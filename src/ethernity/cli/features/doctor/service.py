from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ethernity.artifacts.publish import (
    TRANSACTION_METADATA_NAME,
    PublicationTransaction,
    exclusive_advisory_lock,
    read_transaction_metadata,
    snapshot_artifact_dir,
    sync_directory_metadata,
)
from ethernity.cli.shared.io.frames import recovery_frames_from_scan
from ethernity.crypto.signing import derive_public_key
from ethernity.extensions.layout import (
    canonical_extension_dir_name,
    is_staging_dir_name,
    parse_extension_main_filename,
    parse_extension_shard_filename,
)
from ethernity.extensions.recovery import (
    decode_imported_extension_link,
    imported_document_from_recovery_frames,
)
from ethernity.extensions.staging import (
    EXTENSION_CHAIN_LOCK_FILE_NAME,
    ExtensionPublishPolicy,
    validate_staged_extension_dir,
)
from ethernity.workflows.extension.planning import ResolvedExtendState, resolve_extend_state
from ethernity.workflows.extension.request import ExtensionRequest


@dataclass(frozen=True)
class DoctorTransactionResult:
    path: Path
    transaction_uuid: str
    status: str
    action: str


@dataclass(frozen=True)
class DoctorResult:
    root_dir: Path
    authenticated_head_index: int
    authenticated_head_hash: str
    transactions: tuple[DoctorTransactionResult, ...]


def reconcile_publication_transactions(
    root_dir: str | Path,
    *,
    passphrase: str,
    repair: bool,
    quiet: bool = True,
) -> DoctorResult:
    """Authenticate the published chain and reconcile journaled extension transactions."""

    root = Path(root_dir).expanduser()
    state = _authenticated_state(root, passphrase=passphrase, quiet=quiet)
    extensions_dir = root / "extensions"
    if repair and extensions_dir.is_dir():
        sync_directory_metadata(extensions_dir)
    results: list[DoctorTransactionResult] = []
    legacy_lock = extensions_dir / EXTENSION_CHAIN_LOCK_FILE_NAME
    if legacy_lock.is_dir():
        action = "none"
        if repair:
            try:
                legacy_lock.rmdir()
            except OSError as exc:
                raise ValueError("doctor refused non-empty legacy chain lock directory") from exc
            with exclusive_advisory_lock(legacy_lock, operation_name="doctor lock migration"):
                pass
            sync_directory_metadata(extensions_dir)
            action = "replaced legacy lock directory with persistent lock file"
        results.append(
            DoctorTransactionResult(
                path=legacy_lock,
                transaction_uuid="legacy-directory-lock",
                status="obsolete directory lock",
                action=action,
            )
        )
    final_transaction_dirs = tuple(
        sorted(
            (
                path
                for path in extensions_dir.iterdir()
                if path.is_dir()
                and not path.is_symlink()
                and not is_staging_dir_name(path.name)
                and (path / TRANSACTION_METADATA_NAME).is_file()
            ),
            key=lambda path: path.name,
        )
        if extensions_dir.is_dir()
        else ()
    )
    for final_dir in final_transaction_dirs:
        results.append(_inspect_committed_transaction(final_dir, state=state))

    staging_dirs = (
        tuple(sorted((path for path in extensions_dir.iterdir() if is_staging_dir_name(path.name))))
        if extensions_dir.is_dir()
        else ()
    )
    for staging_dir in staging_dirs:
        if staging_dir.is_symlink() or not staging_dir.is_dir():
            raise ValueError(f"doctor refused invalid staging path: {staging_dir.name}")
        if not (staging_dir / TRANSACTION_METADATA_NAME).is_file():
            if repair:
                raise ValueError(
                    f"doctor refused {staging_dir.name}: a staging directory without a "
                    "transaction record may still be active; remove it manually only after "
                    "excluding a live publisher"
                )
            results.append(
                DoctorTransactionResult(
                    path=staging_dir,
                    transaction_uuid="missing",
                    status="unjournaled staging; ownership unknown",
                    action="none",
                )
            )
            continue
        results.append(
            _reconcile_staging_transaction(
                root,
                staging_dir,
                state=state,
                passphrase=passphrase,
                repair=repair,
                quiet=quiet,
            )
        )
        if repair:
            state = _authenticated_state(root, passphrase=passphrase, quiet=quiet)

    head_index, head_hash = _head_coordinates(state)
    return DoctorResult(
        root_dir=root,
        authenticated_head_index=head_index,
        authenticated_head_hash=head_hash,
        transactions=tuple(results),
    )


def _inspect_committed_transaction(
    final_dir: Path,
    *,
    state: ResolvedExtendState,
) -> DoctorTransactionResult:
    transaction, recorded_snapshot = read_transaction_metadata(final_dir)
    if snapshot_artifact_dir(final_dir) != recorded_snapshot:
        raise ValueError(
            f"doctor refused {final_dir.name}: published artifacts do not match "
            "transaction snapshot"
        )
    if canonical_extension_dir_name(transaction.new_index) != final_dir.name:
        raise ValueError(f"doctor refused {final_dir.name}: transaction index is not canonical")
    _require_committed_transaction_matches_chain(state, transaction, final_dir=final_dir)
    return DoctorTransactionResult(
        path=final_dir,
        transaction_uuid=transaction.transaction_uuid or "unknown",
        status="authenticated committed",
        action="none",
    )


def _reconcile_staging_transaction(
    root: Path,
    staging_dir: Path,
    *,
    state: ResolvedExtendState,
    passphrase: str,
    repair: bool,
    quiet: bool,
) -> DoctorTransactionResult:
    transaction, recorded_snapshot = read_transaction_metadata(staging_dir)
    transaction_uuid = transaction.transaction_uuid or "unknown"
    actual_snapshot = snapshot_artifact_dir(staging_dir)
    if actual_snapshot != recorded_snapshot:
        raise ValueError(
            f"doctor refused {staging_dir.name}: staged artifacts do not match transaction snapshot"
        )

    final_dir = staging_dir.parent / canonical_extension_dir_name(transaction.new_index)
    if final_dir.exists():
        if _transaction_is_in_authenticated_chain(state, transaction):
            action = "none"
            if repair:
                _remove_committed_duplicate(
                    root,
                    staging_dir,
                    final_dir=final_dir,
                    lock_path=staging_dir.parent / EXTENSION_CHAIN_LOCK_FILE_NAME,
                    passphrase=passphrase,
                    quiet=quiet,
                )
                action = "removed duplicate staging directory"
            return DoctorTransactionResult(
                path=staging_dir,
                transaction_uuid=transaction_uuid,
                status="already committed",
                action=action,
            )
        raise ValueError(
            f"doctor refused {staging_dir.name}: final directory exists but is not the "
            "authenticated transaction"
        )

    _require_transaction_parent(state, transaction, staging_dir=staging_dir)
    publish_policy = _infer_publish_policy(staging_dir)
    validate_staged_extension_dir(
        staging_dir,
        expected_index=transaction.new_index,
        publish_policy=publish_policy,
    )
    _authenticate_staged_extension(
        staging_dir,
        state=state,
        transaction=transaction,
        passphrase=passphrase,
        quiet=quiet,
    )
    if repair:
        quarantine_path = _quarantine_unresumable_staging(
            root,
            staging_dir,
            state=state,
            passphrase=passphrase,
            quiet=quiet,
        )
        return DoctorTransactionResult(
            path=quarantine_path,
            transaction_uuid=transaction_uuid,
            status="journaled staging quarantined; publication not resumed",
            action="moved unpublished transaction to sibling quarantine",
        )
    return DoctorTransactionResult(
        path=staging_dir,
        transaction_uuid=transaction_uuid,
        status="journaled staging; automatic resume unavailable",
        action="none",
    )


def _authenticated_state(root: Path, *, passphrase: str, quiet: bool) -> ResolvedExtendState:
    state = resolve_extend_state(
        ExtensionRequest(publish_root=str(root), passphrase=passphrase, quiet=quiet)
    )
    if state.issues:
        first = state.issues[0]
        raise ValueError(
            "doctor requires an authenticated valid published-chain prefix: "
            f"{first.message or 'chain validation failed'}"
        )
    if state.lineage is None:
        raise ValueError("doctor could not resolve authenticated chain coordinates")
    if state.authority is None or state.resolved_passphrase is None:
        raise ValueError("doctor requires the root signing authority and unlock passphrase")
    return state


def _head_coordinates(state: ResolvedExtendState) -> tuple[int, str]:
    lineage = state.lineage
    if lineage is None:
        raise ValueError("doctor could not resolve authenticated chain head")
    return lineage.head_index, lineage.head_doc_hash.hex()


def _transaction_is_in_authenticated_chain(
    state: ResolvedExtendState,
    transaction: PublicationTransaction,
) -> bool:
    lineage = state.lineage
    if lineage is None:
        return False
    if transaction.new_index == 0:
        return transaction.new_hash == lineage.root_doc_hash.hex()
    return any(
        item.index == transaction.new_index and item.doc_hash.hex() == transaction.new_hash
        for item in lineage.extensions
    )


def _require_committed_transaction_matches_chain(
    state: ResolvedExtendState,
    transaction: PublicationTransaction,
    *,
    final_dir: Path,
) -> None:
    lineage = state.lineage
    if lineage is None or transaction.root_hash != lineage.root_doc_hash.hex():
        raise ValueError(f"doctor refused {final_dir.name}: transaction root hash is invalid")
    if not _transaction_is_in_authenticated_chain(state, transaction):
        raise ValueError(f"doctor refused {final_dir.name}: transaction is not authenticated")
    if transaction.new_index == 1:
        expected_parent = lineage.root_doc_hash.hex()
    else:
        expected_parent = next(
            (
                item.doc_hash.hex()
                for item in lineage.extensions
                if item.index == transaction.new_index - 1
            ),
            None,
        )
    if transaction.expected_parent_hash != expected_parent:
        raise ValueError(f"doctor refused {final_dir.name}: transaction parent hash is invalid")


def _require_transaction_parent(
    state: ResolvedExtendState,
    transaction: PublicationTransaction,
    *,
    staging_dir: Path,
) -> None:
    lineage = state.lineage
    if lineage is None:
        raise ValueError("doctor could not resolve authenticated chain coordinates")
    if transaction.root_hash != lineage.root_doc_hash.hex():
        raise ValueError(f"doctor refused {staging_dir.name}: transaction root hash is stale")
    if transaction.expected_parent_hash != lineage.head_doc_hash.hex():
        raise ValueError(f"doctor refused {staging_dir.name}: transaction parent hash is stale")
    if transaction.new_index != lineage.head_index + 1:
        raise ValueError(f"doctor refused {staging_dir.name}: transaction index is not next")


def _authenticate_staged_extension(
    staging_dir: Path,
    *,
    state: ResolvedExtendState,
    transaction: PublicationTransaction,
    passphrase: str,
    quiet: bool,
) -> None:
    qr_paths = [path for path in staging_dir.glob("qr_document-*.pdf") if path.is_file()]
    if len(qr_paths) != 1:
        raise ValueError(f"doctor refused {staging_dir.name}: expected one QR document")
    frames = recovery_frames_from_scan([str(qr_paths[0])], quiet=quiet)
    document = imported_document_from_recovery_frames(
        frames,
        source_label=f"doctor:{staging_dir.name}",
    )
    if document.doc_hash.hex() != transaction.new_hash:
        raise ValueError(f"doctor refused {staging_dir.name}: transaction new hash is invalid")
    lineage = state.lineage
    authority = state.authority
    if lineage is None or authority is None:
        raise ValueError("doctor could not resolve authenticated signing authority")
    decoded = decode_imported_extension_link(
        document,
        passphrase=passphrase,
        expected_sign_pub=derive_public_key(authority.signing_seed),
        quiet=quiet,
        debug=False,
    )
    header = decoded.link.document.header
    if header.index != transaction.new_index:
        raise ValueError(f"doctor refused {staging_dir.name}: decrypted index is invalid")
    if header.root_doc_hash != lineage.root_doc_hash:
        raise ValueError(f"doctor refused {staging_dir.name}: decrypted root hash is invalid")
    if header.parent_doc_hash != lineage.head_doc_hash:
        raise ValueError(f"doctor refused {staging_dir.name}: decrypted parent hash is invalid")


def _infer_publish_policy(staging_dir: Path) -> ExtensionPublishPolicy:
    passphrase_count = 0
    signing_count = 0
    require_kit_index = False
    for path in staging_dir.iterdir():
        if path.name == TRANSACTION_METADATA_NAME:
            continue
        if path.name.startswith("recovery_kit_index-"):
            parsed = parse_extension_main_filename(path.name)
            require_kit_index = parsed.doc_type == "recovery_kit_index"
            continue
        if path.name.startswith("shard-") or path.name.startswith("signing-key-shard-"):
            parsed_shard = parse_extension_shard_filename(path.name)
            if parsed_shard.doc_type == "shard":
                passphrase_count = parsed_shard.share_count
            else:
                signing_count = parsed_shard.share_count
    return ExtensionPublishPolicy(
        require_recovery_kit_index=require_kit_index,
        passphrase_shard_count=passphrase_count,
        signing_key_shard_count=signing_count,
    )


def _remove_committed_duplicate(
    root: Path,
    staging_dir: Path,
    *,
    final_dir: Path,
    lock_path: Path,
    passphrase: str,
    quiet: bool,
) -> None:
    with exclusive_advisory_lock(lock_path, operation_name="doctor repair"):
        state = _authenticated_state(root, passphrase=passphrase, quiet=quiet)
        transaction, recorded_snapshot = read_transaction_metadata(staging_dir)
        if snapshot_artifact_dir(staging_dir) != recorded_snapshot:
            raise ValueError(
                f"doctor refused {staging_dir.name}: staged artifacts changed before cleanup"
            )
        if transaction.transaction_uuid is None:
            raise ValueError("doctor refused transaction without UUID")
        if not final_dir.is_dir() or final_dir.is_symlink():
            raise ValueError(
                f"doctor refused {staging_dir.name}: committed destination changed before cleanup"
            )
        if not _transaction_is_in_authenticated_chain(state, transaction):
            raise ValueError(
                f"doctor refused {staging_dir.name}: transaction is no longer authenticated"
            )
        publish_policy = _infer_publish_policy(staging_dir)
        validated = validate_staged_extension_dir(
            staging_dir,
            expected_index=transaction.new_index,
            publish_policy=publish_policy,
        )
        _authenticate_staged_extension(
            staging_dir,
            state=state,
            transaction=transaction,
            passphrase=passphrase,
            quiet=quiet,
        )
        _require_matching_committed_transaction(final_dir, transaction)
        current = staging_dir.stat(follow_symlinks=False)
        if (current.st_dev, current.st_ino) != validated.staging_dir_identity:
            raise ValueError(
                f"doctor refused {staging_dir.name}: staging directory changed before cleanup"
            )
        if snapshot_artifact_dir(staging_dir) != recorded_snapshot:
            raise ValueError(
                f"doctor refused {staging_dir.name}: staged artifacts changed before cleanup"
            )
        shutil.rmtree(staging_dir)
        sync_directory_metadata(staging_dir.parent)


def _quarantine_unresumable_staging(
    root: Path,
    staging_dir: Path,
    *,
    state: ResolvedExtendState,
    passphrase: str,
    quiet: bool,
) -> Path:
    quarantine_parent = root.parent
    quarantine_name = f".{root.name}.ethernity-doctor-quarantine"
    if staging_dir.stat(follow_symlinks=False).st_dev != quarantine_parent.stat().st_dev:
        quarantine_parent = root
        quarantine_name = ".ethernity-doctor-quarantine"
    quarantine_root = quarantine_parent / quarantine_name
    sync_directory_metadata(quarantine_parent)
    lock_path = staging_dir.parent / EXTENSION_CHAIN_LOCK_FILE_NAME
    with exclusive_advisory_lock(lock_path, operation_name="doctor quarantine"):
        current_state = _authenticated_state(root, passphrase=passphrase, quiet=quiet)
        transaction, recorded_snapshot = read_transaction_metadata(staging_dir)
        _require_transaction_parent(current_state, transaction, staging_dir=staging_dir)
        if snapshot_artifact_dir(staging_dir) != recorded_snapshot:
            raise ValueError(
                f"doctor refused {staging_dir.name}: staged artifacts changed before quarantine"
            )
        publish_policy = _infer_publish_policy(staging_dir)
        validated = validate_staged_extension_dir(
            staging_dir,
            expected_index=transaction.new_index,
            publish_policy=publish_policy,
        )
        _authenticate_staged_extension(
            staging_dir,
            state=current_state,
            transaction=transaction,
            passphrase=passphrase,
            quiet=quiet,
        )
        if current_state.lineage != state.lineage:
            raise ValueError(
                f"doctor refused {staging_dir.name}: authenticated chain changed before quarantine"
            )
        if quarantine_root.is_symlink() or (
            quarantine_root.exists() and not quarantine_root.is_dir()
        ):
            raise ValueError("doctor quarantine path must be a non-symlink directory")
        quarantine_root.mkdir(mode=0o700, exist_ok=True)
        sync_directory_metadata(quarantine_parent)
        sync_directory_metadata(quarantine_root)
        quarantine_path = quarantine_root / staging_dir.name
        if quarantine_path.exists() or quarantine_path.is_symlink():
            raise ValueError(f"doctor quarantine destination already exists: {quarantine_path}")
        current = staging_dir.stat(follow_symlinks=False)
        if (current.st_dev, current.st_ino) != validated.staging_dir_identity:
            raise ValueError(
                f"doctor refused {staging_dir.name}: staging directory changed before quarantine"
            )
        staging_dir.rename(quarantine_path)
        sync_directory_metadata(staging_dir.parent)
        sync_directory_metadata(quarantine_root)
        return quarantine_path


def _require_matching_committed_transaction(
    final_dir: Path,
    staging_transaction: PublicationTransaction,
) -> None:
    metadata_path = final_dir / TRANSACTION_METADATA_NAME
    if not metadata_path.exists():
        return
    committed, committed_snapshot = read_transaction_metadata(final_dir)
    if snapshot_artifact_dir(final_dir) != committed_snapshot:
        raise ValueError(
            f"doctor refused {final_dir.name}: committed artifacts do not match "
            "transaction snapshot"
        )
    if (
        committed.root_hash != staging_transaction.root_hash
        or committed.expected_parent_hash != staging_transaction.expected_parent_hash
        or committed.new_index != staging_transaction.new_index
        or committed.new_hash != staging_transaction.new_hash
        or committed.transaction_uuid != staging_transaction.transaction_uuid
    ):
        raise ValueError(
            f"doctor refused {final_dir.name}: staging transaction does not match "
            "committed metadata"
        )
