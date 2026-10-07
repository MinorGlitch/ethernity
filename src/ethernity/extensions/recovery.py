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
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Recover extension chains from carrier content.

Recovery does not rely on extension directory names or document filenames. Scanned content is
grouped by frame/doc identity, then authenticated and ordered using ciphertext hashes and decrypted
headers.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Protocol

from ethernity.core.bounds import (
    MAX_CIPHERTEXT_BYTES,
    MAX_RECOVERY_DECODED_CHUNK_BYTES,
)
from ethernity.crypto import decrypt_bytes, normalize_valid_bip39_whitespace
from ethernity.crypto.age_policy import RecoveryResourceLimitError
from ethernity.crypto.age_runtime import (
    AgeError,
    PassphraseAuthenticationError,
    decrypt_bytes_with_exact_passphrase,
)
from ethernity.crypto.document_identity import (
    doc_id_and_hash_from_ciphertext,
    parse_doc_hash_hex,
)
from ethernity.crypto.signing import (
    AuthPayload,
    decode_auth_payload,
    verify_auth,
)
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.frame_sets import (
    deduplicate_frame_slots,
    split_main_and_auth_frames,
)
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions import errors as extension_errors, validation
from ethernity.extensions.chain import (
    AuthenticatedExtensionChainLink,
    ExtensionReplayError,
    ReconstructedFile,
    ValidatedChainState,
)
from ethernity.extensions.resources import require_chain_resource_limits
from ethernity.extensions.validation import (
    RootSigningKeyBinding,
    resolve_root_signing_key_binding,
    validate_root_signing_key_binding,
)
from ethernity.formats.document_codec import (
    decode_document,
    detect_document_version,
    extract_payloads,
)
from ethernity.formats.document_constants import BACKUP_DOCUMENT_VERSIONS
from ethernity.formats.extension_document import (
    ExtensionDecodedChunkBudgetError,
    ExtensionDocument,
)
from ethernity.formats.manifest import BackupManifest, ManifestFile

RECONSTRUCTED_STATE_INPUT_ORIGIN = "directory"
RECONSTRUCTED_STATE_INPUT_ROOTS = ("reconstructed-state",)


@dataclass(frozen=True)
class ImportedRecoveryDocument:
    """One reassembled MAIN document discovered from content."""

    doc_id: bytes
    doc_hash: bytes
    ciphertext: bytes
    auth_frames: tuple[Frame, ...]
    source_label: str

    def __post_init__(self) -> None:
        if not isinstance(self.ciphertext, (bytes, bytearray)) or not self.ciphertext:
            raise ValueError("imported recovery document ciphertext must be non-empty bytes")
        ciphertext = bytes(self.ciphertext)
        if len(ciphertext) > MAX_CIPHERTEXT_BYTES:
            raise ValueError(
                "imported recovery document ciphertext exceeds MAX_CIPHERTEXT_BYTES "
                f"({MAX_CIPHERTEXT_BYTES})"
            )
        if not isinstance(self.doc_id, (bytes, bytearray)) or len(self.doc_id) != 8:
            raise ValueError("imported recovery document doc_id must be 8 bytes")
        if not isinstance(self.doc_hash, (bytes, bytearray)) or len(self.doc_hash) != 32:
            raise ValueError("imported recovery document doc_hash must be 32 bytes")
        doc_id = bytes(self.doc_id)
        doc_hash = bytes(self.doc_hash)
        derived_doc_id, derived_doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        if doc_hash != derived_doc_hash:
            raise ValueError("imported recovery document doc_hash does not match ciphertext")
        if doc_id != derived_doc_id:
            raise ValueError("imported recovery document doc_id does not match ciphertext")
        object.__setattr__(self, "doc_id", doc_id)
        object.__setattr__(self, "doc_hash", doc_hash)
        object.__setattr__(self, "ciphertext", ciphertext)
        object.__setattr__(self, "auth_frames", tuple(self.auth_frames))

    @classmethod
    def from_ciphertext(
        cls,
        ciphertext: bytes,
        *,
        auth_frames: tuple[Frame, ...] | list[Frame],
        source_label: str,
    ) -> ImportedRecoveryDocument:
        raw_ciphertext = bytes(ciphertext)
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(raw_ciphertext)
        return cls(
            doc_id=doc_id,
            doc_hash=doc_hash,
            ciphertext=raw_ciphertext,
            auth_frames=tuple(auth_frames),
            source_label=source_label,
        )


@dataclass(frozen=True)
class _DecodedImportEntry:
    doc_hash: bytes
    plaintext: bytes | None
    error: str | None
    passphrase_auth_failed: bool = False


@dataclass(frozen=True)
class DecodedImportSession:
    """One bounded decrypt pass shared by import classification and chain replay."""

    root_document: ImportedRecoveryDocument
    entries: tuple[_DecodedImportEntry, ...]
    locked_passphrase: str

    def plaintext_for(self, document: ImportedRecoveryDocument) -> bytes:
        """Return cached plaintext, or replay the cached decrypt failure without more KDF work."""

        for entry in self.entries:
            if entry.doc_hash != document.doc_hash:
                continue
            if entry.plaintext is not None:
                return entry.plaintext
            if entry.passphrase_auth_failed:
                raise PassphraseAuthenticationError(
                    AgeError(backend="pyrage", detail="Decryption failed")
                )
            raise ValueError(entry.error or "cached import decryption failed")
        raise ValueError("import document is not part of the decoded import session")


class _ImportSessionSelectionError(ValueError):
    """Root classification failed for one locked passphrase candidate."""

    def __init__(self, message: str, *, normalized_retry_allowed: bool) -> None:
        super().__init__(message)
        self.normalized_retry_allowed = normalized_retry_allowed


@dataclass(frozen=True)
class DecodedExtensionLink:
    link: AuthenticatedExtensionChainLink
    auth_payload: AuthPayload | None
    auth_status: str
    root_signing_key_verified: bool


@dataclass(frozen=True)
class ValidatedRecoveryHead:
    doc_id: bytes
    doc_hash: bytes
    ciphertext: bytes
    auth_payload: AuthPayload | None
    auth_status: str
    extension_index: int | None


@dataclass(frozen=True)
class ChainRecoveryResult:
    manifest: BackupManifest
    extracted: tuple[tuple[ManifestFile, bytes], ...]
    head: ValidatedRecoveryHead
    validated_chain: ValidatedChainState | None
    root_payload: bytes | None = None

    @property
    def selected_extension_index(self) -> int | None:
        return self.head.extension_index

    @property
    def selected_extension_doc_hash(self) -> str | None:
        if self.head.extension_index is None:
            return None
        return self.head.doc_hash.hex()


class ChainRecoveryInputs(Protocol):
    @property
    def ciphertext(self) -> bytes: ...

    @property
    def doc_id(self) -> bytes: ...

    @property
    def doc_hash(self) -> bytes: ...

    @property
    def passphrase(self) -> str: ...

    @property
    def auth_payload(self) -> AuthPayload | None: ...

    @property
    def auth_status(self) -> str: ...

    @property
    def allow_unsigned(self) -> bool: ...

    @property
    def extension_index(self) -> int | None: ...

    @property
    def extension_doc_hash(self) -> str | None: ...

    @property
    def expected_head_doc_hash(self) -> str | None: ...

    @property
    def import_documents(self) -> tuple[ImportedRecoveryDocument, ...]: ...

    @property
    def decoded_import_session(self) -> DecodedImportSession | None: ...


@dataclass(frozen=True)
class _DecodedExtensionCandidate:
    document: ImportedRecoveryDocument
    decoded: ExtensionDocument
    auth_payload: AuthPayload
    auth_status: str


def imported_documents_from_recovery_frames(
    frames: list[Frame],
    *,
    source_label: str = "content import",
) -> tuple[ImportedRecoveryDocument, ...]:
    """Group MAIN/AUTH recovery frames into independently recoverable documents."""

    deduped = deduplicate_frame_slots(frames)
    main_doc_ids = {
        frame.doc_id for frame in deduped if frame.frame_type == FrameType.MAIN_DOCUMENT
    }
    auth_doc_ids = {frame.doc_id for frame in deduped if frame.frame_type == FrameType.AUTH}
    orphan_auth_doc_ids = tuple(sorted(auth_doc_ids - main_doc_ids))
    if orphan_auth_doc_ids:
        raise extension_errors.OrphanAuthFramesError(orphan_auth_doc_ids, source_label=source_label)
    main_frames, auth_frames = split_main_and_auth_frames(deduped)
    require_chain_resource_limits(
        document_count=len({frame.doc_id for frame in main_frames}),
        total_ciphertext_bytes=sum(len(frame.data) for frame in main_frames),
        operation=source_label,
    )
    main_by_doc_id: dict[bytes, list[Frame]] = {}
    auth_by_doc_id: dict[bytes, list[Frame]] = {}
    for frame in main_frames:
        main_by_doc_id.setdefault(frame.doc_id, []).append(frame)
    for frame in auth_frames:
        auth_by_doc_id.setdefault(frame.doc_id, []).append(frame)

    documents: list[ImportedRecoveryDocument] = []
    for doc_id in sorted(main_by_doc_id):
        ciphertext = reassemble_payload(
            main_by_doc_id[doc_id],
            expected_frame_type=FrameType.MAIN_DOCUMENT,
        )
        derived_doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
        if derived_doc_id != doc_id:
            raise ValueError("MAIN frame doc_id does not match recovered ciphertext")
        documents.append(
            ImportedRecoveryDocument.from_ciphertext(
                ciphertext=ciphertext,
                auth_frames=tuple(auth_by_doc_id.get(doc_id, ())),
                source_label=f"{source_label}:{doc_id.hex()}",
            )
        )
    return tuple(documents)


def imported_document_from_recovery_frames(
    frames: list[Frame],
    *,
    source_label: str = "content import",
) -> ImportedRecoveryDocument:
    documents = imported_documents_from_recovery_frames(frames, source_label=source_label)
    if len(documents) != 1:
        raise ValueError("extension carrier input must contain exactly one MAIN document")
    return documents[0]


def select_root_import_document(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    passphrase: str,
    debug: bool,
) -> ImportedRecoveryDocument:
    """Pick exactly one supported standalone root backup from imported content."""

    return select_root_import_session(
        documents,
        passphrase=passphrase,
        debug=debug,
    ).root_document


def select_root_import_session(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    passphrase: str,
    debug: bool,
) -> DecodedImportSession:
    """Classify imports with one passphrase candidate locked across the whole session."""

    require_chain_resource_limits(
        document_count=len(documents),
        total_ciphertext_bytes=sum(len(document.ciphertext) for document in documents),
        operation="content import",
    )

    try:
        return _select_root_import_session_candidate(
            documents,
            passphrase=passphrase,
            debug=debug,
        )
    except _ImportSessionSelectionError as exact_error:
        normalized = normalize_valid_bip39_whitespace(passphrase)
        if normalized == passphrase or not exact_error.normalized_retry_allowed:
            raise ValueError(str(exact_error)) from exact_error
        try:
            return _select_root_import_session_candidate(
                documents,
                passphrase=normalized,
                debug=debug,
            )
        except _ImportSessionSelectionError as normalized_error:
            raise ValueError(str(normalized_error)) from normalized_error


def _select_root_import_session_candidate(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    passphrase: str,
    debug: bool,
) -> DecodedImportSession:
    """Classify all imports using exactly one already-selected passphrase candidate."""

    roots: list[ImportedRecoveryDocument] = []
    decoded_entries: list[_DecodedImportEntry] = []
    extension_count = 0
    decode_errors: list[str] = []
    passphrase_auth_failures = 0
    non_passphrase_failures = 0
    for document in documents:
        entry = _decode_import_entry(document, passphrase=passphrase, debug=debug)
        decoded_entries.append(entry)
        if entry.error is not None:
            passphrase_auth_failures += int(entry.passphrase_auth_failed)
            non_passphrase_failures += int(not entry.passphrase_auth_failed)
            decode_errors.append(f"{document.doc_id.hex()}: {entry.error}")
            continue
        assert entry.plaintext is not None
        plaintext = entry.plaintext
        try:
            version = detect_document_version(plaintext)
            decoded = decode_document(plaintext)[1] if version in BACKUP_DOCUMENT_VERSIONS else None
        except ExtensionDecodedChunkBudgetError:
            raise
        except Exception as exc:
            non_passphrase_failures += 1
            decode_errors.append(f"{document.doc_id.hex()}: {exc}")
            continue
        if version in BACKUP_DOCUMENT_VERSIONS and isinstance(decoded, tuple) and len(decoded) == 2:
            roots.append(document)
        elif version == 2:
            extension_count += 1
        else:
            decode_errors.append(
                f"{document.doc_id.hex()}: unsupported document version: {version}"
            )

    if len(roots) == 1:
        return DecodedImportSession(
            root_document=roots[0],
            entries=tuple(decoded_entries),
            locked_passphrase=passphrase,
        )
    if not roots:
        detail = "; ".join(decode_errors[:3])
        suffix = f" ({detail})" if detail else ""
        raise _ImportSessionSelectionError(
            f"content import did not contain a decryptable root backup{suffix}",
            normalized_retry_allowed=(
                passphrase_auth_failures > 0 and non_passphrase_failures == 0
            ),
        )
    raise _ImportSessionSelectionError(
        "content import contains multiple root backups; provide one root backup per "
        f"recovery session ({len(roots)} roots, {extension_count} extensions)",
        normalized_retry_allowed=False,
    )


def _decode_import_entry(
    document: ImportedRecoveryDocument, *, passphrase: str, debug: bool
) -> _DecodedImportEntry:
    try:
        plaintext = _decrypt_import_session_candidate(
            document.ciphertext, passphrase=passphrase, debug=debug
        )
    except RecoveryResourceLimitError:
        raise
    except PassphraseAuthenticationError as exc:
        return _DecodedImportEntry(
            doc_hash=document.doc_hash, plaintext=None, error=str(exc), passphrase_auth_failed=True
        )
    except Exception as exc:
        return _DecodedImportEntry(doc_hash=document.doc_hash, plaintext=None, error=str(exc))
    return _DecodedImportEntry(doc_hash=document.doc_hash, plaintext=plaintext, error=None)


def _decrypt_import_session_candidate(
    ciphertext: bytes,
    *,
    passphrase: str,
    debug: bool,
) -> bytes:
    """Decrypt one session member without allowing an implicit second candidate."""

    if normalize_valid_bip39_whitespace(passphrase) == passphrase:
        return decrypt_bytes(ciphertext, passphrase=passphrase, debug=debug)
    try:
        return decrypt_bytes_with_exact_passphrase(ciphertext, passphrase=passphrase)
    except AgeError:
        if debug:
            raise
        raise ValueError("decryption failed") from None


def recover_chain_entries(
    plan: ChainRecoveryInputs,
    *,
    debug: bool = False,
) -> ChainRecoveryResult:
    if plan.import_documents:
        return recover_imported_chain_entries(plan, debug=debug)

    root_manifest, payload = decode_root_manifest(
        ciphertext=plan.ciphertext,
        passphrase=plan.passphrase,
        debug=debug,
    )
    validate_root_signing_key_binding(root_manifest, plan.auth_payload, doc_hash=plan.doc_hash)
    _ensure_expected_head_satisfied(
        plan,
        selected_extension_index=None,
        selected_extension_doc_hash=None,
    )
    return _root_chain_recovery_result(plan, root_manifest, payload)


def recover_imported_chain_entries(
    plan: ChainRecoveryInputs, *, debug: bool = False
) -> ChainRecoveryResult:
    decoded_import_session = getattr(plan, "decoded_import_session", None)
    normalized = normalize_valid_bip39_whitespace(plan.passphrase)
    if (
        decoded_import_session is None
        and len(plan.import_documents) > 1
        and normalized != plan.passphrase
    ):
        decoded_import_session = select_root_import_session(
            tuple(plan.import_documents),
            passphrase=plan.passphrase,
            debug=debug,
        )

    try:
        return _recover_imported_chain_entries_with_session(
            plan,
            debug=debug,
            decoded_import_session=decoded_import_session,
        )
    except PassphraseAuthenticationError as exact_error:
        if (
            decoded_import_session is None
            or decoded_import_session.locked_passphrase != plan.passphrase
            or normalized == plan.passphrase
        ):
            raise ValueError("content import decryption failed") from exact_error
        try:
            normalized_session = _select_root_import_session_candidate(
                tuple(plan.import_documents),
                passphrase=normalized,
                debug=debug,
            )
            return _recover_imported_chain_entries_with_session(
                plan,
                debug=debug,
                decoded_import_session=normalized_session,
            )
        except (PassphraseAuthenticationError, _ImportSessionSelectionError) as normalized_error:
            raise ValueError(
                "content import cannot be decrypted with one consistent passphrase candidate"
            ) from normalized_error


def _recover_imported_chain_entries_with_session(
    plan: ChainRecoveryInputs,
    *,
    debug: bool,
    decoded_import_session: DecodedImportSession | None,
) -> ChainRecoveryResult:
    require_chain_resource_limits(
        document_count=len(plan.import_documents),
        total_ciphertext_bytes=sum(len(document.ciphertext) for document in plan.import_documents),
        operation="content import",
    )
    if plan.extension_index is not None and plan.extension_doc_hash is not None:
        raise ValueError("use either --extension-index or --extension-doc-hash, not both")

    if decoded_import_session is None:
        root_manifest, payload = decode_root_manifest(
            ciphertext=plan.ciphertext,
            passphrase=plan.passphrase,
            debug=debug,
        )
    else:
        root_manifest, payload = decode_imported_root_manifest(
            _selected_root_import_document(plan),
            decoded_import_session=decoded_import_session,
        )
    if len(plan.import_documents) <= 1:
        _ensure_root_selector_satisfied(
            root_doc_hash=plan.doc_hash,
            requested_index=plan.extension_index,
            requested_doc_hash=plan.extension_doc_hash,
        )
        validate_root_signing_key_binding(root_manifest, plan.auth_payload, doc_hash=plan.doc_hash)
        _ensure_expected_head_satisfied(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        return _root_chain_recovery_result(plan, root_manifest, payload)

    if plan.extension_index == 0:
        validate_root_signing_key_binding(root_manifest, plan.auth_payload, doc_hash=plan.doc_hash)
        _ensure_expected_head_satisfied(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        return _root_chain_recovery_result(plan, root_manifest, payload)

    if plan.allow_unsigned:
        raise extension_errors.ExtensionRecoveryError(
            code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
            message=(
                "unsigned recovery is not supported for extension replay; "
                "extension chain recovery requires authenticated extension AUTH"
            ),
            details={
                "stage": "auth",
                "unsigned_recovery": True,
                "validated_head_index": 0,
                "validated_head_doc_hash": plan.doc_hash.hex(),
            },
        )

    root_validation = validation.inspect_root_validation(
        root_manifest,
        plan.auth_payload,
        doc_hash=plan.doc_hash,
        auth_status=plan.auth_status,
        require_signing_key=True,
    )
    root_sign_pub = root_validation.require_valid()
    assert root_sign_pub is not None

    decoded_links = _decode_imported_extension_links(
        tuple(plan.import_documents),
        root_doc_hash=plan.doc_hash,
        root_doc_id=plan.doc_id,
        passphrase=plan.passphrase,
        expected_sign_pub=root_sign_pub,
        requested_index=plan.extension_index,
        requested_doc_hash=plan.extension_doc_hash,
        decoded_import_session=decoded_import_session,
        debug=debug,
    )
    selected_links = _select_imported_chain_links(
        decoded_links,
        root_doc_hash=plan.doc_hash,
        requested_index=plan.extension_index,
        requested_doc_hash=plan.extension_doc_hash,
    )
    if not selected_links:
        _ensure_expected_head_satisfied(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        return _root_chain_recovery_result(plan, root_manifest, payload)

    try:
        validated_chain = validation.inspect_chain_validation(
            root_manifest,
            payload,
            root_doc_hash=plan.doc_hash,
            root_auth_payload=plan.auth_payload,
            root_auth_status=plan.auth_status,
            extensions=tuple(item.link for item in selected_links),
        ).require_state()
    except ExtensionReplayError as exc:
        raise _chain_replay_head_untrusted_error(
            exc,
            plan=plan,
            decoded_links=decoded_links,
            selected_links=selected_links,
        ) from exc
    latest_manifest = _synthetic_manifest_from_state(
        root_manifest,
        validated_chain.files,
    )
    state_by_path = {item.path: item.data for item in validated_chain.files}
    extracted = tuple((entry, state_by_path[entry.path]) for entry in latest_manifest.files)
    selected_head = selected_links[-1]
    selected_document = next(
        document
        for document in plan.import_documents
        if document.doc_hash == selected_head.link.doc_hash
    )
    selected_extension_index = selected_head.link.document.header.index
    selected_extension_doc_hash = selected_document.doc_hash.hex()
    _ensure_expected_head_satisfied(
        plan,
        selected_extension_index=selected_extension_index,
        selected_extension_doc_hash=selected_extension_doc_hash,
    )
    return ChainRecoveryResult(
        manifest=latest_manifest,
        extracted=extracted,
        head=ValidatedRecoveryHead(
            doc_id=selected_document.doc_id,
            doc_hash=selected_document.doc_hash,
            ciphertext=selected_document.ciphertext,
            auth_payload=selected_head.auth_payload,
            auth_status=selected_head.auth_status,
            extension_index=selected_extension_index,
        ),
        validated_chain=validated_chain,
    )


def _root_chain_recovery_result(
    plan: ChainRecoveryInputs,
    manifest: BackupManifest,
    payload: bytes,
) -> ChainRecoveryResult:
    return ChainRecoveryResult(
        manifest=manifest,
        extracted=tuple(extract_payloads(manifest, payload)),
        head=ValidatedRecoveryHead(
            doc_id=plan.doc_id,
            doc_hash=plan.doc_hash,
            ciphertext=plan.ciphertext,
            auth_payload=plan.auth_payload,
            auth_status=plan.auth_status,
            extension_index=None,
        ),
        validated_chain=None,
        root_payload=payload,
    )


def _ensure_expected_head_satisfied(
    plan: ChainRecoveryInputs,
    *,
    selected_extension_index: int | None,
    selected_extension_doc_hash: str | None,
) -> None:
    expected_head_doc_hash = getattr(plan, "expected_head_doc_hash", None)
    if expected_head_doc_hash is None:
        return
    expected = parse_doc_hash_hex(
        expected_head_doc_hash,
        option="--extension-doc-hash",
    ).hex()
    validated_head_index = selected_extension_index if selected_extension_index is not None else 0
    validated_head_doc_hash = selected_extension_doc_hash or plan.doc_hash.hex()
    if hmac.compare_digest(expected, validated_head_doc_hash):
        return
    raise extension_errors.ExtensionRecoveryError(
        code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
        message=(
            "recovery head doc_hash does not match expected head "
            f"{expected}; validated supplied head is {validated_head_doc_hash}"
        ),
        details={
            "stage": "selection",
            "expected_head_doc_hash": expected,
            "validated_head_index": validated_head_index,
            "validated_head_doc_hash": validated_head_doc_hash,
            "freshness_scope": "supplied_carriers_only",
        },
    )


def validate_expected_recovery_head(
    plan: ChainRecoveryInputs,
    *,
    selected_extension_index: int | None,
    selected_extension_doc_hash: str | None,
) -> None:
    _ensure_expected_head_satisfied(
        plan,
        selected_extension_index=selected_extension_index,
        selected_extension_doc_hash=selected_extension_doc_hash,
    )


def _chain_replay_head_untrusted_error(
    exc: ExtensionReplayError,
    *,
    plan: ChainRecoveryInputs,
    decoded_links: tuple[DecodedExtensionLink, ...],
    selected_links: tuple[DecodedExtensionLink, ...],
) -> extension_errors.ExtensionRecoveryError:
    validated_link = next(
        (
            item
            for item in selected_links
            if item.link.document.header.index == exc.last_validated_head_index
            and item.link.doc_hash == exc.last_validated_head_hash
        ),
        None,
    )
    head_index = exc.last_validated_head_index
    head_hash = exc.last_validated_head_hash.hex()
    head_auth = None if validated_link is None else validated_link.auth_status
    head_verified = None if validated_link is None else validated_link.root_signing_key_verified
    latest_head_index, latest_head_doc_hash = _latest_head_details(decoded_links)
    requested_doc_hash = (
        None if plan.extension_doc_hash is None else plan.extension_doc_hash.strip().lower()
    )
    explicit_selection = plan.extension_index is not None or requested_doc_hash is not None
    head_label = "requested" if explicit_selection else "latest supplied"
    failure_message = str(exc)
    return extension_errors.ExtensionRecoveryError(
        code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
        message=f"{head_label} recovery head could not be trusted: {failure_message}",
        details={
            "stage": "replay",
            "failure_stage": exc.failure_phase,
            "failure_message": failure_message,
            "failure_head_index": exc.failing_index,
            "failure_head_doc_hash": exc.failing_hash.hex(),
            "latest_head_index": latest_head_index,
            "latest_head_doc_hash": latest_head_doc_hash,
            "requested_head_index": plan.extension_index,
            "requested_head_doc_hash": requested_doc_hash,
            "validated_head_index": head_index,
            "validated_head_doc_hash": head_hash,
            "validated_head_auth_status": head_auth,
            "validated_head_root_signing_key_verified": head_verified,
            "explicit_selection": explicit_selection,
        },
    )


def _latest_head_details(
    links: tuple[DecodedExtensionLink, ...],
) -> tuple[int | None, str | None]:
    if not links:
        return None, None
    latest = links[-1]
    return latest.link.document.header.index, latest.link.doc_hash.hex()


def _latest_candidate_head_details(
    candidates: tuple[_DecodedExtensionCandidate, ...],
) -> tuple[int | None, str | None]:
    if not candidates:
        return None, None
    latest = max(candidates, key=lambda candidate: candidate.decoded.header.index)
    return latest.decoded.header.index, latest.document.doc_hash.hex()


def _missing_requested_extension_error(
    message: str,
    *,
    root_doc_hash: bytes,
    latest_head_index: int | None,
    latest_head_doc_hash: str | None,
    requested_index: int | None,
    requested_doc_hash: str | None,
) -> extension_errors.ExtensionRecoveryError:
    return extension_errors.ExtensionRecoveryError(
        code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
        message=message,
        details={
            "stage": "selection",
            "failure_stage": "selection",
            "failure_message": message,
            "latest_head_index": latest_head_index,
            "latest_head_doc_hash": latest_head_doc_hash,
            "requested_head_index": requested_index,
            "requested_head_doc_hash": requested_doc_hash,
            "validated_head_index": 0,
            "validated_head_doc_hash": root_doc_hash.hex(),
            "explicit_selection": True,
        },
    )


def _decode_imported_extension_links(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    root_doc_hash: bytes,
    root_doc_id: bytes,
    passphrase: str,
    expected_sign_pub: bytes,
    requested_index: int | None = None,
    requested_doc_hash: str | None = None,
    decoded_import_session: DecodedImportSession | None = None,
    debug: bool,
) -> tuple[DecodedExtensionLink, ...]:
    if requested_index is not None and requested_doc_hash is not None:
        raise ValueError("use either --extension-index or --extension-doc-hash, not both")

    candidates = _decode_imported_extension_candidates(
        documents,
        root_doc_hash=root_doc_hash,
        root_doc_id=root_doc_id,
        passphrase=passphrase,
        expected_sign_pub=expected_sign_pub,
        fail_on_root_signing_key_errors=requested_index is None and requested_doc_hash is None,
        requested_doc_hash=_requested_extension_doc_hash_bytes(requested_doc_hash),
        decoded_import_session=decoded_import_session,
        debug=debug,
    )
    candidates = _select_extension_candidates_for_auth(
        candidates,
        root_doc_hash=root_doc_hash,
        requested_index=requested_index,
        requested_doc_hash=requested_doc_hash,
    )
    return _authenticate_imported_extension_candidates(
        candidates,
        expected_sign_pub=expected_sign_pub,
    )


def _decode_imported_extension_candidates(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    root_doc_hash: bytes,
    root_doc_id: bytes,
    passphrase: str,
    expected_sign_pub: bytes,
    fail_on_root_signing_key_errors: bool,
    requested_doc_hash: bytes | None,
    decoded_import_session: DecodedImportSession | None,
    debug: bool,
) -> tuple[_DecodedExtensionCandidate, ...]:
    candidates: list[_DecodedExtensionCandidate] = []
    seen_doc_hashes = {root_doc_hash}
    remaining_inline_chunk_bytes = MAX_RECOVERY_DECODED_CHUNK_BYTES
    for document in documents:
        if document.doc_hash in seen_doc_hashes:
            continue
        _require_distinct_root_id(document, root_doc_id)
        try:
            auth_payload, auth_status = _resolve_verified_extension_auth(
                document,
                expected_sign_pub=expected_sign_pub,
            )
        except ValueError as exc:
            if document.doc_hash == requested_doc_hash:
                raise _extension_auth_error(
                    document,
                    message=str(exc),
                    explicit_selection=True,
                ) from exc
            if fail_on_root_signing_key_errors:
                raise _extension_auth_error(document, message=str(exc)) from exc
            continue
        try:
            plaintext = _import_document_plaintext(
                document,
                passphrase=passphrase,
                debug=debug,
                decoded_import_session=decoded_import_session,
            )
            version, decoded_document = decode_document(
                plaintext,
                max_extension_inline_chunk_bytes=remaining_inline_chunk_bytes,
            )
        except (
            PassphraseAuthenticationError,
            ExtensionDecodedChunkBudgetError,
            RecoveryResourceLimitError,
        ):
            raise
        except Exception as exc:
            message = f"imported document signed by the root key could not be decoded: {exc}"
            _handle_extension_candidate_failure(
                document,
                expected_sign_pub=expected_sign_pub,
                requested_doc_hash=requested_doc_hash,
                fail_on_root_signing_key_errors=fail_on_root_signing_key_errors,
                stage="decode",
                message=message,
            )
            continue
        if version != 2 or not isinstance(decoded_document, ExtensionDocument):
            message = (
                "imported document signed by the root key did not decode as an extension document"
            )
            _handle_extension_candidate_failure(
                document,
                expected_sign_pub=expected_sign_pub,
                requested_doc_hash=requested_doc_hash,
                fail_on_root_signing_key_errors=fail_on_root_signing_key_errors,
                stage="decode",
                message=message,
            )
            continue
        remaining_inline_chunk_bytes -= decoded_document.inline_chunk_raw_bytes
        if decoded_document.header.root_doc_hash != root_doc_hash:
            message = (
                "imported extension signed by the root key does not target "
                "the selected root document"
            )
            _handle_extension_candidate_failure(
                document,
                expected_sign_pub=expected_sign_pub,
                requested_doc_hash=requested_doc_hash,
                fail_on_root_signing_key_errors=fail_on_root_signing_key_errors,
                stage="chain",
                message=message,
            )
            continue
        seen_doc_hashes.add(document.doc_hash)
        candidates.append(
            _DecodedExtensionCandidate(
                document=document,
                decoded=decoded_document,
                auth_payload=auth_payload,
                auth_status=auth_status,
            )
        )
    return tuple(candidates)


def _require_distinct_root_id(document: ImportedRecoveryDocument, root_doc_id: bytes) -> None:
    if document.doc_id == root_doc_id:
        raise extension_errors.ExtensionRecoveryError(
            code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
            message=(
                "imported extension chain could not be trusted: "
                "content import contains a document whose doc_id collides with "
                "the selected root backup"
            ),
            details={
                "stage": "selection",
                "root_doc_id": root_doc_id.hex(),
                "colliding_doc_hash": document.doc_hash.hex(),
            },
        )


def _requested_extension_doc_hash_bytes(requested_doc_hash: str | None) -> bytes | None:
    if requested_doc_hash is None:
        return None
    return parse_doc_hash_hex(requested_doc_hash, option="--extension-doc-hash")


def _select_extension_candidates_for_auth(
    candidates: tuple[_DecodedExtensionCandidate, ...],
    *,
    root_doc_hash: bytes,
    requested_index: int | None,
    requested_doc_hash: str | None,
) -> tuple[_DecodedExtensionCandidate, ...]:
    if requested_index is not None:
        if requested_index < 0:
            raise ValueError("--extension-index must be >= 0")
        if requested_index == 0:
            return ()
        if not any(candidate.decoded.header.index == requested_index for candidate in candidates):
            latest_head_index, latest_head_doc_hash = _latest_candidate_head_details(candidates)
            raise _missing_requested_extension_error(
                f"extension index {requested_index} was not found",
                root_doc_hash=root_doc_hash,
                latest_head_index=latest_head_index,
                latest_head_doc_hash=latest_head_doc_hash,
                requested_index=requested_index,
                requested_doc_hash=None,
            )
        return tuple(
            candidate
            for candidate in candidates
            if candidate.decoded.header.index <= requested_index
        )
    if requested_doc_hash is not None:
        requested = parse_doc_hash_hex(requested_doc_hash, option="--extension-doc-hash")
        target_index = next(
            (
                candidate.decoded.header.index
                for candidate in candidates
                if candidate.document.doc_hash == requested
            ),
            None,
        )
        if target_index is None:
            latest_head_index, latest_head_doc_hash = _latest_candidate_head_details(candidates)
            requested_doc_hash_value = requested_doc_hash.strip().lower()
            raise _missing_requested_extension_error(
                f"extension doc_hash {requested_doc_hash_value} was not found",
                root_doc_hash=root_doc_hash,
                latest_head_index=latest_head_index,
                latest_head_doc_hash=latest_head_doc_hash,
                requested_index=None,
                requested_doc_hash=requested_doc_hash_value,
            )
        return tuple(
            candidate for candidate in candidates if candidate.decoded.header.index <= target_index
        )
    return candidates


def resolve_required_auth_payload(
    auth_frames: tuple[Frame, ...] | list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
) -> tuple[AuthPayload, str]:
    """Resolve and verify a required AUTH payload for extension replay."""

    if not auth_frames:
        raise ValueError("missing auth payload; provide AUTH input to verify recovery")
    if len(auth_frames) > 1:
        raise ValueError("multiple auth payloads provided")
    frame = auth_frames[0]
    if frame.doc_id != doc_id:
        raise ValueError("auth payload doc_id does not match ciphertext")
    if frame.total != 1 or frame.index != 0:
        raise ValueError("auth payload must be a single-frame payload")
    payload = decode_auth_payload(frame.data)
    if not hmac.compare_digest(payload.doc_hash, doc_hash):
        raise ValueError("auth doc_hash does not match ciphertext")
    if not verify_auth(doc_hash, sign_pub=payload.sign_pub, signature=payload.signature):
        raise ValueError("invalid auth signature")
    return payload, "verified"


def _authenticate_imported_extension_candidates(
    candidates: tuple[_DecodedExtensionCandidate, ...],
    *,
    expected_sign_pub: bytes,
) -> tuple[DecodedExtensionLink, ...]:
    links: list[DecodedExtensionLink] = []
    for candidate in candidates:
        document = candidate.document

        links.append(
            DecodedExtensionLink(
                link=AuthenticatedExtensionChainLink(
                    doc_hash=document.doc_hash,
                    document=candidate.decoded,
                    auth_payload=candidate.auth_payload,
                    expected_sign_pub=expected_sign_pub,
                    auth_status=candidate.auth_status,
                    root_signing_key_verified=True,
                ),
                auth_payload=candidate.auth_payload,
                auth_status=candidate.auth_status,
                root_signing_key_verified=True,
            )
        )

    by_index: dict[int, DecodedExtensionLink] = {}
    for link in links:
        index = link.link.document.header.index
        existing = by_index.get(index)
        if existing is not None and existing.link.doc_hash != link.link.doc_hash:
            raise extension_errors.ExtensionRecoveryError(
                code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
                message=(
                    f"content import contains multiple authenticated extensions for index {index}"
                ),
                details={"stage": "selection", "extension_index": index},
            )
        by_index[index] = link
    return tuple(by_index[index] for index in sorted(by_index))


def _resolve_verified_extension_auth(
    document: ImportedRecoveryDocument,
    *,
    expected_sign_pub: bytes,
) -> tuple[AuthPayload, str]:
    try:
        auth_payload, auth_status = resolve_required_auth_payload(
            document.auth_frames,
            doc_id=document.doc_id,
            doc_hash=document.doc_hash,
        )
    except ValueError as exc:
        raise ValueError(f"imported extension AUTH could not be verified: {exc}") from exc
    if auth_payload.sign_pub != expected_sign_pub:
        raise ValueError("imported extension AUTH signing key does not match root signing key")
    return auth_payload, auth_status


def _extension_auth_error(
    document: ImportedRecoveryDocument,
    *,
    message: str,
    explicit_selection: bool = False,
) -> extension_errors.ExtensionRecoveryError:
    details: dict[str, object] = {
        "stage": "auth",
        "extension_doc_hash": document.doc_hash.hex(),
    }
    if explicit_selection:
        details["explicit_selection"] = True
    return extension_errors.ExtensionRecoveryError(
        code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
        message=message,
        details=details,
    )


def _raise_if_document_signed_by_root_key(
    document: ImportedRecoveryDocument,
    *,
    expected_sign_pub: bytes,
    stage: str,
    message: str,
) -> None:
    try:
        auth_payload, _auth_status = resolve_required_auth_payload(
            document.auth_frames,
            doc_id=document.doc_id,
            doc_hash=document.doc_hash,
        )
    except ValueError:
        return
    if auth_payload.sign_pub == expected_sign_pub:
        raise extension_errors.ExtensionRecoveryError(
            code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
            message=message,
            details={
                "stage": stage,
                "extension_doc_hash": document.doc_hash.hex(),
            },
        )


def _raise_selected_extension_candidate_error(
    document: ImportedRecoveryDocument,
    *,
    expected_sign_pub: bytes,
    stage: str,
    message: str,
) -> None:
    details: dict[str, object] = {
        "stage": stage,
        "extension_doc_hash": document.doc_hash.hex(),
        "explicit_selection": True,
    }
    try:
        auth_payload, _auth_status = resolve_required_auth_payload(
            document.auth_frames,
            doc_id=document.doc_id,
            doc_hash=document.doc_hash,
        )
    except ValueError as exc:
        details["auth_error"] = str(exc)
    else:
        details["root_signing_key_verified"] = auth_payload.sign_pub == expected_sign_pub
    raise extension_errors.ExtensionRecoveryError(
        code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
        message=message,
        details=details,
    )


def decode_imported_extension_link(
    document: ImportedRecoveryDocument,
    *,
    passphrase: str,
    expected_sign_pub: bytes,
    debug: bool,
    max_inline_chunk_bytes: int = MAX_RECOVERY_DECODED_CHUNK_BYTES,
    decoded_import_session: DecodedImportSession | None = None,
) -> DecodedExtensionLink:
    auth_payload, auth_status = _resolve_verified_extension_auth(
        document,
        expected_sign_pub=expected_sign_pub,
    )
    plaintext = _import_document_plaintext(
        document,
        passphrase=passphrase,
        debug=debug,
        decoded_import_session=decoded_import_session,
    )
    version, decoded = decode_document(
        plaintext,
        max_extension_inline_chunk_bytes=max_inline_chunk_bytes,
    )
    if version != 2 or not isinstance(decoded, ExtensionDocument):
        raise ValueError("imported document did not decode as an extension document")

    return DecodedExtensionLink(
        link=AuthenticatedExtensionChainLink(
            doc_hash=document.doc_hash,
            document=decoded,
            auth_payload=auth_payload,
            expected_sign_pub=expected_sign_pub,
            auth_status=auth_status,
            root_signing_key_verified=True,
        ),
        auth_payload=auth_payload,
        auth_status=auth_status,
        root_signing_key_verified=True,
    )


def _select_imported_chain_links(
    links: tuple[DecodedExtensionLink, ...],
    *,
    root_doc_hash: bytes,
    requested_index: int | None,
    requested_doc_hash: str | None,
) -> tuple[DecodedExtensionLink, ...]:
    if requested_index is not None and requested_doc_hash is not None:
        raise ValueError("use either --extension-index or --extension-doc-hash, not both")
    if requested_index is not None:
        if requested_index < 0:
            raise ValueError("--extension-index must be >= 0")
        if requested_index == 0:
            return ()
        if not any(link.link.document.header.index == requested_index for link in links):
            latest_head_index, latest_head_doc_hash = _latest_head_details(links)
            raise _missing_requested_extension_error(
                f"extension index {requested_index} was not found",
                root_doc_hash=root_doc_hash,
                latest_head_index=latest_head_index,
                latest_head_doc_hash=latest_head_doc_hash,
                requested_index=requested_index,
                requested_doc_hash=None,
            )
        return tuple(link for link in links if link.link.document.header.index <= requested_index)
    if requested_doc_hash is not None:
        requested = parse_doc_hash_hex(requested_doc_hash, option="--extension-doc-hash")
        selected: list[DecodedExtensionLink] = []
        matched = False
        for link in links:
            selected.append(link)
            if link.link.doc_hash == requested:
                matched = True
                break
        if not matched:
            latest_head_index, latest_head_doc_hash = _latest_head_details(links)
            requested_doc_hash_value = requested_doc_hash.strip().lower()
            raise _missing_requested_extension_error(
                f"extension doc_hash {requested_doc_hash_value} was not found",
                root_doc_hash=root_doc_hash,
                latest_head_index=latest_head_index,
                latest_head_doc_hash=latest_head_doc_hash,
                requested_index=None,
                requested_doc_hash=requested_doc_hash_value,
            )
        return tuple(selected)
    return links


def _ensure_root_selector_satisfied(
    *,
    root_doc_hash: bytes,
    requested_index: int | None,
    requested_doc_hash: str | None,
) -> None:
    if requested_index is not None:
        if requested_index < 0:
            raise ValueError("--extension-index must be >= 0")
        if requested_index > 0:
            raise _missing_requested_extension_error(
                f"extension index {requested_index} was not found",
                root_doc_hash=root_doc_hash,
                latest_head_index=None,
                latest_head_doc_hash=None,
                requested_index=requested_index,
                requested_doc_hash=None,
            )
    if requested_doc_hash is not None:
        parse_doc_hash_hex(requested_doc_hash, option="--extension-doc-hash")
        requested_doc_hash_value = requested_doc_hash.strip().lower()
        raise _missing_requested_extension_error(
            f"extension doc_hash {requested_doc_hash_value} was not found",
            root_doc_hash=root_doc_hash,
            latest_head_index=None,
            latest_head_doc_hash=None,
            requested_index=None,
            requested_doc_hash=requested_doc_hash_value,
        )


def decode_root_manifest(
    *,
    ciphertext: bytes,
    passphrase: str,
    debug: bool,
) -> tuple[BackupManifest, bytes]:
    plaintext = decrypt_bytes(ciphertext, passphrase=passphrase, debug=debug)
    return _decode_root_plaintext(plaintext)


def decode_imported_root_manifest(
    document: ImportedRecoveryDocument,
    *,
    decoded_import_session: DecodedImportSession,
) -> tuple[BackupManifest, bytes]:
    """Decode a root using plaintext authenticated by an earlier import decrypt pass."""

    if document.doc_hash != decoded_import_session.root_document.doc_hash:
        raise ValueError("decoded import session root does not match selected root document")
    return _decode_root_plaintext(decoded_import_session.plaintext_for(document))


def _decode_root_plaintext(plaintext: bytes) -> tuple[BackupManifest, bytes]:
    version, decoded = decode_document(plaintext)
    if (
        version not in BACKUP_DOCUMENT_VERSIONS
        or not isinstance(decoded, tuple)
        or len(decoded) != 2
    ):
        raise ValueError("root backup must decode as a standalone backup document")
    manifest, payload = decoded
    if not isinstance(manifest, BackupManifest) or not isinstance(payload, bytes):
        raise ValueError("root backup did not decode correctly")
    return manifest, payload


def _selected_root_import_document(plan: ChainRecoveryInputs) -> ImportedRecoveryDocument:
    for document in plan.import_documents:
        if document.doc_hash == plan.doc_hash and document.ciphertext == plan.ciphertext:
            return document
    raise ValueError("decoded import session does not contain the selected root document")


def _import_document_plaintext(
    document: ImportedRecoveryDocument,
    *,
    passphrase: str,
    debug: bool,
    decoded_import_session: DecodedImportSession | None,
) -> bytes:
    if decoded_import_session is not None:
        return decoded_import_session.plaintext_for(document)
    return decrypt_bytes(document.ciphertext, passphrase=passphrase, debug=debug)


def _synthetic_manifest_from_state(
    root_manifest: BackupManifest,
    state: tuple[ReconstructedFile, ...],
) -> BackupManifest:
    return BackupManifest(
        created_at=root_manifest.created_at,
        signing_seed=root_manifest.signing_seed,
        files=tuple(
            ManifestFile(
                path=item.path,
                size=item.size,
                sha256=item.sha256,
                mtime=item.mtime,
            )
            for item in state
        ),
        input_origin=RECONSTRUCTED_STATE_INPUT_ORIGIN,
        input_roots=RECONSTRUCTED_STATE_INPUT_ROOTS,
        payload_codec="raw",
    )


__all__ = [
    "ChainRecoveryResult",
    "DecodedImportSession",
    "DecodedExtensionLink",
    "ImportedRecoveryDocument",
    "RootSigningKeyBinding",
    "ValidatedRecoveryHead",
    "decode_imported_extension_link",
    "decode_imported_root_manifest",
    "decode_root_manifest",
    "imported_document_from_recovery_frames",
    "imported_documents_from_recovery_frames",
    "recover_chain_entries",
    "recover_imported_chain_entries",
    "resolve_required_auth_payload",
    "resolve_root_signing_key_binding",
    "select_root_import_document",
    "select_root_import_session",
    "validate_expected_recovery_head",
    "validate_root_signing_key_binding",
]


def _handle_extension_candidate_failure(
    document: ImportedRecoveryDocument,
    *,
    expected_sign_pub: bytes,
    requested_doc_hash: bytes | None,
    fail_on_root_signing_key_errors: bool,
    stage: str,
    message: str,
) -> None:
    if document.doc_hash == requested_doc_hash:
        _raise_selected_extension_candidate_error(
            document, expected_sign_pub=expected_sign_pub, stage=stage, message=message
        )
    if fail_on_root_signing_key_errors:
        _raise_if_document_signed_by_root_key(
            document, expected_sign_pub=expected_sign_pub, stage=stage, message=message
        )
