#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Read-only planning helpers for extension inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ethernity.cli.features.extend.scope import (
    SelectedExtendScope,
    empty_scope_inspection_payload,
    load_selected_scope,
    summarize_scope_diff,
)
from ethernity.cli.features.recover.chain import (
    DecodedExtensionLink,
    DiscoveredRecoveryExtension,
    RecoveryChainInspection,
    RecoveryExtensionInventory,
    RecoveryHeadTrustRefusal,
    RecoveryReplayFailure,
    decode_authenticated_extension_link,
    decode_root_manifest as _decode_root_manifest_shared,
    locate_replay_failure,
    resolve_root_manifest_authority,
    scan_extension_carriers,
)
from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    _resolve_auth_payload,
    _validated_shard_payloads_from_frames,
)
from ethernity.cli.features.recover.planning import RecoveryInspection, inspect_recovery_inputs
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import _doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.io.fallback_parser import format_fallback_error
from ethernity.cli.shared.io.frames import (
    _frame_from_fallback,
    _frames_from_payloads,
    _recovery_frames_from_scan,
    _shard_frames_from_scan,
    format_shard_input_error,
)
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.paths import expanduser_cli_paths
from ethernity.cli.shared.types import ExtendArgs
from ethernity.config.load import load_app_config
from ethernity.crypto import sharding as sharding_module
from ethernity.encoding.framing import Frame
from ethernity.extensions.chain import (
    LogicalFileState,
    build_chain_available_chunks,
    extract_root_logical_state,
    reconstruct_latest_logical_state,
    validate_extension_chain,
)
from ethernity.extensions.discovery import (
    DiscoveredExtensionDirectory,
    DiscoveredExtensionMainCarrier,
    discover_validated_extension_directories,
    payload_main_carriers,
    require_backup_root_dir,
)
from ethernity.formats import EnvelopeManifest
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    derive_chain_id,
)
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC


@dataclass(frozen=True)
class ExtendInspection:
    doc_id: str | None
    root_dir: str
    input_label: str
    input_detail: str
    input_kind: str
    source_summary: dict[str, object] | None
    frame_counts: dict[str, int]
    root_doc_id: str | None
    root_doc_hash: str | None
    chain_id: str | None
    auth_status: str
    unlock: dict[str, object]
    discovered_extension_dirs: tuple[int, ...]
    validated_head_index: int | None
    validated_head_doc_hash: str | None
    available_extensions: tuple[dict[str, object], ...]
    ancestry_valid: bool | None
    validated_head_auth_status: str | None
    validated_head_root_authority_verified: bool | None
    signing_authority: dict[str, object]
    selected_scope: dict[str, object] | None
    diff_summary: dict[str, object] | None
    blocking_issues: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ResolvedExtendState:
    inspection: ExtendInspection
    loaded_scope: SelectedExtendScope | None
    current_state: tuple[LogicalFileState, ...] | None
    available_chunks: tuple[tuple[bytes, bytes], ...]
    resolved_passphrase: str | None
    root_doc_hash: bytes | None
    parent_doc_hash: bytes | None
    next_index: int | None
    signing_seed: bytes | None
    chunking: ExtensionChunkingProfile | None
    root_passphrase_shard_threshold: int | None = None
    root_passphrase_shard_count: int = 0


def inspect_from_args(args: ExtendArgs) -> ExtendInspection:
    return resolve_extend_state(args).inspection


def require_extend_root_dir(
    args: ExtendArgs,
    *,
    command_name: str,
) -> str:
    if not args.root_dir:
        raise ApiCommandError(
            code="INPUT_REQUIRED",
            message=f"--root-dir is required for `{command_name}`",
        )
    return args.root_dir


def resolve_extend_state(args: ExtendArgs) -> ResolvedExtendState:
    """Inspect extension layout from a writable backup root directory."""

    root_dir_arg = require_extend_root_dir(args, command_name="ethernity api inspect extend")
    try:
        root_dir = require_backup_root_dir(root_dir_arg)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("root backup directory not found:"):
            raise ApiCommandError(
                code="NOT_FOUND",
                message=message,
                details={"path": root_dir_arg},
            ) from exc
        raise ApiCommandError(
            code="INVALID_INPUT",
            message=message,
            details={"path": root_dir_arg},
        ) from exc

    blocking_issues: list[dict[str, object]] = []
    discovered_extension_dirs: tuple[int, ...] = ()
    available_extensions: tuple[dict[str, object], ...] = ()
    new_chain_chunking = _default_chunking_profile(args)
    input_kind = "standalone_root"
    extension_inventory: RecoveryExtensionInventory | None = None
    try:
        extension_inventory = _inspect_published_extension_inventory(
            root_dir,
            quiet=args.quiet,
        )
        discovered_extension_dirs = _discovered_extension_indices(extension_inventory)
        available_extensions = _available_extensions_from_inventory(extension_inventory)
        if discovered_extension_dirs:
            input_kind = "extended_root"
        if extension_inventory.failure is not None:
            blocking_issues.append(
                {
                    "code": "EXTENSION_LAYOUT_INVALID",
                    "message": extension_inventory.failure.message,
                    "details": {"root_dir": str(root_dir)},
                }
            )
    except ValueError as exc:
        blocking_issues.append(
            {
                "code": "EXTENSION_LAYOUT_INVALID",
                "message": str(exc),
                "details": {"root_dir": str(root_dir)},
            }
        )

    loaded_scope = None
    selected_scope = None
    if args.input or args.input_dir:
        try:
            loaded_scope = load_selected_scope(args)
        except FileNotFoundError as exc:
            raise ApiCommandError(
                code="NOT_FOUND",
                message=str(exc),
                details={"path": exc.filename},
            ) from exc
        except ValueError as exc:
            raise ApiCommandError(
                code="INVALID_INPUT",
                message=str(exc),
            ) from exc
        if loaded_scope is not None:
            selected_scope = loaded_scope.to_inspection_payload()
    elif args.base_dir:
        selected_scope = empty_scope_inspection_payload(base_dir_arg=args.base_dir)

    root_inspection = _inspect_root_recovery(root_dir, args)
    blocking_issues.extend(dict(item) for item in root_inspection.blocking_issues)

    doc_id_hex = root_inspection.doc_id.hex()
    doc_hash_hex = root_inspection.doc_hash.hex()
    chain_id_hex = derive_chain_id(root_inspection.doc_hash).hex()
    source_summary: dict[str, object] | None = None
    validated_head_index: int | None = None
    validated_head_doc_hash: str | None = None
    ancestry_valid: bool | None = None
    validated_head_auth_status: str | None = None
    validated_head_root_authority_verified: bool | None = None
    signing_authority: dict[str, object] = {
        "available": False,
        "satisfied": False,
        "source": None,
    }
    diff_summary: dict[str, object] | None = None
    root_doc_hash_bytes: bytes | None = root_inspection.doc_hash
    parent_doc_hash: bytes | None = None
    next_index: int | None = None
    signing_seed: bytes | None = None
    chunking: ExtensionChunkingProfile | None = None
    root_passphrase_shard_threshold = (
        root_inspection.unlock.required_shard_threshold
        if root_inspection.unlock.mode == "shards"
        else None
    )
    root_passphrase_shard_count = (
        root_inspection.unlock.shard_share_count
        if root_inspection.unlock.mode == "shards"
        and root_inspection.unlock.shard_share_count is not None
        else 0
    )

    current_state: tuple[LogicalFileState, ...] | None = None
    available_chunks: tuple[tuple[bytes, bytes], ...] = ()
    if root_inspection.unlock.satisfied and root_inspection.unlock.resolved_passphrase is not None:
        try:
            manifest, payload = _decode_root_manifest(
                root_inspection.ciphertext,
                passphrase=root_inspection.unlock.resolved_passphrase,
            )
            source_summary = _manifest_summary_payload(manifest)
            current_state = extract_root_logical_state(manifest, payload)
            if manifest.sealed:
                blocking_issues.append(
                    _blocking_issue(
                        "SEALED_ROOT_NOT_EXTENDABLE",
                        "sealed roots are terminal in v1 and cannot be extended",
                    )
                )
            else:
                authority = resolve_root_manifest_authority(manifest, root_inspection.auth_payload)
                embedded_signing_seed = manifest.signing_seed
                if embedded_signing_seed is None:
                    raise ValueError("root backup manifest is missing an embedded signing seed")
                if authority.mismatch:
                    blocking_issues.append(
                        _blocking_issue(
                            "ROOT_AUTHORITY_MISMATCH",
                            (
                                "embedded signing seed does not match the verified "
                                "root AUTH authority"
                            ),
                        )
                    )
                    signing_authority = {
                        "available": True,
                        "satisfied": False,
                        "source": None,
                    }
                else:
                    signing_seed = embedded_signing_seed
                    signing_authority = {
                        "available": True,
                        "satisfied": True,
                        "source": "embedded_seed",
                    }
                    if root_passphrase_shard_count <= 0:
                        try:
                            (
                                root_passphrase_shard_threshold,
                                root_passphrase_shard_count,
                            ) = _published_root_passphrase_shard_policy(
                                root_dir,
                                root_doc_id=root_inspection.doc_id,
                                root_doc_hash=root_inspection.doc_hash,
                                sign_pub=authority.embedded_sign_pub,
                                quiet=args.quiet,
                            )
                        except ValueError as exc:
                            blocking_issues.append(
                                _blocking_issue(
                                    api_codes.ROOT_SHARD_POLICY_INVALID,
                                    str(exc),
                                    details={"stage": "shards"},
                                )
                            )

                    if (
                        extension_inventory is not None
                        and _extension_chain_present(extension_inventory)
                        and not manifest.sealed
                    ):
                        (
                            current_state,
                            validated_head_index,
                            validated_head_doc_hash,
                            ancestry_valid,
                            parent_doc_hash,
                            next_index,
                            chunking,
                            available_chunks,
                            available_extensions,
                            validated_head_auth_status,
                            validated_head_root_authority_verified,
                            discovered_extension_dirs,
                            input_kind,
                        ) = _reconstruct_extension_state(
                            root_dir=root_dir,
                            manifest=manifest,
                            payload=payload,
                            root_doc_hash=root_inspection.doc_hash,
                            passphrase=root_inspection.unlock.resolved_passphrase,
                            expected_sign_pub=authority.embedded_sign_pub,
                            root_auth_status=root_inspection.auth_status,
                            blocking_issues=blocking_issues,
                            inventory=extension_inventory,
                            new_chain_chunking=new_chain_chunking,
                            quiet=args.quiet,
                        )
                    else:
                        validated_head_index = 0
                        validated_head_doc_hash = root_inspection.doc_hash.hex()
                        ancestry_valid = True
                        validated_head_auth_status = root_inspection.auth_status
                        validated_head_root_authority_verified = (
                            authority.embedded_sign_pub is not None
                        )
                        parent_doc_hash = root_inspection.doc_hash
                        next_index = 1
                        chunking = new_chain_chunking
                        available_chunks = _sorted_chunk_items(
                            build_chain_available_chunks(current_state, chunking)
                        )

            if current_state is not None and loaded_scope is not None:
                diff = summarize_scope_diff(current_state, loaded_scope)
                diff_summary = diff.to_payload()
                if diff.missing_paths:
                    blocking_issues.append(
                        _blocking_issue(
                            "DELETE_NOT_SUPPORTED",
                            (
                                "selected scope omits previously backed paths; "
                                "delete/rename is unsupported"
                            ),
                            details={"missing_paths": list(diff.missing_paths)},
                        )
                    )
        except ValueError as exc:
            blocking_issues.append(
                _blocking_issue(
                    "UNLOCK_FAILED",
                    str(exc),
                    details={"stage": "decrypt"},
                )
            )

    inspection = ExtendInspection(
        doc_id=doc_id_hex,
        root_dir=str(root_dir),
        input_label="Backup root directory",
        input_detail=str(root_dir.resolve()),
        input_kind=input_kind,
        source_summary=source_summary,
        frame_counts={
            "main": len(root_inspection.main_frames),
            "auth": len(root_inspection.auth_frames),
            "shard": len(root_inspection.shard_frames),
        },
        root_doc_id=doc_id_hex,
        root_doc_hash=doc_hash_hex,
        chain_id=chain_id_hex,
        auth_status=root_inspection.auth_status,
        unlock={
            "mode": root_inspection.unlock.mode,
            "passphrase_provided": root_inspection.unlock.passphrase_provided,
            "validated_shard_count": root_inspection.unlock.validated_shard_count,
            "required_shard_threshold": root_inspection.unlock.required_shard_threshold,
            "shard_share_count": root_inspection.unlock.shard_share_count,
            "satisfied": root_inspection.unlock.satisfied,
        },
        discovered_extension_dirs=discovered_extension_dirs,
        validated_head_index=validated_head_index,
        validated_head_doc_hash=validated_head_doc_hash,
        available_extensions=available_extensions,
        ancestry_valid=ancestry_valid,
        validated_head_auth_status=validated_head_auth_status,
        validated_head_root_authority_verified=validated_head_root_authority_verified,
        signing_authority=signing_authority,
        selected_scope=selected_scope,
        diff_summary=diff_summary,
        blocking_issues=tuple(blocking_issues),
    )
    return ResolvedExtendState(
        inspection=inspection,
        loaded_scope=loaded_scope,
        current_state=current_state,
        available_chunks=available_chunks,
        resolved_passphrase=root_inspection.unlock.resolved_passphrase,
        root_doc_hash=root_doc_hash_bytes,
        parent_doc_hash=parent_doc_hash,
        next_index=next_index,
        signing_seed=signing_seed,
        chunking=chunking,
        root_passphrase_shard_threshold=root_passphrase_shard_threshold,
        root_passphrase_shard_count=root_passphrase_shard_count,
    )


def _inspect_root_recovery(root_dir: Path, args: ExtendArgs) -> RecoveryInspection:
    scan_paths = _published_root_scan_paths(root_dir)
    if not scan_paths:
        raise ApiCommandError(
            code=api_codes.NOT_FOUND,
            message="root backup documents not found in the writable backup directory",
            details={"root_dir": str(root_dir)},
        )
    frames = _recovery_frames_from_scan(scan_paths, quiet=args.quiet)
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = (
        _shard_frames_from_extend_args(args, quiet=args.quiet)
    )
    return inspect_recovery_inputs(
        frames=frames,
        extra_auth_frames=[],
        shard_frames=shard_frames,
        passphrase=args.passphrase,
        allow_unsigned=False,
        input_label="Backup root directory",
        input_detail=str(root_dir.resolve()),
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        quiet=args.quiet,
    )


def _published_root_passphrase_shard_policy(
    root_dir: Path,
    *,
    root_doc_id: bytes,
    root_doc_hash: bytes,
    sign_pub: bytes | None,
    quiet: bool,
) -> tuple[int | None, int]:
    paths = sorted(root_dir.glob("shard-*.pdf"))
    if not paths:
        return None, 0
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"root passphrase shard must not be a symlink: {path.name}")
    frames = _shard_frames_from_scan([str(path) for path in paths], quiet=quiet)
    if not frames:
        return None, 0
    try:
        shares = _validated_shard_payloads_from_frames(
            frames,
            expected_doc_id=root_doc_id,
            expected_doc_hash=root_doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=sign_pub is None,
            key_type=sharding_module.KEY_TYPE_PASSPHRASE,
            secret_label="passphrase",
        )
    except InsufficientShardError as exc:
        if exc.share_count is not None:
            return None, 0
        raise
    first = shares[0]
    if len(shares) != first.share_count:
        return None, 0
    return first.threshold, first.share_count


def _shard_frames_from_extend_args(
    args: ExtendArgs,
    *,
    quiet: bool,
) -> tuple[list[Frame], list[str], list[str], list[str]]:
    shard_fallback_files = expanduser_cli_paths(list(args.shard_fallback_file or []))
    shard_payloads_file = expanduser_cli_paths(list(args.shard_payloads_file or []))
    shard_scan = expanduser_cli_paths(list(args.shard_scan or []))
    shard_frames: list[Frame] = list(args.shard_frames or [])
    for path in shard_fallback_files:
        try:
            shard_frames.append(_frame_from_fallback(path, quiet=quiet))
        except ValueError as exc:
            raise ValueError(format_fallback_error(exc, context="Shard recovery text")) from exc
    for path in shard_payloads_file:
        try:
            shard_frames.extend(_frames_from_payloads(path, label="shard QR payloads"))
        except ValueError as exc:
            raise ValueError(format_shard_input_error(exc)) from exc
    if shard_scan:
        try:
            shard_frames.extend(_shard_frames_from_scan(shard_scan, quiet=quiet))
        except ValueError as exc:
            raise ValueError(format_shard_input_error(exc)) from exc
    if (
        args.shard_frames or shard_fallback_files or shard_payloads_file or shard_scan
    ) and not shard_frames:
        raise ValueError("no shard payloads found; check shard inputs and try again")
    return shard_frames, shard_fallback_files, shard_payloads_file, shard_scan


def _decode_root_manifest(ciphertext: bytes, *, passphrase: str) -> tuple[EnvelopeManifest, bytes]:
    return _decode_root_manifest_shared(ciphertext=ciphertext, passphrase=passphrase, debug=False)


def _available_extensions_from_inventory(
    inventory: RecoveryExtensionInventory,
) -> tuple[dict[str, object], ...]:
    if inventory.failure is not None:
        return ()
    return tuple(
        {
            "dir_name": item.dir_name,
            "doc_id": item.doc_id_hex,
            "doc_hash": item.doc_hash.hex(),
        }
        for item in inventory.extensions
    )


def _discovered_extension_indices(inventory: RecoveryExtensionInventory) -> tuple[int, ...]:
    if inventory.failure is not None and inventory.extensions:
        return ()
    indices = [item.index for item in inventory.extensions]
    if (
        inventory.failure is not None
        and inventory.failure.head_index is not None
        and _extension_carrier_scan_failure(inventory.failure)
    ):
        if inventory.failure.head_index not in indices:
            indices.append(inventory.failure.head_index)
    return tuple(indices)


def _published_root_scan_paths(root_dir: Path) -> list[str]:
    paths: list[str] = []
    for name in ("qr_document.pdf", "recovery_document.pdf"):
        candidate = root_dir / name
        if candidate.is_symlink():
            raise ApiCommandError(
                code=api_codes.INVALID_INPUT,
                message=f"root backup MAIN carrier must not be a symlink: {name}",
                details={"root_dir": str(root_dir)},
            )
        if candidate.is_file():
            paths.append(str(candidate))
    return paths


def _inspect_published_extension_inventory(
    root_dir: Path,
    *,
    quiet: bool,
) -> RecoveryExtensionInventory:
    discovery = discover_validated_extension_directories(root_dir)
    extensions: list[DiscoveredRecoveryExtension] = []
    failure: RecoveryReplayFailure | None = None
    for item in discovery.directories:
        try:
            ciphertext, auth_frames = _scan_published_extension_payload_carriers(
                item,
                quiet=quiet,
            )
            doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
            if doc_id.hex() != item.doc_id_hex:
                raise ValueError(
                    f"extension {item.dir_name} MAIN carriers do not match the filename doc_id"
                )
        except ValueError as exc:
            failure = RecoveryReplayFailure(
                stage="scan",
                message=str(exc),
                head_index=item.index,
                head_dir_name=item.dir_name,
            )
            break
        extensions.append(
            DiscoveredRecoveryExtension(
                index=item.index,
                dir_name=item.dir_name,
                doc_id_hex=item.doc_id_hex,
                doc_hash=doc_hash,
                ciphertext=ciphertext,
                auth_frames=tuple(auth_frames),
            )
        )

    if failure is None and discovery.first_invalid_message is not None:
        failure = RecoveryReplayFailure(
            stage="layout",
            message=discovery.first_invalid_message,
            head_index=len(extensions) + 1,
            head_dir_name=discovery.first_invalid_dir_name,
        )
    latest = extensions[-1] if extensions else None
    return RecoveryExtensionInventory(
        extensions=tuple(extensions),
        latest_head_index=None if latest is None else latest.index,
        latest_head_doc_hash=None if latest is None else latest.doc_hash.hex(),
        latest_head_dir_name=None if latest is None else latest.dir_name,
        failure=failure,
    )


def _scan_published_extension_payload_carriers(
    item: DiscoveredExtensionDirectory,
    *,
    quiet: bool,
) -> tuple[bytes, list[Frame]]:
    ciphertext: bytes | None = None
    auth_frames: list[Frame] | None = None
    doc_hash: bytes | None = None
    auth_sign_pub: bytes | None = None
    for carrier in payload_main_carriers(item.main_carriers):
        (
            candidate_ciphertext,
            candidate_auth_frames,
            candidate_auth_sign_pub,
        ) = _scan_published_extension_payload_carrier(item, carrier, quiet=quiet)
        candidate_doc_id, candidate_doc_hash = _doc_id_and_hash_from_ciphertext(
            candidate_ciphertext
        )
        if candidate_doc_id.hex() != item.doc_id_hex:
            raise ValueError(
                f"extension {item.dir_name} {carrier.doc_type} carrier does not match "
                "the filename doc_id"
            )
        if ciphertext is None:
            ciphertext = candidate_ciphertext
            auth_frames = candidate_auth_frames
            doc_hash = candidate_doc_hash
            auth_sign_pub = candidate_auth_sign_pub
            continue
        if candidate_ciphertext != ciphertext or candidate_doc_hash != doc_hash:
            raise ValueError(
                f"extension {item.dir_name} machine-readable MAIN carriers reconstruct "
                "different documents"
            )
        if candidate_auth_sign_pub != auth_sign_pub:
            raise ValueError(
                f"extension {item.dir_name} machine-readable MAIN carrier AUTH signing "
                "authorities differ"
            )
    if ciphertext is None or auth_frames is None:
        raise ValueError(f"extension {item.dir_name} MAIN carriers could not be reconstructed")
    return ciphertext, auth_frames


def _scan_published_extension_payload_carrier(
    item: DiscoveredExtensionDirectory,
    carrier: DiscoveredExtensionMainCarrier,
    *,
    quiet: bool,
) -> tuple[bytes, list[Frame], bytes]:
    try:
        if carrier.doc_type != "qr_document":
            raise ValueError(f"{carrier.doc_type} is not a machine-readable extension carrier")
        ciphertext, auth_frames = scan_extension_carriers([str(carrier.path)], quiet=quiet)
        doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
        auth_payload, _auth_status = _resolve_auth_payload(
            list(auth_frames),
            doc_id=doc_id,
            doc_hash=doc_hash,
            allow_unsigned=False,
            require_auth=True,
            quiet=quiet,
        )
        if auth_payload is None:
            raise ValueError("missing required AUTH payload")
    except Exception as exc:
        raise ValueError(
            f"extension {item.dir_name} {carrier.doc_type} carrier could not be "
            f"independently reconstructed: {exc}"
        ) from exc
    return ciphertext, auth_frames, auth_payload.sign_pub


def _extension_carrier_scan_failure(failure: Any) -> bool:
    message = str(getattr(failure, "message", ""))
    return (
        "MAIN carriers could not be reconstructed" in message
        or "MAIN carrier is not independently recoverable" in message
    )


def _extension_chain_present(inventory: RecoveryExtensionInventory) -> bool:
    return bool(inventory.extensions) or inventory.failure is not None


def _inspect_published_extension_chain(
    *,
    manifest: EnvelopeManifest,
    payload: bytes,
    root_doc_hash: bytes,
    passphrase: str,
    expected_sign_pub: bytes | None,
    allow_unsigned: bool,
    quiet: bool,
    debug: bool,
    inventory: RecoveryExtensionInventory,
) -> RecoveryChainInspection:
    root_state = extract_root_logical_state(manifest, payload)
    if expected_sign_pub is None:
        return RecoveryChainInspection(
            inventory=inventory,
            links=(),
            latest_state=root_state,
            locked_chunking=None,
            refusal=RecoveryHeadTrustRefusal(
                code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                message="extension replay requires an unsealed root signing authority",
                details={"stage": "auth", "validated_head_index": 0},
            ),
            validated_head_index=0,
            validated_head_doc_hash=root_doc_hash.hex(),
            validated_head_auth_status=None,
            validated_head_root_authority_verified=False,
        )

    links: list[DecodedExtensionLink] = []
    for item in inventory.extensions:
        try:
            decoded = decode_authenticated_extension_link(
                item,
                passphrase=passphrase,
                expected_sign_pub=expected_sign_pub,
                allow_unsigned=allow_unsigned,
                quiet=quiet,
                debug=debug,
            )
        except ValueError as exc:
            head_index, head_hash, head_auth, head_verified = _validated_head_details(
                root_doc_hash,
                links,
            )
            return RecoveryChainInspection(
                inventory=inventory,
                links=tuple(links),
                latest_state=None,
                locked_chunking=None,
                refusal=RecoveryHeadTrustRefusal(
                    code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                    message=str(exc),
                    details={
                        "stage": "auth",
                        "failed_extension_index": item.index,
                        "validated_head_index": head_index,
                        "validated_head_doc_hash": head_hash,
                    },
                ),
                validated_head_index=head_index,
                validated_head_doc_hash=head_hash,
                validated_head_auth_status=head_auth,
                validated_head_root_authority_verified=head_verified,
            )
        links.append(decoded)

    if not links:
        return RecoveryChainInspection(
            inventory=inventory,
            links=(),
            latest_state=root_state,
            locked_chunking=None,
            refusal=None,
            validated_head_index=0,
            validated_head_doc_hash=root_doc_hash.hex(),
            validated_head_auth_status=None,
            validated_head_root_authority_verified=expected_sign_pub is not None,
        )

    try:
        locked_chunking = validate_extension_chain(
            root_doc_hash=root_doc_hash,
            extensions=tuple(item.link for item in links),
        )
        latest_state = reconstruct_latest_logical_state(
            manifest,
            payload,
            root_doc_hash=root_doc_hash,
            extensions=tuple(item.link for item in links),
        )
    except ValueError as exc:
        failure, validated_links = locate_replay_failure(
            root_manifest=manifest,
            payload=payload,
            root_doc_hash=root_doc_hash,
            selected_links=tuple(links),
        )
        head_index, head_hash, head_auth, head_verified = _validated_head_details(
            root_doc_hash,
            validated_links,
        )
        return RecoveryChainInspection(
            inventory=inventory,
            links=tuple(links),
            latest_state=None,
            locked_chunking=None,
            refusal=RecoveryHeadTrustRefusal(
                code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                message=str(exc),
                details={
                    "stage": "chain",
                    "failure_head_index": failure.link.document.header.index,
                    "failure_head_doc_hash": failure.link.doc_hash.hex(),
                    "validated_head_index": head_index,
                    "validated_head_doc_hash": head_hash,
                },
            ),
            validated_head_index=head_index,
            validated_head_doc_hash=head_hash,
            validated_head_auth_status=head_auth,
            validated_head_root_authority_verified=head_verified,
        )

    latest = links[-1]
    return RecoveryChainInspection(
        inventory=inventory,
        links=tuple(links),
        latest_state=latest_state,
        locked_chunking=locked_chunking,
        refusal=None,
        validated_head_index=latest.link.document.header.index,
        validated_head_doc_hash=latest.link.doc_hash.hex(),
        validated_head_auth_status=latest.auth_status,
        validated_head_root_authority_verified=latest.root_authority_verified,
    )


def _validated_head_details(
    root_doc_hash: bytes,
    links: list[DecodedExtensionLink] | tuple[DecodedExtensionLink, ...],
) -> tuple[int, str, str | None, bool | None]:
    if not links:
        return 0, root_doc_hash.hex(), None, None
    latest = links[-1]
    return (
        latest.link.document.header.index,
        latest.link.doc_hash.hex(),
        latest.auth_status,
        latest.root_authority_verified,
    )


def _available_extensions_from_recovery_chain(
    chain_inspection: RecoveryChainInspection,
) -> tuple[dict[str, object], ...]:
    available_extensions: list[dict[str, object]] = []
    for index, item in enumerate(chain_inspection.inventory.extensions):
        extension_payload: dict[str, object] = {
            "dir_name": item.dir_name,
            "doc_id": item.doc_id_hex,
            "doc_hash": item.doc_hash.hex(),
        }
        if index < len(chain_inspection.links):
            decoded_link = chain_inspection.links[index]
            extension_payload["auth_status"] = decoded_link.auth_status
            extension_payload["root_authority_verified"] = decoded_link.root_authority_verified
        available_extensions.append(extension_payload)
    return tuple(available_extensions)


def _sorted_chunk_items(chunk_map: dict[bytes, bytes]) -> tuple[tuple[bytes, bytes], ...]:
    return tuple((chunk_id, chunk_map[chunk_id]) for chunk_id in sorted(chunk_map))


def _reconstruct_extension_state(
    *,
    root_dir: Path,
    manifest: EnvelopeManifest,
    payload: bytes,
    root_doc_hash: bytes,
    passphrase: str,
    expected_sign_pub: bytes | None,
    root_auth_status: str | None,
    blocking_issues: list[dict[str, object]],
    inventory: RecoveryExtensionInventory,
    new_chain_chunking: ExtensionChunkingProfile,
    quiet: bool,
) -> tuple[
    tuple[LogicalFileState, ...] | None,
    int | None,
    str | None,
    bool | None,
    bytes | None,
    int | None,
    ExtensionChunkingProfile | None,
    tuple[tuple[bytes, bytes], ...],
    tuple[dict[str, object], ...],
    str | None,
    bool | None,
    tuple[int, ...],
    str,
]:
    if expected_sign_pub is None:
        raise ValueError("root backup manifest is missing an embedded signing seed")

    root_state = extract_root_logical_state(manifest, payload)
    chain_inspection = _inspect_published_extension_chain(
        manifest=manifest,
        payload=payload,
        root_doc_hash=root_doc_hash,
        passphrase=passphrase,
        expected_sign_pub=expected_sign_pub,
        allow_unsigned=False,
        quiet=quiet,
        debug=False,
        inventory=inventory,
    )
    discovered_extension_dirs = tuple(item.index for item in chain_inspection.inventory.extensions)
    input_kind = "extended_root" if discovered_extension_dirs else "standalone_root"
    available_extensions = _available_extensions_from_recovery_chain(chain_inspection)

    if chain_inspection.refusal is not None:
        validated_head_auth_status = chain_inspection.validated_head_auth_status
        validated_head_root_authority_verified = (
            chain_inspection.validated_head_root_authority_verified
        )
        refusal_details = dict(chain_inspection.refusal.details)
        if chain_inspection.validated_head_index == 0:
            validated_head_auth_status = root_auth_status
            validated_head_root_authority_verified = expected_sign_pub is not None
            refusal_details["validated_head_auth_status"] = validated_head_auth_status
            refusal_details["validated_head_root_authority_verified"] = (
                validated_head_root_authority_verified
            )
        blocking_issues[:] = [
            issue
            for issue in blocking_issues
            if issue.get("code") not in {"EXTENSION_LAYOUT_INVALID", "CHAIN_INVALID"}
        ]
        blocking_issues.insert(
            0,
            _blocking_issue(
                chain_inspection.refusal.code,
                chain_inspection.refusal.message,
                details=refusal_details,
            ),
        )
        return (
            None,
            chain_inspection.validated_head_index,
            chain_inspection.validated_head_doc_hash,
            False,
            None,
            None,
            None,
            (),
            available_extensions,
            validated_head_auth_status,
            validated_head_root_authority_verified,
            discovered_extension_dirs,
            input_kind,
        )

    if not chain_inspection.links or chain_inspection.latest_state is None:
        return (
            root_state,
            chain_inspection.validated_head_index,
            chain_inspection.validated_head_doc_hash,
            True,
            root_doc_hash,
            1,
            new_chain_chunking,
            _sorted_chunk_items(build_chain_available_chunks(root_state, new_chain_chunking)),
            available_extensions,
            chain_inspection.validated_head_auth_status,
            chain_inspection.validated_head_root_authority_verified,
            discovered_extension_dirs,
            input_kind,
        )

    locked_chunking = chain_inspection.locked_chunking
    if locked_chunking is None:
        raise ValueError("extension chain requires a locked chunking profile")

    return (
        chain_inspection.latest_state,
        chain_inspection.validated_head_index,
        chain_inspection.validated_head_doc_hash,
        True,
        chain_inspection.links[-1].link.doc_hash,
        chain_inspection.validated_head_index + 1,
        locked_chunking,
        _sorted_chunk_items(
            build_chain_available_chunks(
                root_state,
                locked_chunking,
                extensions=tuple(item.link for item in chain_inspection.links),
            )
        ),
        available_extensions,
        chain_inspection.validated_head_auth_status,
        chain_inspection.validated_head_root_authority_verified,
        discovered_extension_dirs,
        input_kind,
    )


def _manifest_summary_payload(manifest: EnvelopeManifest) -> dict[str, object]:
    return {
        "format_version": manifest.format_version,
        "input_origin": manifest.input_origin,
        "input_roots": list(manifest.input_roots),
        "sealed": manifest.sealed,
        "payload_codec": manifest.payload_codec,
        "payload_raw_len": manifest.payload_raw_len,
        "file_count": len(manifest.files),
    }


def _blocking_issue(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
    }


def _default_chunking_profile(args: ExtendArgs) -> ExtensionChunkingProfile:
    try:
        return _default_chunking_profile_from_config(args)
    except ValueError as exc:
        raise ApiCommandError(
            code=api_codes.INVALID_INPUT,
            message=str(exc),
            details={"config": args.config},
        ) from exc


def _default_chunking_profile_from_config(args: ExtendArgs) -> ExtensionChunkingProfile:
    configured = load_app_config(args.config, paper_size=args.paper).extension_chunking
    return ExtensionChunkingProfile(
        algorithm_id=CHUNK_ALGORITHM_FASTCDC,
        target_size=configured.target_size,
        min_size=configured.min_size,
        max_size=configured.max_size,
    )
