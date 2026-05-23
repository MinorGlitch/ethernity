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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ethernity.cli.features.recover.key_recovery import resolve_auth_payload
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.io.frames import (
    _dedupe_frames,
    _split_main_and_auth_frames,
    recovery_frames_from_scan,
)
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.signing import AuthPayload, derive_public_key
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions.chain import (
    AuthenticatedExtensionChainLink,
    LogicalFileState,
    reconstruct_authenticated_latest_logical_state,
)
from ethernity.formats.envelope_codec import decode_any_envelope, extract_payloads
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile
from ethernity.formats.extension_envelope import ExtensionChunkingProfile, ExtensionEnvelope

if TYPE_CHECKING:
    from ethernity.cli.features.recover.planning import RecoveryPlan


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
        if not isinstance(self.doc_id, (bytes, bytearray)) or len(self.doc_id) != 8:
            raise ValueError("imported recovery document doc_id must be 8 bytes")
        if not isinstance(self.doc_hash, (bytes, bytearray)) or len(self.doc_hash) != 32:
            raise ValueError("imported recovery document doc_hash must be 32 bytes")
        if self.extension_index is not None and (
            isinstance(self.extension_index, bool)
            or not isinstance(self.extension_index, int)
            or self.extension_index <= 0
        ):
            raise ValueError("published extension index must be a positive integer")
        if self.extension_dir_name is not None and (
            not isinstance(self.extension_dir_name, str) or not self.extension_dir_name
        ):
            raise ValueError("published extension directory name must be non-empty")
        object.__setattr__(self, "doc_id", bytes(self.doc_id))
        object.__setattr__(self, "doc_hash", bytes(self.doc_hash))
        object.__setattr__(self, "ciphertext", bytes(self.ciphertext))
        object.__setattr__(self, "auth_frames", tuple(self.auth_frames))

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


@dataclass(frozen=True)
class _DecodedExtensionCandidate:
    document: ImportedRecoveryDocument
    decoded: ExtensionEnvelope


def imported_documents_from_recovery_frames(
    frames: list[Frame],
    *,
    source_label: str = "content import",
) -> tuple[ImportedRecoveryDocument, ...]:
    """Group MAIN/AUTH recovery frames into independently recoverable documents."""

    deduped = _dedupe_frames(frames)
    main_frames, auth_frames = _split_main_and_auth_frames(deduped)
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
            ImportedRecoveryDocument(
                doc_id=doc_id,
                doc_hash=doc_hash,
                ciphertext=ciphertext,
                auth_frames=tuple(auth_by_doc_id.get(doc_id, ())),
                source_label=f"{source_label}:{doc_id.hex()}",
            )
        )
    return tuple(documents)


def select_root_import_document(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    passphrase: str,
    debug: bool,
) -> ImportedRecoveryDocument:
    """Pick exactly one V1 root backup from imported content."""

    roots: list[ImportedRecoveryDocument] = []
    extension_count = 0
    decode_errors: list[str] = []
    for document in documents:
        try:
            plaintext = decrypt_bytes(document.ciphertext, passphrase=passphrase, debug=debug)
            version, decoded = decode_any_envelope(plaintext)
        except Exception as exc:
            decode_errors.append(f"{document.doc_id.hex()}: {exc}")
            continue
        if version == 1 and isinstance(decoded, tuple) and len(decoded) == 2:
            roots.append(document)
        elif version == 2 and isinstance(decoded, ExtensionEnvelope):
            extension_count += 1

    if len(roots) == 1:
        return roots[0]
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
    plan: "RecoveryPlan", *, quiet: bool, debug: bool = False
) -> ChainRecoveryResult:
    if plan.import_documents:
        return recover_imported_chain_entries(plan, quiet=quiet, debug=debug)

    root_manifest, payload = decode_root_manifest(
        ciphertext=plan.ciphertext,
        passphrase=plan.passphrase,
        debug=debug,
    )
    validate_root_manifest_authority(root_manifest, plan.auth_payload)
    return ChainRecoveryResult(
        manifest=root_manifest,
        extracted=tuple(extract_payloads(root_manifest, payload)),
        selected_extension_index=None,
        selected_extension_doc_hash=None,
    )


def recover_imported_chain_entries(
    plan: "RecoveryPlan", *, quiet: bool, debug: bool = False
) -> ChainRecoveryResult:
    root_manifest, payload = decode_root_manifest(
        ciphertext=plan.ciphertext,
        passphrase=plan.passphrase,
        debug=debug,
    )
    if len(plan.import_documents) <= 1:
        _ensure_root_selector_satisfied(
            requested_index=plan.extension_index,
            requested_doc_hash=plan.extension_doc_hash,
        )
        validate_root_manifest_authority(root_manifest, plan.auth_payload)
        return ChainRecoveryResult(
            manifest=root_manifest,
            extracted=tuple(extract_payloads(root_manifest, payload)),
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )

    if plan.extension_index == 0:
        validate_root_manifest_authority(root_manifest, plan.auth_payload)
        return ChainRecoveryResult(
            manifest=root_manifest,
            extracted=tuple(extract_payloads(root_manifest, payload)),
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )

    if plan.allow_unsigned:
        raise ApiCommandError(
            code=api_codes.RECOVERY_HEAD_UNTRUSTED,
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
        raise ApiCommandError(
            code=api_codes.RECOVERY_HEAD_UNTRUSTED,
            message="extension import recovery requires verified root AUTH",
            details={
                "stage": "auth",
                "root_auth_status": plan.auth_status,
                "validated_head_index": 0,
                "validated_head_doc_hash": plan.doc_hash.hex(),
            },
        )

    root_sign_pub = validate_root_manifest_authority(root_manifest, plan.auth_payload)
    if root_sign_pub is None:
        raise ApiCommandError(
            code=api_codes.RECOVERY_HEAD_UNTRUSTED,
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
        quiet=quiet,
        debug=debug,
    )
    selected_links = _select_imported_chain_links(
        decoded_links,
        requested_index=plan.extension_index,
        requested_doc_hash=plan.extension_doc_hash,
    )
    if not selected_links:
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
    return ChainRecoveryResult(
        manifest=latest_manifest,
        extracted=extracted,
        selected_extension_index=selected_links[-1].link.document.header.index,
        selected_extension_doc_hash=selected_links[-1].link.doc_hash.hex(),
    )


def _chain_replay_head_untrusted_error(
    exc: ValueError,
    *,
    plan: "RecoveryPlan",
    decoded_links: tuple[DecodedExtensionLink, ...],
    selected_links: tuple[DecodedExtensionLink, ...],
    root_manifest: EnvelopeManifest,
    payload: bytes,
    expected_sign_pub: bytes,
) -> ApiCommandError:
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
    return ApiCommandError(
        code=api_codes.RECOVERY_HEAD_UNTRUSTED,
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


def _decode_imported_extension_links(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    root_doc_hash: bytes,
    root_doc_id: bytes,
    passphrase: str,
    expected_sign_pub: bytes,
    requested_index: int | None = None,
    requested_doc_hash: str | None = None,
    quiet: bool,
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
        quiet=quiet,
        debug=debug,
    )
    candidates = _select_extension_candidates_for_auth(
        candidates,
        requested_index=requested_index,
        requested_doc_hash=requested_doc_hash,
    )
    return _authenticate_imported_extension_candidates(
        candidates,
        expected_sign_pub=expected_sign_pub,
        quiet=quiet,
    )


def _decode_imported_extension_candidates(
    documents: tuple[ImportedRecoveryDocument, ...],
    *,
    root_doc_hash: bytes,
    root_doc_id: bytes,
    passphrase: str,
    expected_sign_pub: bytes,
    fail_on_root_authority_errors: bool,
    quiet: bool,
    debug: bool,
) -> tuple[_DecodedExtensionCandidate, ...]:
    candidates: list[_DecodedExtensionCandidate] = []
    seen_doc_hashes = {root_doc_hash}
    for document in documents:
        if document.doc_hash in seen_doc_hashes:
            continue
        if document.doc_id == root_doc_id:
            raise ApiCommandError(
                code=api_codes.RECOVERY_HEAD_UNTRUSTED,
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
            plaintext = decrypt_bytes(document.ciphertext, passphrase=passphrase, debug=debug)
            version, decoded_document = decode_any_envelope(plaintext)
        except Exception as exc:
            if fail_on_root_authority_errors:
                _raise_if_document_signed_by_root_authority(
                    document,
                    expected_sign_pub=expected_sign_pub,
                    quiet=quiet,
                    stage="decode",
                    message=f"imported root-authority document could not be decoded: {exc}",
                )
            continue
        if version != 2 or not isinstance(decoded_document, ExtensionEnvelope):
            if fail_on_root_authority_errors:
                _raise_if_document_signed_by_root_authority(
                    document,
                    expected_sign_pub=expected_sign_pub,
                    quiet=quiet,
                    stage="decode",
                    message=(
                        "imported root-authority document did not decode as an extension envelope"
                    ),
                )
            continue
        if decoded_document.header.root_doc_hash != root_doc_hash:
            if fail_on_root_authority_errors:
                _raise_if_document_signed_by_root_authority(
                    document,
                    expected_sign_pub=expected_sign_pub,
                    quiet=quiet,
                    stage="chain",
                    message=(
                        "imported root-authority extension does not target the selected "
                        "root document"
                    ),
                )
            continue
        seen_doc_hashes.add(document.doc_hash)
        candidates.append(_DecodedExtensionCandidate(document=document, decoded=decoded_document))
    return tuple(candidates)


def _select_extension_candidates_for_auth(
    candidates: tuple[_DecodedExtensionCandidate, ...],
    *,
    requested_index: int | None,
    requested_doc_hash: str | None,
) -> tuple[_DecodedExtensionCandidate, ...]:
    if requested_index is not None:
        if requested_index < 0:
            raise ValueError("--extension-index must be >= 0")
        if requested_index == 0:
            return ()
        if not any(candidate.decoded.header.index == requested_index for candidate in candidates):
            raise ValueError(f"extension index {requested_index} was not found")
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
            raise ValueError(
                f"extension doc_hash {requested_doc_hash.strip().lower()} was not found"
            )
        return tuple(
            candidate for candidate in candidates if candidate.decoded.header.index <= target_index
        )
    return candidates


def _authenticate_imported_extension_candidates(
    candidates: tuple[_DecodedExtensionCandidate, ...],
    *,
    expected_sign_pub: bytes,
    quiet: bool,
) -> tuple[DecodedExtensionLink, ...]:
    links: list[DecodedExtensionLink] = []
    for candidate in candidates:
        document = candidate.document
        try:
            auth_payload, auth_status = resolve_auth_payload(
                list(document.auth_frames),
                doc_id=document.doc_id,
                doc_hash=document.doc_hash,
                allow_unsigned=False,
                require_auth=True,
                quiet=quiet,
            )
        except ValueError as exc:
            raise ApiCommandError(
                code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                message=f"imported extension AUTH could not be verified: {exc}",
                details={
                    "stage": "auth",
                    "extension_doc_hash": document.doc_hash.hex(),
                },
            ) from exc
        if auth_payload is None or auth_payload.sign_pub != expected_sign_pub:
            raise ApiCommandError(
                code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                message="imported extension AUTH signing key does not match root authority",
                details={
                    "stage": "auth",
                    "extension_doc_hash": document.doc_hash.hex(),
                },
            )

        links.append(
            DecodedExtensionLink(
                link=AuthenticatedExtensionChainLink(
                    doc_hash=document.doc_hash,
                    document=candidate.decoded,
                    auth_payload=auth_payload,
                    expected_sign_pub=expected_sign_pub,
                    auth_status=auth_status,
                    root_authority_verified=True,
                ),
                auth_payload=auth_payload,
                auth_status=auth_status,
                root_authority_verified=True,
            )
        )

    by_index: dict[int, DecodedExtensionLink] = {}
    for link in links:
        index = link.link.document.header.index
        existing = by_index.get(index)
        if existing is not None and existing.link.doc_hash != link.link.doc_hash:
            raise ApiCommandError(
                code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                message=(
                    f"content import contains multiple authenticated extensions for index {index}"
                ),
                details={"stage": "selection", "extension_index": index},
            )
        by_index[index] = link
    return tuple(by_index[index] for index in sorted(by_index))


def _raise_if_document_signed_by_root_authority(
    document: ImportedRecoveryDocument,
    *,
    expected_sign_pub: bytes,
    quiet: bool,
    stage: str,
    message: str,
) -> None:
    try:
        auth_payload, _auth_status = resolve_auth_payload(
            list(document.auth_frames),
            doc_id=document.doc_id,
            doc_hash=document.doc_hash,
            allow_unsigned=False,
            require_auth=True,
            quiet=quiet,
        )
    except ValueError:
        return
    if auth_payload is not None and auth_payload.sign_pub == expected_sign_pub:
        raise ApiCommandError(
            code=api_codes.RECOVERY_HEAD_UNTRUSTED,
            message=message,
            details={
                "stage": stage,
                "extension_doc_hash": document.doc_hash.hex(),
            },
        )


def decode_imported_extension_link(
    document: ImportedRecoveryDocument,
    *,
    passphrase: str,
    expected_sign_pub: bytes,
    quiet: bool,
    debug: bool,
) -> DecodedExtensionLink:
    plaintext = decrypt_bytes(document.ciphertext, passphrase=passphrase, debug=debug)
    version, decoded = decode_any_envelope(plaintext)
    if version != 2 or not isinstance(decoded, ExtensionEnvelope):
        raise ValueError("imported document did not decode as an extension envelope")

    auth_payload, auth_status = resolve_auth_payload(
        list(document.auth_frames),
        doc_id=document.doc_id,
        doc_hash=document.doc_hash,
        allow_unsigned=False,
        require_auth=True,
        quiet=quiet,
    )
    if auth_payload is None or auth_payload.sign_pub != expected_sign_pub:
        raise ValueError("extension AUTH signing key does not match root authority")

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
            raise ValueError(f"extension index {requested_index} was not found")
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
            raise ValueError(
                f"extension doc_hash {requested_doc_hash.strip().lower()} was not found"
            )
        return tuple(selected)
    return links


def _ensure_root_selector_satisfied(
    *,
    requested_index: int | None,
    requested_doc_hash: str | None,
) -> None:
    if requested_index is not None:
        if requested_index < 0:
            raise ValueError("--extension-index must be >= 0")
        if requested_index > 0:
            raise ValueError(f"extension index {requested_index} was not found")
    if requested_doc_hash is not None:
        _parse_extension_doc_hash(requested_doc_hash)
        raise ValueError(f"extension doc_hash {requested_doc_hash.strip().lower()} was not found")


def decode_root_manifest(
    *,
    ciphertext: bytes,
    passphrase: str,
    debug: bool,
) -> tuple[EnvelopeManifest, bytes]:
    plaintext = decrypt_bytes(ciphertext, passphrase=passphrase, debug=debug)
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
) -> bytes | None:
    """Validate that any verified root AUTH matches the embedded signing seed."""

    authority = resolve_root_manifest_authority(manifest, auth_payload)
    if authority.mismatch:
        raise ApiCommandError(
            code=api_codes.ROOT_AUTHORITY_MISMATCH,
            message="embedded signing seed does not match the verified root AUTH authority",
        )
    return authority.embedded_sign_pub


def decode_authenticated_extension_link(
    item: ImportedRecoveryDocument,
    *,
    passphrase: str,
    expected_sign_pub: bytes | None,
    quiet: bool,
    debug: bool,
) -> DecodedExtensionLink:
    if expected_sign_pub is None:
        raise ValueError("extension replay requires an unsealed root signing authority")
    return decode_imported_extension_link(
        item,
        passphrase=passphrase,
        expected_sign_pub=expected_sign_pub,
        quiet=quiet,
        debug=debug,
    )


def scan_extension_carriers(paths: list[str], *, quiet: bool) -> tuple[bytes, list[Frame]]:
    """Reassemble one extension document from explicitly provided carrier paths."""

    if not paths:
        raise ValueError("no extension MAIN carriers were provided")
    frames = recovery_frames_from_scan(paths, quiet=quiet)
    documents = imported_documents_from_recovery_frames(frames, source_label="extension carrier")
    if len(documents) != 1:
        raise ValueError("extension carrier input must contain exactly one MAIN document")
    document = documents[0]
    return document.ciphertext, list(document.auth_frames)


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
    "DecodedExtensionLink",
    "ImportedRecoveryDocument",
    "RecoveryChainInspection",
    "RecoveryExtensionInventory",
    "RecoveryHeadTrustRefusal",
    "decode_authenticated_extension_link",
    "decode_imported_extension_link",
    "decode_root_manifest",
    "imported_documents_from_recovery_frames",
    "locate_replay_failure",
    "recover_chain_entries",
    "recover_imported_chain_entries",
    "resolve_root_manifest_authority",
    "scan_extension_carriers",
    "select_root_import_document",
    "validate_root_manifest_authority",
]
