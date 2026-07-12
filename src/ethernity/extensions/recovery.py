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

"""Content-first extension recovery helpers.

Recovery does not rely on extension directory names or artifact filenames. Scanned content is
grouped by frame/doc identity, then authenticated and ordered using ciphertext hashes and decrypted
headers.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Protocol

from ethernity.core.bounds import (
    MAX_CIPHERTEXT_BYTES,
    MAX_EXTENSION_INDEX,
    MAX_RECOVERY_DECODED_CHUNK_BYTES,
)
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.signing import (
    AuthPayload,
    decode_auth_payload,
    derive_public_key,
    verify_auth,
)
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions import errors as extension_errors
from ethernity.extensions.chain import (
    AuthenticatedExtensionChainLink,
    LogicalFileState,
    reconstruct_authenticated_latest_logical_state,
)
from ethernity.extensions.identity import doc_id_and_hash_from_ciphertext
from ethernity.extensions.resources import require_chain_resource_limits
from ethernity.formats.envelope_codec import (
    decode_any_envelope,
    detect_envelope_version,
    extract_payloads,
)
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile
from ethernity.formats.extension_envelope import (
    ExtensionChunkingProfile,
    ExtensionDecodedChunkBudgetError,
    ExtensionEnvelope,
)

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
    extension_index: int | None = None
    extension_dir_name: str | None = None

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
        if self.extension_index is not None and (
            isinstance(self.extension_index, bool)
            or not isinstance(self.extension_index, int)
            or self.extension_index <= 0
        ):
            raise ValueError("published extension index must be a positive integer")
        if self.extension_index is not None and self.extension_index > MAX_EXTENSION_INDEX:
            raise ValueError(
                f"published extension index must be <= MAX_EXTENSION_INDEX ({MAX_EXTENSION_INDEX})"
            )
        if self.extension_dir_name is not None and (
            not isinstance(self.extension_dir_name, str) or not self.extension_dir_name
        ):
            raise ValueError("published extension directory name must be non-empty")
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
        extension_index: int | None = None,
        extension_dir_name: str | None = None,
    ) -> "ImportedRecoveryDocument":
        raw_ciphertext = bytes(ciphertext)
        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(raw_ciphertext)
        return cls(
            doc_id=doc_id,
            doc_hash=doc_hash,
            ciphertext=raw_ciphertext,
            auth_frames=tuple(auth_frames),
            source_label=source_label,
            extension_index=extension_index,
            extension_dir_name=extension_dir_name,
        )

    @property
    def doc_id_hex(self) -> str:
        return self.doc_id.hex()

    @property
    def index(self) -> int:
        if self.extension_index is None:
            raise ValueError("recovery document is not a published extension")
        return self.extension_index

    @property
    def dir_name(self) -> str:
        return self.extension_dir_name or self.source_label


@dataclass(frozen=True)
class _DecodedImportEntry:
    doc_hash: bytes
    plaintext: bytes | None
    error: str | None


@dataclass(frozen=True)
class DecodedImportSession:
    """One bounded decrypt pass shared by import classification and chain replay."""

    root_document: ImportedRecoveryDocument
    entries: tuple[_DecodedImportEntry, ...]

    def plaintext_for(self, document: ImportedRecoveryDocument) -> bytes:
        """Return cached plaintext, or replay the cached decrypt failure without more KDF work."""

        for entry in self.entries:
            if entry.doc_hash != document.doc_hash:
                continue
            if entry.plaintext is not None:
                return entry.plaintext
            raise ValueError(entry.error or "cached import decryption failed")
        raise ValueError("import document is not part of the decoded import session")


@dataclass(frozen=True)
class DecodedExtensionLink:
    link: AuthenticatedExtensionChainLink
    auth_payload: AuthPayload | None
    auth_status: str
    root_authority_verified: bool


@dataclass(frozen=True)
class ChainRecoveryResult:
    manifest: EnvelopeManifest
    extracted: tuple[tuple[ManifestFile, bytes], ...]
    selected_extension_index: int | None
    selected_extension_doc_hash: str | None


@dataclass(frozen=True)
class RootManifestAuthority:
    embedded_sign_pub: bytes | None
    mismatch: bool


@dataclass(frozen=True)
class RecoveryReplayFailure:
    stage: str
    message: str
    head_index: int | None = None
    head_doc_hash: str | None = None
    head_dir_name: str | None = None


@dataclass(frozen=True)
class RecoveryHeadTrustRefusal:
    code: str
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class RecoveryExtensionInventory:
    """Published extension inventory assembled from recovery document content."""

    extensions: tuple[ImportedRecoveryDocument, ...]
    explicit_selection: bool = False
    requested_head_index: int | None = None
    requested_head_doc_hash: str | None = None
    requested_target_matched: bool = False
    latest_head_index: int | None = None
    latest_head_doc_hash: str | None = None
    latest_head_dir_name: str | None = None
    failure: RecoveryReplayFailure | None = None


@dataclass(frozen=True)
class RecoveryChainInspection:
    inventory: RecoveryExtensionInventory
    links: tuple[DecodedExtensionLink, ...]
    latest_state: tuple[LogicalFileState, ...] | None
    locked_chunking: ExtensionChunkingProfile | None
    refusal: RecoveryHeadTrustRefusal | None
    validated_head_index: int
    validated_head_doc_hash: str
    validated_head_auth_status: str | None
    validated_head_root_authority_verified: bool | None


class RecoveryPlanLike(Protocol):
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
    decoded: ExtensionEnvelope
    auth_payload: AuthPayload
    auth_status: str


def _dedupe_frames(frames: list[Frame]) -> list[Frame]:
    """Deduplicate frames by type/index/doc_id, rejecting conflicts."""

    seen: dict[tuple[int, int, bytes], Frame] = {}
    deduped: list[Frame] = []
    for frame in frames:
        key = (int(frame.frame_type), int(frame.index), frame.doc_id)
        existing = seen.get(key)
        if existing:
            if existing.data != frame.data or existing.total != frame.total:
                raise ValueError("conflicting duplicate frames detected")
            continue
        seen[key] = frame
        deduped.append(frame)
    return deduped


def _split_main_and_auth_frames(frames: list[Frame]) -> tuple[list[Frame], list[Frame]]:
    """Split decoded frames into MAIN and AUTH lists."""

    main_frames: list[Frame] = []
    auth_frames: list[Frame] = []
    for frame in frames:
        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            main_frames.append(frame)
        elif frame.frame_type == FrameType.AUTH:
            auth_frames.append(frame)
        else:
            raise ValueError("unexpected frame type in main document QR payloads")
    if not main_frames:
        raise ValueError(
            "no main document payloads provided; check the MAIN QR payloads or recovery text"
        )
    return main_frames, auth_frames


def imported_documents_from_recovery_frames(
    frames: list[Frame],
    *,
    source_label: str = "content import",
) -> tuple[ImportedRecoveryDocument, ...]:
    """Group MAIN/AUTH recovery frames into independently recoverable documents."""

    deduped = _dedupe_frames(frames)
    pre_main_doc_ids = {
        frame.doc_id for frame in deduped if frame.frame_type == FrameType.MAIN_DOCUMENT
    }
    pre_auth_doc_ids = {frame.doc_id for frame in deduped if frame.frame_type == FrameType.AUTH}
    pre_orphan_auth_doc_ids = sorted(pre_auth_doc_ids - pre_main_doc_ids)
    if pre_orphan_auth_doc_ids:
        preview = ", ".join(doc_id.hex() for doc_id in pre_orphan_auth_doc_ids[:3])
        raise ValueError(f"{source_label} contains AUTH frame(s) without matching MAIN: {preview}")
    main_frames, auth_frames = _split_main_and_auth_frames(deduped)
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
    orphan_auth_doc_ids = sorted(set(auth_by_doc_id) - set(main_by_doc_id))
    if orphan_auth_doc_ids:
        preview = ", ".join(doc_id.hex() for doc_id in orphan_auth_doc_ids[:3])
        raise ValueError(f"{source_label} contains AUTH frame(s) without matching MAIN: {preview}")

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
    """Pick exactly one V1 root backup from imported content."""

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
    """Classify imports and retain the single bounded decrypt pass for later replay."""

    require_chain_resource_limits(
        document_count=len(documents),
        total_ciphertext_bytes=sum(len(document.ciphertext) for document in documents),
        operation="content import",
    )

    roots: list[ImportedRecoveryDocument] = []
    decoded_entries: list[_DecodedImportEntry] = []
    extension_count = 0
    decode_errors: list[str] = []
    for document in documents:
        try:
            plaintext = decrypt_bytes(document.ciphertext, passphrase=passphrase, debug=debug)
        except Exception as exc:
            error = str(exc)
            decoded_entries.append(
                _DecodedImportEntry(
                    doc_hash=document.doc_hash,
                    plaintext=None,
                    error=error,
                )
            )
            decode_errors.append(f"{document.doc_id.hex()}: {error}")
            continue
        decoded_entries.append(
            _DecodedImportEntry(
                doc_hash=document.doc_hash,
                plaintext=plaintext,
                error=None,
            )
        )
        try:
            version = detect_envelope_version(plaintext)
            decoded = decode_any_envelope(plaintext)[1] if version == 1 else None
        except ExtensionDecodedChunkBudgetError:
            raise
        except Exception as exc:
            decode_errors.append(f"{document.doc_id.hex()}: {exc}")
            continue
        if version == 1 and isinstance(decoded, tuple) and len(decoded) == 2:
            roots.append(document)
        elif version == 2:
            extension_count += 1
        else:
            decode_errors.append(
                f"{document.doc_id.hex()}: unsupported envelope version: {version}"
            )

    if len(roots) == 1:
        return DecodedImportSession(
            root_document=roots[0],
            entries=tuple(decoded_entries),
        )
    if not roots:
        detail = "; ".join(decode_errors[:3])
        suffix = f" ({detail})" if detail else ""
        raise ValueError(f"content import did not contain a decryptable root backup{suffix}")
    raise ValueError(
        "content import contains multiple root backups; provide one root backup per "
        "recovery session "
        f"({len(roots)} roots, {extension_count} extensions)"
    )


def recover_chain_entries(
    plan: RecoveryPlanLike,
    *,
    quiet: bool,
    debug: bool = False,
) -> ChainRecoveryResult:
    if plan.import_documents:
        return recover_imported_chain_entries(plan, quiet=quiet, debug=debug)

    root_manifest, payload = decode_root_manifest(
        ciphertext=plan.ciphertext,
        passphrase=plan.passphrase,
        debug=debug,
    )
    validate_root_manifest_authority(root_manifest, plan.auth_payload, doc_hash=plan.doc_hash)
    _ensure_expected_head_satisfied(
        plan,
        selected_extension_index=None,
        selected_extension_doc_hash=None,
    )
    return ChainRecoveryResult(
        manifest=root_manifest,
        extracted=tuple(extract_payloads(root_manifest, payload)),
        selected_extension_index=None,
        selected_extension_doc_hash=None,
    )


def recover_imported_chain_entries(
    plan: RecoveryPlanLike, *, quiet: bool, debug: bool = False
) -> ChainRecoveryResult:
    _ = quiet
    require_chain_resource_limits(
        document_count=len(plan.import_documents),
        total_ciphertext_bytes=sum(len(document.ciphertext) for document in plan.import_documents),
        operation="content import",
    )
    if plan.extension_index is not None and plan.extension_doc_hash is not None:
        raise ValueError("use either --extension-index or --extension-doc-hash, not both")

    decoded_import_session = getattr(plan, "decoded_import_session", None)
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
        validate_root_manifest_authority(root_manifest, plan.auth_payload, doc_hash=plan.doc_hash)
        _ensure_expected_head_satisfied(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        return ChainRecoveryResult(
            manifest=root_manifest,
            extracted=tuple(extract_payloads(root_manifest, payload)),
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )

    if plan.extension_index == 0:
        validate_root_manifest_authority(root_manifest, plan.auth_payload, doc_hash=plan.doc_hash)
        _ensure_expected_head_satisfied(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        return ChainRecoveryResult(
            manifest=root_manifest,
            extracted=tuple(extract_payloads(root_manifest, payload)),
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )

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

    if plan.auth_payload is None or plan.auth_status != "verified":
        raise extension_errors.ExtensionRecoveryError(
            code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
            message="extension import recovery requires verified root AUTH",
            details={
                "stage": "auth",
                "root_auth_status": plan.auth_status,
                "validated_head_index": 0,
                "validated_head_doc_hash": plan.doc_hash.hex(),
            },
        )

    root_sign_pub = validate_root_manifest_authority(
        root_manifest,
        plan.auth_payload,
        doc_hash=plan.doc_hash,
    )
    if root_sign_pub is None:
        raise extension_errors.ExtensionRecoveryError(
            code=extension_errors.RECOVERY_HEAD_UNTRUSTED,
            message="extension import recovery requires an unsealed root signing authority",
            details={
                "stage": "auth",
                "validated_head_index": 0,
                "validated_head_doc_hash": plan.doc_hash.hex(),
            },
        )

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
        return ChainRecoveryResult(
            manifest=root_manifest,
            extracted=tuple(extract_payloads(root_manifest, payload)),
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )

    try:
        latest_state = reconstruct_authenticated_latest_logical_state(
            root_manifest,
            payload,
            root_doc_hash=plan.doc_hash,
            expected_sign_pub=root_sign_pub,
            extensions=tuple(item.link for item in selected_links),
        )
    except ValueError as exc:
        raise _chain_replay_head_untrusted_error(
            exc,
            plan=plan,
            decoded_links=decoded_links,
            selected_links=selected_links,
            root_manifest=root_manifest,
            payload=payload,
            expected_sign_pub=root_sign_pub,
        ) from exc
    latest_manifest = _synthetic_manifest_from_state(
        root_manifest,
        latest_state,
    )
    state_by_path = {item.path: item.data for item in latest_state}
    extracted = tuple((entry, state_by_path[entry.path]) for entry in latest_manifest.files)
    selected_extension_index = selected_links[-1].link.document.header.index
    selected_extension_doc_hash = selected_links[-1].link.doc_hash.hex()
    _ensure_expected_head_satisfied(
        plan,
        selected_extension_index=selected_extension_index,
        selected_extension_doc_hash=selected_extension_doc_hash,
    )
    return ChainRecoveryResult(
        manifest=latest_manifest,
        extracted=extracted,
        selected_extension_index=selected_extension_index,
        selected_extension_doc_hash=selected_extension_doc_hash,
    )


def _ensure_expected_head_satisfied(
    plan: RecoveryPlanLike,
    *,
    selected_extension_index: int | None,
    selected_extension_doc_hash: str | None,
) -> None:
    expected_head_doc_hash = getattr(plan, "expected_head_doc_hash", None)
    if expected_head_doc_hash is None:
        return
    expected = _parse_extension_doc_hash(expected_head_doc_hash).hex()
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
    plan: RecoveryPlanLike,
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
    exc: ValueError,
    *,
    plan: RecoveryPlanLike,
    decoded_links: tuple[DecodedExtensionLink, ...],
    selected_links: tuple[DecodedExtensionLink, ...],
    root_manifest: EnvelopeManifest,
    payload: bytes,
    expected_sign_pub: bytes,
) -> extension_errors.ExtensionRecoveryError:
    failure, validated_links = locate_replay_failure(
        root_manifest=root_manifest,
        payload=payload,
        root_doc_hash=plan.doc_hash,
        expected_sign_pub=expected_sign_pub,
        selected_links=selected_links,
    )
    head_index, head_hash, head_auth, head_verified = _validated_head_details(
        plan.doc_hash,
        validated_links,
    )
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
            "failure_stage": "chain",
            "failure_message": failure_message,
            "failure_head_index": failure.link.document.header.index,
            "failure_head_doc_hash": failure.link.doc_hash.hex(),
            "latest_head_index": latest_head_index,
            "latest_head_doc_hash": latest_head_doc_hash,
            "requested_head_index": plan.extension_index,
            "requested_head_doc_hash": requested_doc_hash,
            "validated_head_index": head_index,
            "validated_head_doc_hash": head_hash,
            "validated_head_auth_status": head_auth,
            "validated_head_root_authority_verified": head_verified,
            "explicit_selection": explicit_selection,
        },
    )


def locate_replay_failure(
    *,
    root_manifest: EnvelopeManifest,
    payload: bytes,
    root_doc_hash: bytes,
    expected_sign_pub: bytes,
    selected_links: tuple[DecodedExtensionLink, ...],
) -> tuple[DecodedExtensionLink, tuple[DecodedExtensionLink, ...]]:
    for end in range(1, len(selected_links) + 1):
        prefix = selected_links[:end]
        try:
            reconstruct_authenticated_latest_logical_state(
                root_manifest,
                payload,
                root_doc_hash=root_doc_hash,
                expected_sign_pub=expected_sign_pub,
                extensions=tuple(item.link for item in prefix),
            )
        except ValueError:
            return prefix[-1], prefix[:-1]
    return selected_links[-1], selected_links[:-1]


def _validated_head_details(
    root_doc_hash: bytes,
    links: tuple[DecodedExtensionLink, ...],
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
        fail_on_root_authority_errors=requested_index is None and requested_doc_hash is None,
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
    fail_on_root_authority_errors: bool,
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
        try:
            auth_payload, auth_status = _resolve_verified_extension_auth(
                document,
                expected_sign_pub=expected_sign_pub,
            )
        except ValueError as exc:
            if document.doc_hash == requested_doc_hash:
                raise _extension_auth_api_error(
                    document,
                    message=str(exc),
                    explicit_selection=True,
                ) from exc
            if fail_on_root_authority_errors:
                raise _extension_auth_api_error(document, message=str(exc)) from exc
            continue
        try:
            plaintext = _import_document_plaintext(
                document,
                passphrase=passphrase,
                debug=debug,
                decoded_import_session=decoded_import_session,
            )
            version, decoded_document = decode_any_envelope(
                plaintext,
                max_extension_inline_chunk_bytes=remaining_inline_chunk_bytes,
            )
        except ExtensionDecodedChunkBudgetError:
            raise
        except Exception as exc:
            message = f"imported root-authority document could not be decoded: {exc}"
            if document.doc_hash == requested_doc_hash:
                _raise_selected_extension_candidate_error(
                    document,
                    expected_sign_pub=expected_sign_pub,
                    stage="decode",
                    message=message,
                )
            if fail_on_root_authority_errors:
                _raise_if_document_signed_by_root_authority(
                    document,
                    expected_sign_pub=expected_sign_pub,
                    stage="decode",
                    message=message,
                )
            continue
        if version != 2 or not isinstance(decoded_document, ExtensionEnvelope):
            message = "imported root-authority document did not decode as an extension envelope"
            if document.doc_hash == requested_doc_hash:
                _raise_selected_extension_candidate_error(
                    document,
                    expected_sign_pub=expected_sign_pub,
                    stage="decode",
                    message=message,
                )
            if fail_on_root_authority_errors:
                _raise_if_document_signed_by_root_authority(
                    document,
                    expected_sign_pub=expected_sign_pub,
                    stage="decode",
                    message=message,
                )
            continue
        remaining_inline_chunk_bytes -= decoded_document.inline_chunk_raw_bytes
        if decoded_document.header.root_doc_hash != root_doc_hash:
            message = "imported root-authority extension does not target the selected root document"
            if document.doc_hash == requested_doc_hash:
                _raise_selected_extension_candidate_error(
                    document,
                    expected_sign_pub=expected_sign_pub,
                    stage="chain",
                    message=message,
                )
            if fail_on_root_authority_errors:
                _raise_if_document_signed_by_root_authority(
                    document,
                    expected_sign_pub=expected_sign_pub,
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


def _requested_extension_doc_hash_bytes(requested_doc_hash: str | None) -> bytes | None:
    if requested_doc_hash is None:
        return None
    return _parse_extension_doc_hash(requested_doc_hash)


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
        requested = _parse_extension_doc_hash(requested_doc_hash)
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
                    root_authority_verified=True,
                ),
                auth_payload=candidate.auth_payload,
                auth_status=candidate.auth_status,
                root_authority_verified=True,
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
        raise ValueError("imported extension AUTH signing key does not match root authority")
    return auth_payload, auth_status


def _extension_auth_api_error(
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


def _raise_if_document_signed_by_root_authority(
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
        details["root_authority_verified"] = auth_payload.sign_pub == expected_sign_pub
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
    quiet: bool,
    debug: bool,
    max_inline_chunk_bytes: int = MAX_RECOVERY_DECODED_CHUNK_BYTES,
    decoded_import_session: DecodedImportSession | None = None,
) -> DecodedExtensionLink:
    _ = quiet
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
    version, decoded = decode_any_envelope(
        plaintext,
        max_extension_inline_chunk_bytes=max_inline_chunk_bytes,
    )
    if version != 2 or not isinstance(decoded, ExtensionEnvelope):
        raise ValueError("imported document did not decode as an extension envelope")

    return DecodedExtensionLink(
        link=AuthenticatedExtensionChainLink(
            doc_hash=document.doc_hash,
            document=decoded,
            auth_payload=auth_payload,
            expected_sign_pub=expected_sign_pub,
            auth_status=auth_status,
            root_authority_verified=True,
        ),
        auth_payload=auth_payload,
        auth_status=auth_status,
        root_authority_verified=True,
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
        requested = _parse_extension_doc_hash(requested_doc_hash)
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
        _parse_extension_doc_hash(requested_doc_hash)
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
) -> tuple[EnvelopeManifest, bytes]:
    plaintext = decrypt_bytes(ciphertext, passphrase=passphrase, debug=debug)
    return _decode_root_plaintext(plaintext)


def decode_imported_root_manifest(
    document: ImportedRecoveryDocument,
    *,
    decoded_import_session: DecodedImportSession,
) -> tuple[EnvelopeManifest, bytes]:
    """Decode a root using plaintext authenticated by an earlier import decrypt pass."""

    if document.doc_hash != decoded_import_session.root_document.doc_hash:
        raise ValueError("decoded import session root does not match selected root document")
    return _decode_root_plaintext(decoded_import_session.plaintext_for(document))


def _decode_root_plaintext(plaintext: bytes) -> tuple[EnvelopeManifest, bytes]:
    version, decoded = decode_any_envelope(plaintext)
    if version != 1 or not isinstance(decoded, tuple) or len(decoded) != 2:
        raise ValueError("root backup must decode as Envelope V1")
    manifest, payload = decoded
    if not isinstance(manifest, EnvelopeManifest) or not isinstance(payload, bytes):
        raise ValueError("root backup did not decode correctly")
    return manifest, payload


def resolve_root_manifest_authority(
    manifest: EnvelopeManifest,
    auth_payload: AuthPayload | None,
) -> RootManifestAuthority:
    if manifest.signing_seed is None:
        return RootManifestAuthority(embedded_sign_pub=None, mismatch=False)

    embedded_sign_pub = derive_public_key(manifest.signing_seed)
    mismatch = auth_payload is not None and auth_payload.sign_pub != embedded_sign_pub
    return RootManifestAuthority(embedded_sign_pub=embedded_sign_pub, mismatch=mismatch)


def validate_root_manifest_authority(
    manifest: EnvelopeManifest,
    auth_payload: AuthPayload | None,
    *,
    doc_hash: bytes,
) -> bytes | None:
    """Cryptographically validate root AUTH and its embedded signing authority."""

    if auth_payload is not None:
        if not hmac.compare_digest(auth_payload.doc_hash, doc_hash):
            raise extension_errors.ExtensionRecoveryError(
                code=extension_errors.AUTH_DOC_HASH_MISMATCH,
                message="root AUTH doc_hash does not match the recovered root ciphertext",
                details={"stage": "auth"},
            )
        if not verify_auth(
            doc_hash, sign_pub=auth_payload.sign_pub, signature=auth_payload.signature
        ):
            raise extension_errors.ExtensionRecoveryError(
                code=extension_errors.AUTH_SIGNATURE_INVALID,
                message="root AUTH signature verification failed",
                details={"stage": "auth"},
            )

    authority = resolve_root_manifest_authority(manifest, auth_payload)
    if authority.mismatch:
        raise extension_errors.ExtensionRecoveryError(
            code=extension_errors.ROOT_AUTHORITY_MISMATCH,
            message="embedded signing seed does not match the verified root AUTH authority",
            details={"stage": "auth"},
        )
    return authority.embedded_sign_pub


def decode_authenticated_extension_link(
    item: ImportedRecoveryDocument,
    *,
    passphrase: str,
    expected_sign_pub: bytes | None,
    quiet: bool,
    debug: bool,
    max_inline_chunk_bytes: int = MAX_RECOVERY_DECODED_CHUNK_BYTES,
    decoded_import_session: DecodedImportSession | None = None,
) -> DecodedExtensionLink:
    if expected_sign_pub is None:
        raise ValueError("extension replay requires an unsealed root signing authority")
    return decode_imported_extension_link(
        item,
        passphrase=passphrase,
        expected_sign_pub=expected_sign_pub,
        quiet=quiet,
        debug=debug,
        max_inline_chunk_bytes=max_inline_chunk_bytes,
        decoded_import_session=decoded_import_session,
    )


def _selected_root_import_document(plan: RecoveryPlanLike) -> ImportedRecoveryDocument:
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


def _parse_extension_doc_hash(value: str) -> bytes:
    normalized = value.strip().lower()
    try:
        requested_bytes = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError("--extension-doc-hash must be lowercase hex") from exc
    if len(requested_bytes) != 32:
        raise ValueError("--extension-doc-hash must be a 32-byte hex value")
    return requested_bytes


def _synthetic_manifest_from_state(
    root_manifest: EnvelopeManifest,
    state: tuple[LogicalFileState, ...],
) -> EnvelopeManifest:
    return EnvelopeManifest(
        format_version=root_manifest.format_version,
        created_at=root_manifest.created_at,
        sealed=root_manifest.sealed,
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
        payload_raw_len=None,
    )


__all__ = [
    "ChainRecoveryResult",
    "DecodedImportSession",
    "DecodedExtensionLink",
    "ImportedRecoveryDocument",
    "RecoveryChainInspection",
    "RecoveryExtensionInventory",
    "RecoveryHeadTrustRefusal",
    "RecoveryReplayFailure",
    "RootManifestAuthority",
    "decode_authenticated_extension_link",
    "decode_imported_extension_link",
    "decode_imported_root_manifest",
    "decode_root_manifest",
    "imported_document_from_recovery_frames",
    "imported_documents_from_recovery_frames",
    "locate_replay_failure",
    "recover_chain_entries",
    "recover_imported_chain_entries",
    "resolve_required_auth_payload",
    "resolve_root_manifest_authority",
    "select_root_import_document",
    "select_root_import_session",
    "validate_expected_recovery_head",
    "validate_root_manifest_authority",
]
