from __future__ import annotations

import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    resolve_auth_payload,
    validated_shard_payloads_from_frames,
)
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.io.frames import (
    _detect_recovery_input_mode,
    _frames_from_fallback_lines,
    _frames_from_payload_lines,
)
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    decode_shard_payload,
    recover_passphrase,
    recover_signing_seed,
)
from ethernity.crypto.signing import (
    AuthPayload,
    decode_auth_payload,
    derive_public_key,
    verify_auth,
    verify_shard,
)
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions import (
    AuthenticatedExtensionChainLink,
    reconstruct_authenticated_latest_logical_state,
    validate_authenticated_extension_chain,
)
from ethernity.formats import decode_any_envelope
from ethernity.formats.envelope_codec import extract_payloads
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile
from ethernity.formats.extension_envelope import ExtensionEnvelope

from .bootstrap import SRC_ROOT as _SRC_ROOT  # noqa: F401
from .constants import MODE_AUTO, MODE_FALLBACK, MODE_PAYLOADS
from .formatting import (
    bool_text,
    combined_fallback_text,
    frame_cbor_text,
    frame_fallback_text,
    frame_payload_text,
    frame_raw_text,
    frame_type_name,
    hex_or_none,
    json_text,
    payload_lines_from_frames,
    preview_bytes,
    preview_file_data,
)
from .models import (
    BatchReportEntry,
    FileRecord,
    FrameRecord,
    InspectionResult,
    RecoveredSecretRecord,
    TrustDiagnostic,
)


@dataclass(frozen=True)
class _DecodedMainDocument:
    doc_id: bytes
    frame_count: int
    ciphertext: bytes | None
    doc_hash: bytes | None
    reassembly_error: str | None
    envelope_version: int | None = None
    document_kind: str | None = None
    decoded: tuple[EnvelopeManifest, bytes] | ExtensionEnvelope | None = None
    decrypt_error: str | None = None
    auth_payload: AuthPayload | None = None
    auth_status: str | None = None
    root_authority_verified: bool | None = None


def _parse_text_to_frames(text: str, *, selected_mode: str) -> tuple[str, list[Frame]]:
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        raise ValueError("paste QR payloads or fallback text to inspect")
    input_mode = _detect_recovery_input_mode(lines) if selected_mode == MODE_AUTO else selected_mode
    if input_mode == MODE_PAYLOADS:
        frames = _frames_from_payload_lines(lines, source="pasted input")
    elif input_mode in {MODE_FALLBACK, "fallback_marked"}:
        frames = _frames_from_fallback_lines(lines, allow_invalid_auth=False, quiet=True)
    else:
        raise ValueError(f"unsupported input mode: {input_mode}")
    return input_mode, frames


def _dedupe_inspection_frames(frames: Sequence[Frame]) -> list[Frame]:
    deduped: list[Frame] = []
    seen_indexed: dict[tuple[int, int, bytes], Frame] = {}
    seen_exact: set[tuple[int, bytes, int, int, bytes]] = set()
    for frame in frames:
        if frame.frame_type == FrameType.KEY_DOCUMENT:
            exact_key = (frame.frame_type, frame.doc_id, frame.index, frame.total, frame.data)
            if exact_key in seen_exact:
                continue
            seen_exact.add(exact_key)
            deduped.append(frame)
            continue
        key = (int(frame.frame_type), int(frame.index), frame.doc_id)
        existing = seen_indexed.get(key)
        if existing is not None:
            if existing.data != frame.data or existing.total != frame.total:
                raise ValueError("conflicting duplicate frames detected")
            continue
        seen_indexed[key] = frame
        deduped.append(frame)
    return deduped


def _auth_detail(frame: Frame, *, main_doc_hash: bytes | None) -> dict[str, object]:
    payload = decode_auth_payload(frame.data)
    self_verified = verify_auth(
        payload.doc_hash,
        sign_pub=payload.sign_pub,
        signature=payload.signature,
    )
    main_matches = None
    if main_doc_hash is not None:
        main_matches = hmac.compare_digest(payload.doc_hash, main_doc_hash)
    return {
        "frame": {
            "frame_type": frame_type_name(frame.frame_type),
            "doc_id": frame.doc_id.hex(),
            "index": frame.index,
            "total": frame.total,
            "data_bytes": len(frame.data),
        },
        "auth_payload": {
            "version": payload.version,
            "doc_hash": payload.doc_hash.hex(),
            "sign_pub": payload.sign_pub.hex(),
            "signature": payload.signature.hex(),
            "signature_valid": self_verified,
            "matches_reassembled_main_doc_hash": main_matches,
            "frame_doc_id_matches_hash_prefix": frame.doc_id
            == payload.doc_hash[: len(frame.doc_id)],
        },
    }


def _shard_detail(frame: Frame, *, main_doc_hash: bytes | None) -> dict[str, object]:
    payload = decode_shard_payload(frame.data)
    self_verified = verify_shard(
        payload.doc_hash,
        shard_version=payload.version,
        key_type=payload.key_type,
        threshold=payload.threshold,
        share_count=payload.share_count,
        share_index=payload.share_index,
        secret_len=payload.secret_len,
        share=payload.share,
        shard_set_id=payload.shard_set_id,
        sign_pub=payload.sign_pub,
        signature=payload.signature,
    )
    main_matches = None
    if main_doc_hash is not None:
        main_matches = hmac.compare_digest(payload.doc_hash, main_doc_hash)
    return {
        "frame": {
            "frame_type": frame_type_name(frame.frame_type),
            "doc_id": frame.doc_id.hex(),
            "index": frame.index,
            "total": frame.total,
            "data_bytes": len(frame.data),
        },
        "shard_payload": {
            "version": payload.version,
            "key_type": payload.key_type,
            "share_index": payload.share_index,
            "threshold": payload.threshold,
            "share_count": payload.share_count,
            "secret_len": payload.secret_len,
            "doc_hash": payload.doc_hash.hex(),
            "sign_pub": payload.sign_pub.hex(),
            "signature": payload.signature.hex(),
            "share_bytes": len(payload.share),
            "share_preview": preview_bytes(payload.share),
            "set_id": hex_or_none(payload.shard_set_id),
            "signature_valid": self_verified,
            "matches_reassembled_main_doc_hash": main_matches,
            "frame_doc_id_matches_hash_prefix": frame.doc_id
            == payload.doc_hash[: len(frame.doc_id)],
        },
    }


def _main_detail(frame: Frame) -> dict[str, object]:
    return {
        "frame": {
            "frame_type": frame_type_name(frame.frame_type),
            "doc_id": frame.doc_id.hex(),
            "index": frame.index,
            "total": frame.total,
            "data_bytes": len(frame.data),
            "data_preview": preview_bytes(frame.data),
        }
    }


def _frame_detail(frame: Frame, *, main_doc_hash: bytes | None) -> dict[str, object]:
    if frame.frame_type == FrameType.AUTH:
        return _auth_detail(frame, main_doc_hash=main_doc_hash)
    if frame.frame_type == FrameType.KEY_DOCUMENT:
        return _shard_detail(frame, main_doc_hash=main_doc_hash)
    return _main_detail(frame)


def _build_frame_record(
    frame: Frame,
    *,
    main_doc_hashes_by_doc_id: dict[bytes, bytes],
) -> FrameRecord:
    detail = _frame_detail(frame, main_doc_hash=main_doc_hashes_by_doc_id.get(frame.doc_id))
    return FrameRecord(
        frame=frame,
        detail=detail,
        detail_text=json_text(detail),
        raw_text=frame_raw_text(frame),
        cbor_text=frame_cbor_text(frame),
        payload_text=frame_payload_text(frame),
        fallback_text=frame_fallback_text(frame),
    )


def _manifest_projection(
    manifest: EnvelopeManifest,
    extracted: Sequence[tuple[ManifestFile, bytes]],
) -> tuple[dict[str, object], list[FileRecord]]:
    manifest_files: list[dict[str, object]] = []
    manifest_dict: dict[str, object] = {
        "format_version": manifest.format_version,
        "created_at": manifest.created_at,
        "sealed": manifest.sealed,
        "signing_seed": hex_or_none(manifest.signing_seed),
        "input_origin": manifest.input_origin,
        "input_roots": list(manifest.input_roots),
        "payload_codec": manifest.payload_codec,
        "payload_raw_len": manifest.payload_raw_len,
        "files": manifest_files,
    }
    file_records: list[FileRecord] = []
    for entry, data in extracted:
        preview_kind, preview = preview_file_data(data, path=entry.path)
        manifest_files.append(
            {
                "path": entry.path,
                "size": entry.size,
                "sha256": entry.sha256.hex(),
                "mtime": entry.mtime,
            }
        )
        file_records.append(
            FileRecord(
                path=entry.path,
                size=entry.size,
                sha256=entry.sha256.hex(),
                preview_kind=preview_kind,
                preview=preview,
                data=data,
            )
        )
    return manifest_dict, file_records


def _state_projection(
    state: Sequence[tuple[str, int, bytes, int | None, bytes]],
) -> tuple[list[dict[str, object]], list[FileRecord]]:
    state_files: list[dict[str, object]] = []
    file_records: list[FileRecord] = []
    for path, size, sha256, mtime, data in state:
        preview_kind, preview = preview_file_data(data, path=path)
        state_files.append(
            {
                "path": path,
                "size": size,
                "sha256": sha256.hex(),
                "mtime": mtime,
            }
        )
        file_records.append(
            FileRecord(
                path=path,
                size=size,
                sha256=sha256.hex(),
                preview_kind=preview_kind,
                preview=preview,
                data=data,
            )
        )
    return state_files, file_records


def _document_list_projection(
    documents: Sequence[_DecodedMainDocument],
) -> dict[str, object]:
    items: list[dict[str, object]] = []
    for document in documents:
        item: dict[str, object] = {
            "doc_id": document.doc_id.hex(),
            "frame_count": document.frame_count,
            "doc_hash": None if document.doc_hash is None else document.doc_hash.hex(),
            "reassembly_error": document.reassembly_error,
            "envelope_version": document.envelope_version,
            "document_kind": document.document_kind,
            "decrypt_error": document.decrypt_error,
            "auth_status": document.auth_status,
            "root_authority_verified": _resolved_root_authority_verified(document),
        }
        if document.envelope_version == 1 and isinstance(document.decoded, tuple):
            manifest, _payload = document.decoded
            item["manifest"] = {
                "format_version": manifest.format_version,
                "sealed": manifest.sealed,
                "input_origin": manifest.input_origin,
                "input_roots": list(manifest.input_roots),
                "payload_codec": manifest.payload_codec,
                "file_count": len(manifest.files),
            }
        elif document.envelope_version == 2 and isinstance(document.decoded, ExtensionEnvelope):
            item["extension"] = {
                "index": document.decoded.header.index,
                "file_count": len(document.decoded.files),
                "chunk_count": len(document.decoded.chunks),
                "input_origin": document.decoded.header.input_origin,
                "input_roots": list(document.decoded.header.input_roots),
            }
        items.append(item)
    return {
        "kind": "documents",
        "documents": items,
    }


def _resolved_root_authority_verified(document: _DecodedMainDocument) -> bool | None:
    if document.root_authority_verified is not None:
        return document.root_authority_verified
    if document.envelope_version != 1 or not isinstance(document.decoded, tuple):
        return None

    manifest, _payload = document.decoded
    if manifest.signing_seed is None:
        return None
    if document.auth_status != "verified" or document.auth_payload is None:
        return None

    return bool(
        hmac.compare_digest(
            document.auth_payload.sign_pub,
            derive_public_key(manifest.signing_seed),
        )
    )


def _latest_chain_document(
    root_document: _DecodedMainDocument | None,
    extension_documents: Sequence[_DecodedMainDocument],
) -> tuple[int | None, _DecodedMainDocument | None]:
    sorted_extensions = [
        document
        for document in sorted(
            extension_documents,
            key=lambda item: (
                item.decoded.header.index if isinstance(item.decoded, ExtensionEnvelope) else -1
            ),
        )
        if document.doc_hash is not None and isinstance(document.decoded, ExtensionEnvelope)
    ]
    if sorted_extensions:
        latest_document = sorted_extensions[-1]
        latest_extension = cast(ExtensionEnvelope, latest_document.decoded)
        return latest_extension.header.index, latest_document
    if root_document is not None and root_document.doc_hash is not None:
        return 0, root_document
    return None, None


def _trusted_root_head_details(
    root_document: _DecodedMainDocument | None,
) -> tuple[int | None, str | None, str | None, bool | None]:
    if root_document is None or root_document.doc_hash is None:
        return None, None, None, None

    root_authority_verified = _resolved_root_authority_verified(root_document)
    if root_document.auth_status != "verified" or root_authority_verified is not True:
        return None, None, None, None
    return 0, root_document.doc_hash.hex(), root_document.auth_status, root_authority_verified


def _validated_chain_head_details(
    root_document: _DecodedMainDocument,
    validated_extensions: Sequence[tuple[_DecodedMainDocument, ExtensionEnvelope]],
) -> tuple[int | None, str | None, str | None, bool | None]:
    if validated_extensions:
        latest_document, latest_extension = validated_extensions[-1]
        if latest_document.doc_hash is None:
            return None, None, None, None
        return (
            latest_extension.header.index,
            latest_document.doc_hash.hex(),
            latest_document.auth_status,
            True,
        )
    return _trusted_root_head_details(root_document)


def _base_trust_details(
    *,
    root_document: _DecodedMainDocument | None,
    extension_documents: Sequence[_DecodedMainDocument],
) -> dict[str, object]:
    latest_head_index, latest_document = _latest_chain_document(root_document, extension_documents)
    (
        validated_head_index,
        validated_head_doc_hash,
        validated_head_auth_status,
        validated_head_root,
    ) = _trusted_root_head_details(root_document)
    root_doc_hash = (
        None
        if root_document is None or root_document.doc_hash is None
        else root_document.doc_hash.hex()
    )
    return {
        "latest_head_index": latest_head_index,
        "latest_head_doc_hash": (
            None
            if latest_document is None or latest_document.doc_hash is None
            else latest_document.doc_hash.hex()
        ),
        "requested_head_index": None,
        "requested_head_doc_hash": None,
        "validated_head_index": validated_head_index,
        "validated_head_doc_hash": validated_head_doc_hash,
        "validated_head_auth_status": validated_head_auth_status,
        "validated_head_root_authority_verified": validated_head_root,
        "explicit_selection": False,
        "root_doc_hash": root_doc_hash,
        "root_auth_status": None if root_document is None else root_document.auth_status,
        "root_authority_verified": (
            None if root_document is None else _resolved_root_authority_verified(root_document)
        ),
    }


def _build_trust_diagnostic(
    *,
    status: str,
    code: str | None,
    message: str,
    details: dict[str, object],
) -> TrustDiagnostic:
    return TrustDiagnostic(
        status=status,
        code=code,
        message=message,
        details=details,
    )


def _root_projection_trust_diagnostic(document: _DecodedMainDocument) -> TrustDiagnostic:
    if document.doc_hash is None:
        raise ValueError("root document is not fully decoded")
    root_authority_verified = _resolved_root_authority_verified(document)
    return _build_trust_diagnostic(
        status="ok",
        code=None,
        message="root backup authority verified",
        details={
            "stage": "projection",
            "trust_scope": "standalone_backup",
            "latest_head_index": 0,
            "latest_head_doc_hash": document.doc_hash.hex(),
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": 0,
            "validated_head_doc_hash": document.doc_hash.hex(),
            "validated_head_auth_status": document.auth_status,
            "validated_head_root_authority_verified": root_authority_verified,
            "explicit_selection": False,
            "root_doc_hash": document.doc_hash.hex(),
            "root_auth_status": document.auth_status,
            "root_authority_verified": root_authority_verified,
        },
    )


def _extension_only_refusal_diagnostic(document: _DecodedMainDocument) -> TrustDiagnostic:
    latest_head_index = None
    root_doc_hash = None
    if isinstance(document.decoded, ExtensionEnvelope):
        latest_head_index = document.decoded.header.index
        root_doc_hash = document.decoded.header.root_doc_hash.hex()
    return _build_trust_diagnostic(
        status="refused",
        code=api_codes.RECOVERY_HEAD_UNTRUSTED,
        message=(
            "latest supplied recovery head could not be trusted: extension preview requires "
            "the root backup to validate root authority"
        ),
        details={
            "stage": "replay",
            "trust_scope": "extension_only",
            "failure_stage": "authority_context",
            "failure_message": (
                "extension preview requires the root backup to validate root authority"
            ),
            "failure_head_index": latest_head_index,
            "failure_head_doc_hash": (
                None if document.doc_hash is None else document.doc_hash.hex()
            ),
            "failure_head_dir_name": None,
            "latest_head_index": latest_head_index,
            "latest_head_doc_hash": (
                None if document.doc_hash is None else document.doc_hash.hex()
            ),
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": None,
            "validated_head_doc_hash": None,
            "validated_head_auth_status": None,
            "validated_head_root_authority_verified": None,
            "explicit_selection": False,
            "root_doc_hash": root_doc_hash,
            "root_auth_status": None,
            "root_authority_verified": None,
            "auth_status": document.auth_status,
        },
    )


def _projection_refusal_diagnostic(
    *,
    root_document: _DecodedMainDocument | None,
    extension_documents: Sequence[_DecodedMainDocument],
    failure_stage: str,
    failure_message: str,
    code: str = api_codes.RECOVERY_HEAD_UNTRUSTED,
    failure_document: _DecodedMainDocument | None = None,
    validated_extensions: Sequence[tuple[_DecodedMainDocument, ExtensionEnvelope]] = (),
) -> TrustDiagnostic:
    details = _base_trust_details(
        root_document=root_document, extension_documents=extension_documents
    )
    (
        validated_head_index,
        validated_head_doc_hash,
        validated_head_auth_status,
        validated_head_root,
    ) = (
        _validated_chain_head_details(root_document, validated_extensions)
        if root_document is not None
        else (None, None, None, None)
    )
    details.update(
        {
            "stage": "authority" if code == api_codes.ROOT_AUTHORITY_MISMATCH else "replay",
            "trust_scope": "extension_chain" if extension_documents else "standalone_backup",
            "failure_stage": failure_stage,
            "failure_message": failure_message,
            "failure_head_index": details["latest_head_index"],
            "failure_head_doc_hash": details["latest_head_doc_hash"],
            "failure_head_dir_name": None,
            "validated_head_index": validated_head_index,
            "validated_head_doc_hash": validated_head_doc_hash,
            "validated_head_auth_status": validated_head_auth_status,
            "validated_head_root_authority_verified": validated_head_root,
        }
    )
    if failure_document is not None and failure_document.doc_hash is not None:
        details["failure_head_doc_hash"] = failure_document.doc_hash.hex()
    if failure_document is not None and isinstance(failure_document.decoded, ExtensionEnvelope):
        details["failure_head_index"] = failure_document.decoded.header.index
    if code == api_codes.ROOT_AUTHORITY_MISMATCH:
        message = failure_message
    else:
        message = f"latest supplied recovery head could not be trusted: {failure_message}"
    return _build_trust_diagnostic(
        status="refused",
        code=code,
        message=message,
        details=details,
    )


def _chain_projection_trust_diagnostic(
    *,
    root_document: _DecodedMainDocument,
    validated_extensions: Sequence[tuple[_DecodedMainDocument, ExtensionEnvelope]],
    latest_file_count: int,
) -> TrustDiagnostic:
    (
        validated_head_index,
        validated_head_doc_hash,
        validated_head_auth_status,
        validated_head_root,
    ) = _validated_chain_head_details(root_document, validated_extensions)
    return _build_trust_diagnostic(
        status="ok",
        code=None,
        message="latest supplied recovery head trusted",
        details={
            "stage": "replay",
            "trust_scope": "extension_chain",
            "latest_head_index": validated_head_index,
            "latest_head_doc_hash": validated_head_doc_hash,
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": validated_head_index,
            "validated_head_doc_hash": validated_head_doc_hash,
            "validated_head_auth_status": validated_head_auth_status,
            "validated_head_root_authority_verified": validated_head_root,
            "explicit_selection": False,
            "root_doc_hash": root_document.doc_hash.hex()
            if root_document.doc_hash is not None
            else None,
            "root_auth_status": root_document.auth_status,
            "root_authority_verified": _resolved_root_authority_verified(root_document),
            "root_auth_matches_embedded_authority": True,
            "extension_count": len(validated_extensions),
            "latest_logical_file_count": latest_file_count,
        },
    )


def _trust_diagnostic_payload(
    trust_diagnostic: TrustDiagnostic | None,
) -> dict[str, object] | None:
    if trust_diagnostic is None:
        return None
    return {
        "status": trust_diagnostic.status,
        "code": trust_diagnostic.code,
        "message": trust_diagnostic.message,
        "details": trust_diagnostic.details,
    }


def _projection_diagnostic_lines(trust_diagnostic: TrustDiagnostic | None) -> list[str]:
    if trust_diagnostic is None:
        return ["No projection diagnostics available."]

    details = trust_diagnostic.details
    lines = [f"Trust status: {trust_diagnostic.status}"]
    if trust_diagnostic.code is not None:
        lines.append(f"Trust code: {trust_diagnostic.code}")
    lines.append(f"Trust message: {trust_diagnostic.message}")

    if trust_diagnostic.status == "ok" and details.get("trust_scope") == "extension_chain":
        lines.extend(
            [
                "Reconstruction scope: full root-plus-extensions chain",
                "Authority model: root-derived via root backup",
                (
                    "Root backup AUTH matches embedded authority: "
                    f"{bool_text(bool(details.get('root_auth_matches_embedded_authority')))}"
                ),
                (
                    "Extension AUTH: verified against root authority for "
                    f"{_details_int(details, 'extension_count')} extension(s)"
                ),
                f"Chain extensions: {_details_int(details, 'extension_count')}",
                f"Latest logical files: {_details_int(details, 'latest_logical_file_count')}",
            ]
        )
    else:
        failure_stage = details.get("failure_stage")
        if failure_stage is not None:
            lines.append(f"Failure stage: {failure_stage}")
        failure_head_index = details.get("failure_head_index")
        if failure_head_index is not None:
            lines.append(f"Failure head index: {failure_head_index}")
        failure_head_doc_hash = details.get("failure_head_doc_hash")
        if failure_head_doc_hash is not None:
            lines.append(f"Failure head doc_hash: {failure_head_doc_hash}")

    latest_head_index = details.get("latest_head_index")
    latest_head_doc_hash = details.get("latest_head_doc_hash")
    if latest_head_index is None and latest_head_doc_hash is None:
        lines.append("Latest head: none")
    else:
        lines.append(f"Latest head: index={latest_head_index}, doc_hash={latest_head_doc_hash}")

    validated_head_index = details.get("validated_head_index")
    validated_head_doc_hash = details.get("validated_head_doc_hash")
    if validated_head_index is None and validated_head_doc_hash is None:
        lines.append("Validated head: none")
    else:
        lines.append(
            f"Validated head: index={validated_head_index}, doc_hash={validated_head_doc_hash}"
        )
        lines.append(
            "Validated head AUTH/root authority: "
            f"{details.get('validated_head_auth_status')}/"
            f"{details.get('validated_head_root_authority_verified')}"
        )

    root_auth_status = details.get("root_auth_status")
    if root_auth_status is not None:
        lines.append(f"Root AUTH status: {root_auth_status}")
    root_authority_verified = details.get("root_authority_verified")
    if root_authority_verified is not None:
        lines.append(f"Root authority verified: {bool_text(bool(root_authority_verified))}")
    return lines


def _details_int(details: Mapping[str, object], key: str, default: int = 0) -> int:
    value = details.get(key, default)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _diagnostics_trust_lines(
    trust_diagnostic: TrustDiagnostic,
    *,
    decryption_source: str | None,
    file_count: int,
) -> list[str]:
    lines = [
        f"Trust status: {trust_diagnostic.status}",
        f"Trust message: {trust_diagnostic.message}",
    ]
    if trust_diagnostic.code is not None:
        lines.append(f"Trust code: {trust_diagnostic.code}")
    if trust_diagnostic.status == "ok":
        lines.append(f"Document details decoded successfully with {file_count} available file(s).")
        if trust_diagnostic.details.get("trust_scope") == "extension_chain":
            lines.append(
                "Latest-state preview is reconstructed from the root backup "
                "plus validated extensions."
            )
    else:
        lines.append(f"Document decode failed: {trust_diagnostic.message}")
    if decryption_source is not None:
        lines.append(f"Document decryption source: {decryption_source}")
    return lines


def _inspect_chain_documents(
    root_document: _DecodedMainDocument,
    extension_documents: Sequence[_DecodedMainDocument],
) -> tuple[dict[str, object] | None, list[FileRecord], TrustDiagnostic]:
    if root_document.doc_hash is None or not isinstance(root_document.decoded, tuple):
        raise ValueError("root document is not fully decoded")

    manifest, payload = root_document.decoded
    root_sign_pub = derive_public_key(manifest.signing_seed) if manifest.signing_seed else None
    if root_sign_pub is None:
        raise ValueError("root signing authority is unavailable for extension chain validation")
    if root_document.auth_status != "verified" or root_document.auth_payload is None:
        trust_diagnostic = _projection_refusal_diagnostic(
            root_document=root_document,
            extension_documents=extension_documents,
            failure_stage="auth",
            failure_message=(
                f"root AUTH validation failed ({root_document.auth_status or 'missing'})"
            ),
        )
        return None, [], trust_diagnostic
    root_auth_matches_embedded = bool(
        hmac.compare_digest(root_document.auth_payload.sign_pub, root_sign_pub)
    )
    if not root_auth_matches_embedded:
        trust_diagnostic = _projection_refusal_diagnostic(
            root_document=root_document,
            extension_documents=extension_documents,
            failure_stage="root_authority",
            failure_message=(
                "embedded signing seed does not match the verified root AUTH authority"
            ),
            code=api_codes.ROOT_AUTHORITY_MISMATCH,
        )
        return None, [], trust_diagnostic

    sorted_extensions: list[tuple[_DecodedMainDocument, ExtensionEnvelope]] = []
    for document in sorted(
        extension_documents,
        key=lambda item: (
            item.decoded.header.index if isinstance(item.decoded, ExtensionEnvelope) else -1
        ),
    ):
        if document.doc_hash is None or not isinstance(document.decoded, ExtensionEnvelope):
            continue
        sorted_extensions.append((document, document.decoded))
    links: list[AuthenticatedExtensionChainLink] = []
    validated_extensions: list[tuple[_DecodedMainDocument, ExtensionEnvelope]] = []
    extension_root_authority_verified: dict[int, bool] = {}
    for document, envelope in sorted_extensions:
        if document.auth_status != "verified":
            trust_diagnostic = _projection_refusal_diagnostic(
                root_document=root_document,
                extension_documents=extension_documents,
                failure_stage="auth",
                failure_message=(
                    f"extension {envelope.header.index} AUTH validation failed "
                    f"({document.auth_status or 'missing'})"
                ),
                failure_document=document,
                validated_extensions=validated_extensions,
            )
            return None, [], trust_diagnostic
        if document.auth_payload is None or not hmac.compare_digest(
            document.auth_payload.sign_pub,
            root_sign_pub,
        ):
            trust_diagnostic = _projection_refusal_diagnostic(
                root_document=root_document,
                extension_documents=extension_documents,
                failure_stage="auth",
                failure_message=(
                    f"extension {envelope.header.index} AUTH does not match root authority"
                ),
                failure_document=document,
                validated_extensions=validated_extensions,
            )
            return None, [], trust_diagnostic
        extension_root_authority_verified[envelope.header.index] = True
        assert document.doc_hash is not None
        links.append(
            AuthenticatedExtensionChainLink(
                doc_hash=document.doc_hash,
                document=envelope,
                auth_payload=document.auth_payload,
                expected_sign_pub=root_sign_pub,
            )
        )
        validated_extensions.append((document, envelope))
    try:
        validate_authenticated_extension_chain(
            root_doc_hash=root_document.doc_hash,
            expected_sign_pub=root_sign_pub,
            extensions=links,
        )
    except Exception as exc:
        trust_diagnostic = _projection_refusal_diagnostic(
            root_document=root_document,
            extension_documents=extension_documents,
            failure_stage="validation",
            failure_message=str(exc),
            validated_extensions=validated_extensions,
        )
        return None, [], trust_diagnostic
    try:
        latest_state = reconstruct_authenticated_latest_logical_state(
            manifest,
            payload,
            root_doc_hash=root_document.doc_hash,
            expected_sign_pub=root_sign_pub,
            extensions=links,
        )
    except Exception as exc:
        trust_diagnostic = _projection_refusal_diagnostic(
            root_document=root_document,
            extension_documents=extension_documents,
            failure_stage="reconstruction",
            failure_message=str(exc),
            validated_extensions=validated_extensions,
        )
        return None, [], trust_diagnostic
    latest_files, file_records = _state_projection(
        [(item.path, item.size, item.sha256, item.mtime, item.data) for item in latest_state]
    )
    trust_diagnostic = _chain_projection_trust_diagnostic(
        root_document=root_document,
        validated_extensions=validated_extensions,
        latest_file_count=len(latest_files),
    )
    return (
        {
            "kind": "extension_chain",
            "root": {
                "doc_id": root_document.doc_id.hex(),
                "doc_hash": root_document.doc_hash.hex(),
                "format_version": manifest.format_version,
                "sealed": manifest.sealed,
                "input_origin": manifest.input_origin,
                "input_roots": list(manifest.input_roots),
                "payload_codec": manifest.payload_codec,
                "auth_status": root_document.auth_status,
                "root_authority_verified": root_auth_matches_embedded,
                "file_count": len(manifest.files),
            },
            "extensions": [
                {
                    "doc_id": document.doc_id.hex(),
                    "doc_hash": document.doc_hash.hex() if document.doc_hash is not None else None,
                    "index": envelope.header.index,
                    "parent_doc_hash": envelope.header.parent_doc_hash.hex(),
                    "root_doc_hash": envelope.header.root_doc_hash.hex(),
                    "input_origin": envelope.header.input_origin,
                    "input_roots": list(envelope.header.input_roots),
                    "file_count": len(envelope.files),
                    "chunk_count": len(envelope.chunks),
                    "auth_status": document.auth_status,
                    "root_authority_verified": extension_root_authority_verified[
                        envelope.header.index
                    ],
                }
                for document, envelope in sorted_extensions
            ],
            "latest_state": {
                "file_count": len(latest_files),
                "files": latest_files,
            },
        },
        file_records,
        trust_diagnostic,
    )


def _decode_main_documents(
    documents: Sequence[_DecodedMainDocument],
    *,
    passphrase: str | None,
) -> tuple[tuple[_DecodedMainDocument, ...], str | None]:
    if not passphrase:
        return tuple(documents), None

    decoded_documents: list[_DecodedMainDocument] = []
    for document in documents:
        if document.ciphertext is None:
            decoded_documents.append(document)
            continue
        try:
            plaintext = decrypt_bytes(document.ciphertext, passphrase=passphrase, debug=False)
            envelope_version, decoded = decode_any_envelope(plaintext)
            if envelope_version == 1 and isinstance(decoded, tuple):
                decoded_payload: tuple[EnvelopeManifest, bytes] | ExtensionEnvelope = cast(
                    tuple[EnvelopeManifest, bytes],
                    decoded,
                )
            elif envelope_version == 2 and isinstance(decoded, ExtensionEnvelope):
                decoded_payload = decoded
            else:
                raise ValueError(
                    f"unsupported decoded envelope shape for version {envelope_version}"
                )
            decoded_documents.append(
                _DecodedMainDocument(
                    doc_id=document.doc_id,
                    frame_count=document.frame_count,
                    ciphertext=document.ciphertext,
                    doc_hash=document.doc_hash,
                    reassembly_error=document.reassembly_error,
                    envelope_version=envelope_version,
                    document_kind="standalone_backup" if envelope_version == 1 else "extension",
                    decoded=decoded_payload,
                    decrypt_error=None,
                    auth_payload=document.auth_payload,
                    auth_status=document.auth_status,
                    root_authority_verified=document.root_authority_verified,
                )
            )
        except Exception as exc:
            decoded_documents.append(
                _DecodedMainDocument(
                    doc_id=document.doc_id,
                    frame_count=document.frame_count,
                    ciphertext=document.ciphertext,
                    doc_hash=document.doc_hash,
                    reassembly_error=document.reassembly_error,
                    decrypt_error=str(exc),
                    auth_payload=document.auth_payload,
                    auth_status=document.auth_status,
                    root_authority_verified=document.root_authority_verified,
                )
            )
    return tuple(decoded_documents), passphrase


def _project_decoded_documents(
    documents: Sequence[_DecodedMainDocument],
) -> tuple[dict[str, object] | None, list[FileRecord], TrustDiagnostic | None]:
    successful = [
        document
        for document in documents
        if document.decrypt_error is None
        and document.reassembly_error is None
        and document.decoded is not None
    ]
    if not successful:
        return None, [], None
    if len(successful) != len(documents):
        root_document = next(
            (
                document
                for document in successful
                if document.envelope_version == 1 and isinstance(document.decoded, tuple)
            ),
            None,
        )
        extension_documents = [
            document
            for document in successful
            if document.envelope_version == 2 and isinstance(document.decoded, ExtensionEnvelope)
        ]
        trust_diagnostic = _projection_refusal_diagnostic(
            root_document=root_document,
            extension_documents=extension_documents,
            failure_stage="decode",
            failure_message=(
                "some decoded documents failed reassembly or envelope decoding; "
                "refusing partial projection"
            ),
        )
        return None, [], trust_diagnostic

    root_documents = [
        document
        for document in successful
        if document.envelope_version == 1 and isinstance(document.decoded, tuple)
    ]
    extension_documents = [
        document
        for document in successful
        if document.envelope_version == 2 and isinstance(document.decoded, ExtensionEnvelope)
    ]

    if len(root_documents) == 1 and not extension_documents:
        return _project_single_root_document(root_documents[0])

    if not root_documents and len(extension_documents) == 1:
        return _project_single_extension_document(extension_documents[0])

    if len(root_documents) == 1 and extension_documents:
        return _inspect_chain_documents(root_documents[0], extension_documents)

    return _document_list_projection(documents), [], None


def _project_single_root_document(
    document: _DecodedMainDocument,
) -> tuple[dict[str, object] | None, list[FileRecord], TrustDiagnostic | None]:
    if document.auth_status != "verified":
        trust_diagnostic = _projection_refusal_diagnostic(
            root_document=document,
            extension_documents=(),
            failure_stage="auth",
            failure_message=(f"root AUTH validation failed ({document.auth_status or 'missing'})"),
        )
        return None, [], trust_diagnostic

    manifest, payload = cast(
        tuple[EnvelopeManifest, bytes],
        document.decoded,
    )
    if (
        manifest.signing_seed is not None
        and _resolved_root_authority_verified(document) is not True
    ):
        trust_diagnostic = _projection_refusal_diagnostic(
            root_document=document,
            extension_documents=(),
            failure_stage="root_authority",
            failure_message=(
                "embedded signing seed does not match the verified root AUTH authority"
            ),
            code=api_codes.ROOT_AUTHORITY_MISMATCH,
        )
        return None, [], trust_diagnostic

    extracted = extract_payloads(manifest, payload)
    projection, file_records = _manifest_projection(manifest, extracted)
    projection["kind"] = "standalone_backup"
    return projection, file_records, _root_projection_trust_diagnostic(document)


def _project_single_extension_document(
    document: _DecodedMainDocument,
) -> tuple[dict[str, object] | None, list[FileRecord], TrustDiagnostic | None]:
    if document.auth_status != "verified":
        trust_diagnostic = _projection_refusal_diagnostic(
            root_document=None,
            extension_documents=(document,),
            failure_stage="auth",
            failure_message=(
                f"extension AUTH validation failed ({document.auth_status or 'missing'})"
            ),
            failure_document=document,
        )
        return None, [], trust_diagnostic
    return None, [], _extension_only_refusal_diagnostic(document)


def _reassemble_main_documents(
    main_frames: Sequence[Frame],
    auth_frames: Sequence[Frame],
) -> tuple[_DecodedMainDocument, ...]:
    grouped: dict[bytes, list[Frame]] = {}
    for frame in main_frames:
        grouped.setdefault(frame.doc_id, []).append(frame)
    auth_by_doc_id: dict[bytes, list[Frame]] = {}
    for frame in auth_frames:
        auth_by_doc_id.setdefault(frame.doc_id, []).append(frame)

    documents: list[_DecodedMainDocument] = []
    for doc_id in sorted(grouped):
        frames = grouped[doc_id]
        try:
            ciphertext = reassemble_payload(
                frames,
                expected_doc_id=doc_id,
                expected_frame_type=FrameType.MAIN_DOCUMENT,
            )
            resolved_doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
            if resolved_doc_id != doc_id:
                raise ValueError("reassembled doc_id does not match MAIN frame doc_id")
            auth_payload: AuthPayload | None = None
            auth_status: str | None = None
            try:
                auth_payload, auth_status = resolve_auth_payload(
                    auth_by_doc_id.get(doc_id, []),
                    doc_id=doc_id,
                    doc_hash=doc_hash,
                    allow_unsigned=True,
                    require_auth=False,
                    quiet=True,
                )
            except Exception as exc:
                auth_status = f"invalid: {exc}"
            documents.append(
                _DecodedMainDocument(
                    doc_id=doc_id,
                    frame_count=len(frames),
                    ciphertext=ciphertext,
                    doc_hash=doc_hash,
                    reassembly_error=None,
                    auth_payload=auth_payload,
                    auth_status=auth_status,
                )
            )
        except Exception as exc:
            documents.append(
                _DecodedMainDocument(
                    doc_id=doc_id,
                    frame_count=len(frames),
                    ciphertext=None,
                    doc_hash=None,
                    reassembly_error=str(exc),
                )
            )
    return tuple(documents)


def _recover_secret_records(
    shard_frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
) -> tuple[tuple[RecoveredSecretRecord, ...], list[str], str | None]:
    grouped: dict[tuple[str, bytes, bytes], list[Frame]] = {}
    for frame in shard_frames:
        payload = decode_shard_payload(frame.data)
        grouped.setdefault((payload.key_type, payload.doc_hash, payload.sign_pub), []).append(frame)

    records: list[RecoveredSecretRecord] = []
    diagnostics: list[str] = []
    recovered_passphrase: str | None = None
    for (key_type, doc_hash, _sign_pub), frames in sorted(grouped.items()):
        secret_label = "passphrase" if key_type == KEY_TYPE_PASSPHRASE else "signing key"
        try:
            payloads = validated_shard_payloads_from_frames(
                list(frames),
                expected_doc_id=expected_doc_id,
                expected_doc_hash=expected_doc_hash,
                expected_sign_pub=None,
                allow_unsigned=False,
                key_type=key_type,
                secret_label=secret_label,
            )
            threshold = payloads[0].threshold
            if key_type == KEY_TYPE_PASSPHRASE:
                recovered = recover_passphrase(payloads)
                recovered_passphrase = recovered
                detail_text = (
                    f"Recovered passphrase:\n\n{recovered}\n\ndoc_hash: {doc_hash.hex()}\n"
                )
                export_text = recovered + "\n"
                summary = (
                    "Recovered passphrase from "
                    f"{len(payloads)} shard(s) at threshold {threshold} "
                    f"for doc_hash {doc_hash.hex()[:16]}."
                )
                export_name = "recovered_passphrase.txt"
            else:
                recovered_seed = recover_signing_seed(payloads)
                derived_pub = derive_public_key(recovered_seed)
                detail_text = (
                    "Recovered signing seed:\n\n"
                    f"seed_hex: {recovered_seed.hex()}\n"
                    f"derived_public_key: {derived_pub.hex()}\n"
                    f"doc_hash: {doc_hash.hex()}\n"
                )
                export_text = (
                    json.dumps(
                        {
                            "seed_hex": recovered_seed.hex(),
                            "derived_public_key": derived_pub.hex(),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                )
                summary = (
                    f"Recovered signing seed from {len(payloads)} shard(s) "
                    f"at threshold {threshold} for doc_hash {doc_hash.hex()[:16]}."
                )
                export_name = "recovered_signing_seed.json"
            diagnostics.append(f"{secret_label} shards: recoverable ({len(payloads)}/{threshold})")
            records.append(
                RecoveredSecretRecord(
                    label=secret_label,
                    status="recoverable",
                    summary=summary,
                    detail_text=detail_text,
                    export_name=export_name,
                    export_text=export_text,
                )
            )
        except InsufficientShardError as exc:
            diagnostics.append(
                f"{secret_label} shards: under quorum ({exc.provided_count}/{exc.threshold})"
            )
            records.append(
                RecoveredSecretRecord(
                    label=secret_label,
                    status="under quorum",
                    summary=(
                        f"Need {exc.threshold} {secret_label} shard(s); "
                        f"only {exc.provided_count} provided."
                    ),
                    detail_text=(
                        f"Under quorum for {secret_label} shards.\n"
                        f"Provided: {exc.provided_count}\n"
                        f"Threshold: {exc.threshold}\n"
                    ),
                    export_name=f"{secret_label.replace(' ', '_')}_status.txt",
                    export_text=(
                        f"status: under quorum\nprovided: {exc.provided_count}\n"
                        f"threshold: {exc.threshold}\n"
                    ),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive GUI path
            diagnostics.append(f"{secret_label} shards: invalid ({exc})")
            records.append(
                RecoveredSecretRecord(
                    label=secret_label,
                    status="invalid",
                    summary=f"{secret_label} shards are not recoverable.",
                    detail_text=f"{secret_label} shard validation failed:\n\n{exc}\n",
                    export_name=f"{secret_label.replace(' ', '_')}_status.txt",
                    export_text=f"status: invalid\nerror: {exc}\n",
                )
            )
    return tuple(records), diagnostics, recovered_passphrase


def _main_frame_diagnostics(main_frames: Sequence[Frame]) -> list[str]:
    if not main_frames:
        return ["No MAIN_DOCUMENT frames present."]
    grouped: dict[bytes, list[Frame]] = {}
    for frame in main_frames:
        grouped.setdefault(frame.doc_id, []).append(frame)
    lines: list[str] = []
    for doc_id in sorted(grouped):
        frames = grouped[doc_id]
        totals = sorted({frame.total for frame in frames})
        indices = sorted(frame.index for frame in frames)
        expected_total = frames[0].total
        missing = [index for index in range(expected_total) if index not in set(indices)]
        lines.extend(
            [
                "MAIN doc_id "
                f"{doc_id.hex()}: totals observed "
                f"{', '.join(str(total) for total in totals)}",
                "MAIN doc_id "
                f"{doc_id.hex()}: indices present "
                f"{', '.join(str(index) for index in indices)}",
            ]
        )
        if missing:
            lines.append(
                "MAIN doc_id "
                f"{doc_id.hex()}: indices missing "
                f"{', '.join(str(index) for index in missing)}"
            )
        else:
            lines.append(f"MAIN doc_id {doc_id.hex()}: indices missing none")
    return lines


def inspect_pasted_text(
    text: str,
    *,
    selected_mode: str,
    passphrase: str | None,
    source_label: str = "pasted input",
) -> InspectionResult:
    input_mode, parsed_frames = _parse_text_to_frames(text, selected_mode=selected_mode)
    warnings: list[str] = []
    deduped_frames = _dedupe_inspection_frames(parsed_frames)
    duplicate_count = len(parsed_frames) - len(deduped_frames)
    if duplicate_count:
        warnings.append(f"ignored {duplicate_count} duplicate frame(s) during analysis")

    main_frames = [frame for frame in deduped_frames if frame.frame_type == FrameType.MAIN_DOCUMENT]
    auth_frames = [frame for frame in deduped_frames if frame.frame_type == FrameType.AUTH]
    shard_frames = [frame for frame in deduped_frames if frame.frame_type == FrameType.KEY_DOCUMENT]

    normalized_payload_text = "\n".join(payload_lines_from_frames(deduped_frames))
    if normalized_payload_text:
        normalized_payload_text += "\n"
    fallback_text = combined_fallback_text(deduped_frames)

    main_documents = _reassemble_main_documents(main_frames, auth_frames)
    main_doc_hashes_by_doc_id = {
        document.doc_id: document.doc_hash
        for document in main_documents
        if document.doc_hash is not None
    }

    frame_records = tuple(
        _build_frame_record(frame, main_doc_hashes_by_doc_id=main_doc_hashes_by_doc_id)
        for frame in deduped_frames
    )

    successful_main_documents = [
        document for document in main_documents if document.doc_hash is not None
    ]
    expected_doc_id = (
        successful_main_documents[0].doc_id if len(successful_main_documents) == 1 else None
    )
    expected_doc_hash = (
        successful_main_documents[0].doc_hash if len(successful_main_documents) == 1 else None
    )

    recovered_secrets, shard_diagnostics, recovered_passphrase = _recover_secret_records(
        shard_frames,
        expected_doc_id=expected_doc_id,
        expected_doc_hash=expected_doc_hash,
    )

    document_text = (
        "No document details available. Provide a passphrase after MAIN frames reassemble.\n"
    )
    document_json_text: str | None = None
    projection_diagnostics_text = "No projection diagnostics available.\n"
    file_records: list[FileRecord] = []
    document_projection: dict[str, object] | None = None
    trust_diagnostic: TrustDiagnostic | None = None
    decryption_source: str | None = None
    decryption_passphrase = passphrase
    if decryption_passphrase:
        decryption_source = "manual passphrase"
    elif recovered_passphrase is not None:
        decryption_passphrase = recovered_passphrase
        decryption_source = "recovered passphrase shards"

    decoded_documents, _used_passphrase = _decode_main_documents(
        main_documents,
        passphrase=decryption_passphrase,
    )
    if decryption_passphrase:
        document_projection, file_records, trust_diagnostic = _project_decoded_documents(
            decoded_documents
        )
        if document_projection is not None:
            document_json_text = json_text(document_projection)
            document_text = document_json_text
        elif trust_diagnostic is not None:
            document_text = f"Document decode failed:\n{trust_diagnostic.message}\n"
        if trust_diagnostic is not None:
            projection_diagnostics_text = (
                "\n".join(_projection_diagnostic_lines(trust_diagnostic)) + "\n"
            )
    elif successful_main_documents:
        if len(successful_main_documents) == 1:
            document_text = (
                "MAIN frames reassembled. Add a passphrase to decrypt and inspect the document.\n"
            )
        else:
            document_text = (
                f"{len(successful_main_documents)} MAIN documents reassembled. "
                "Add a passphrase to decrypt and inspect them.\n"
            )
    elif main_documents:
        errors = [
            f"{document.doc_id.hex()}: {document.reassembly_error}"
            for document in main_documents
            if document.reassembly_error is not None
        ]
        document_text = "MAIN reassembly failed:\n" + "\n".join(errors) + "\n"

    distinct_doc_ids = ", ".join(sorted({frame.doc_id.hex() for frame in deduped_frames})) or "none"
    summary_lines = [
        f"Source: {source_label}",
        f"Input mode: {input_mode}",
        f"Frames parsed: {len(parsed_frames)}",
        f"Frames after dedupe: {len(deduped_frames)}",
        f"Main frames: {len(main_frames)}",
        f"Auth frames: {len(auth_frames)}",
        f"Shard frames: {len(shard_frames)}",
        f"Distinct doc_ids: {distinct_doc_ids}",
    ]
    if len(successful_main_documents) == 1:
        document = successful_main_documents[0]
        summary_lines.extend(
            [
                f"Reassembled ciphertext bytes: {len(document.ciphertext or b'')}",
                f"Reassembled doc_id: {document.doc_id.hex()}",
                "Reassembled doc_hash: "
                f"{document.doc_hash.hex() if document.doc_hash is not None else 'unknown'}",
            ]
        )
    elif successful_main_documents:
        summary_lines.append(f"Reassembled MAIN documents: {len(successful_main_documents)}")
    elif main_documents:
        summary_lines.append("MAIN reassembly: failed")
    if document_projection is not None:
        projection_kind = str(document_projection.get("kind"))
        if projection_kind == "standalone_backup":
            summary_lines.extend(
                [
                    f"Manifest format_version: {document_projection['format_version']}",
                    f"Manifest sealed: {bool_text(bool(document_projection['sealed']))}",
                    f"Manifest input_origin: {document_projection['input_origin']}",
                    f"Manifest payload_codec: {document_projection['payload_codec']}",
                    f"Manifest files: {len(file_records)}",
                ]
            )
        elif projection_kind == "extension_chain":
            chain_extensions = cast(list[object], document_projection.get("extensions", []))
            summary_lines.extend(
                [
                    "Decoded document kind: extension_chain",
                    f"Chain extensions: {len(chain_extensions)}",
                    f"Latest logical files: {len(file_records)}",
                ]
            )
        elif projection_kind == "documents":
            document_items = cast(list[object], document_projection.get("documents", []))
            summary_lines.append(f"Decoded documents: {len(document_items)}")
        if decryption_source is not None:
            summary_lines.append(f"Decrypted via: {decryption_source}")
    elif trust_diagnostic is not None:
        summary_lines.append(f"Decryption: failed ({trust_diagnostic.message})")
    for secret in recovered_secrets:
        summary_lines.append(f"Recovered {secret.label}: {secret.status}")
    if warnings:
        summary_lines.append(f"Warnings: {len(warnings)}")

    diagnostics_lines = [
        f"Source: {source_label}",
        *[f"Warning: {warning}" for warning in warnings],
        *_main_frame_diagnostics(main_frames),
    ]
    if auth_frames:
        for frame in auth_frames:
            payload = decode_auth_payload(frame.data)
            signature_ok = verify_auth(
                payload.doc_hash,
                sign_pub=payload.sign_pub,
                signature=payload.signature,
            )
            match_text = "unknown"
            matching_doc_hash = main_doc_hashes_by_doc_id.get(frame.doc_id)
            if matching_doc_hash is not None:
                match_text = (
                    "yes" if hmac.compare_digest(payload.doc_hash, matching_doc_hash) else "no"
                )
            diagnostics_lines.append(
                "AUTH payload: "
                f"signature_valid={bool_text(signature_ok)}, "
                f"matches_main_doc_hash={match_text}, sign_pub={payload.sign_pub.hex()}"
            )
    else:
        diagnostics_lines.append("No AUTH frames present.")
    if shard_diagnostics:
        diagnostics_lines.extend(shard_diagnostics)
    else:
        diagnostics_lines.append("No shard frames present.")
    if trust_diagnostic is not None:
        diagnostics_lines.extend(
            _diagnostics_trust_lines(
                trust_diagnostic,
                decryption_source=decryption_source,
                file_count=len(file_records),
            )
        )
    elif document_projection is not None and decryption_source is not None:
        diagnostics_lines.append(f"Document decryption source: {decryption_source}")

    report = {
        "source_label": source_label,
        "input_mode": input_mode,
        "parsed_frame_count": len(parsed_frames),
        "deduped_frame_count": len(deduped_frames),
        "warnings": warnings,
        "summary_lines": summary_lines,
        "diagnostics_lines": diagnostics_lines,
        "documents": [
            {
                "doc_id": document.doc_id.hex(),
                "frame_count": document.frame_count,
                "doc_hash": None if document.doc_hash is None else document.doc_hash.hex(),
                "ciphertext_bytes": (
                    None if document.ciphertext is None else len(document.ciphertext)
                ),
                "reassembly_error": document.reassembly_error,
                "envelope_version": document.envelope_version,
                "document_kind": document.document_kind,
                "decrypt_error": document.decrypt_error,
            }
            for document in decoded_documents
        ],
        "frames": [record.detail for record in frame_records],
        "document": document_projection,
        "trust_diagnostic": _trust_diagnostic_payload(trust_diagnostic),
        "decryption_source": decryption_source,
        "files": [
            {
                "path": record.path,
                "size": record.size,
                "sha256": record.sha256,
                "preview_kind": record.preview_kind,
                "preview": record.preview,
            }
            for record in file_records
        ],
        "recovered_secrets": [
            {
                "label": record.label,
                "status": record.status,
                "summary": record.summary,
            }
            for record in recovered_secrets
        ],
    }
    return InspectionResult(
        source_label=source_label,
        input_mode=input_mode,
        parsed_frame_count=len(parsed_frames),
        deduped_frame_count=len(deduped_frames),
        warnings=tuple(warnings),
        summary_text="\n".join(summary_lines) + "\n",
        diagnostics_text="\n".join(diagnostics_lines) + "\n",
        normalized_payload_text=normalized_payload_text,
        combined_fallback_text=fallback_text,
        document_text=document_text,
        document_json_text=document_json_text,
        projection_diagnostics_text=projection_diagnostics_text,
        frame_records=frame_records,
        files=tuple(file_records),
        recovered_secrets=recovered_secrets,
        trust_diagnostic=trust_diagnostic,
        report_json=json_text(report),
    )


def batch_entry_from_result(
    *,
    source_label: str,
    source_path: str | None,
    result: InspectionResult | None,
    error: Exception | None,
) -> BatchReportEntry:
    if error is not None:
        return BatchReportEntry(
            source_label=source_label,
            source_path=source_path,
            frame_count=0,
            doc_ids=(),
            frame_types=(),
            warnings=(),
            error=str(error),
        )
    assert result is not None
    doc_ids = tuple(sorted({record.frame.doc_id.hex() for record in result.frame_records}))
    frame_types = tuple(
        sorted({frame_type_name(record.frame.frame_type) for record in result.frame_records})
    )
    return BatchReportEntry(
        source_label=source_label,
        source_path=source_path,
        frame_count=result.deduped_frame_count,
        doc_ids=doc_ids,
        frame_types=frame_types,
        warnings=result.warnings,
        error=None,
    )


def build_batch_report(entries: Sequence[BatchReportEntry]) -> tuple[str, str]:
    lines = [f"Batch entries: {len(entries)}"]
    report_items: list[dict[str, object]] = []
    for entry in entries:
        label = entry.source_path or entry.source_label
        if entry.error is not None:
            lines.append(f"- {label}: ERROR - {entry.error}")
        else:
            doc_ids = ", ".join(entry.doc_ids) if entry.doc_ids else "none"
            frame_types = ", ".join(entry.frame_types) if entry.frame_types else "none"
            warning_suffix = f"; warnings={len(entry.warnings)}" if entry.warnings else ""
            lines.append(
                f"- {label}: frames={entry.frame_count}; doc_ids={doc_ids}; "
                f"types={frame_types}{warning_suffix}"
            )
        report_items.append(
            {
                "source_label": entry.source_label,
                "source_path": entry.source_path,
                "frame_count": entry.frame_count,
                "doc_ids": list(entry.doc_ids),
                "frame_types": list(entry.frame_types),
                "warnings": list(entry.warnings),
                "error": entry.error,
            }
        )
    return "\n".join(lines) + "\n", json_text({"entries": report_items})


__all__ = ["batch_entry_from_result", "build_batch_report", "inspect_pasted_text"]
