from __future__ import annotations

import hmac
import json
from collections.abc import Sequence

from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    _validated_shard_payloads_from_frames,
)
from ethernity.cli.shared.crypto import _doc_id_and_hash_from_ciphertext
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
    decode_auth_payload,
    derive_public_key,
    verify_auth,
    verify_shard,
)
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import Frame, FrameType
from ethernity.formats.envelope_codec import decode_envelope, extract_payloads
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile

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
)


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


def _build_frame_record(frame: Frame, *, main_doc_hash: bytes | None) -> FrameRecord:
    detail = _frame_detail(frame, main_doc_hash=main_doc_hash)
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


def _recover_secret_records(
    shard_frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes | None,
) -> tuple[tuple[RecoveredSecretRecord, ...], list[str], str | None]:
    grouped: dict[str, list[Frame]] = {}
    for frame in shard_frames:
        payload = decode_shard_payload(frame.data)
        grouped.setdefault(payload.key_type, []).append(frame)

    records: list[RecoveredSecretRecord] = []
    diagnostics: list[str] = []
    recovered_passphrase: str | None = None
    for key_type, frames in sorted(grouped.items()):
        secret_label = "passphrase" if key_type == KEY_TYPE_PASSPHRASE else "signing key"
        try:
            payloads = _validated_shard_payloads_from_frames(
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
                detail_text = f"Recovered passphrase:\n\n{recovered}\n"
                export_text = recovered + "\n"
                summary = (
                    f"Recovered passphrase from {len(payloads)} shard(s) at threshold {threshold}."
                )
                export_name = "recovered_passphrase.txt"
            else:
                recovered_seed = recover_signing_seed(payloads)
                derived_pub = derive_public_key(recovered_seed)
                detail_text = (
                    "Recovered signing seed:\n\n"
                    f"seed_hex: {recovered_seed.hex()}\n"
                    f"derived_public_key: {derived_pub.hex()}\n"
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
                    f"at threshold {threshold}."
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
    totals = sorted({frame.total for frame in main_frames})
    indices = sorted(frame.index for frame in main_frames)
    expected_total = main_frames[0].total
    missing = [index for index in range(expected_total) if index not in set(indices)]
    lines = [
        f"MAIN frame totals observed: {', '.join(str(total) for total in totals)}",
        f"MAIN frame indices present: {', '.join(str(index) for index in indices)}",
    ]
    if missing:
        lines.append(f"MAIN frame indices missing: {', '.join(str(index) for index in missing)}")
    else:
        lines.append("MAIN frame indices missing: none")
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

    ciphertext: bytes | None = None
    doc_id: bytes | None = None
    doc_hash: bytes | None = None
    main_error: str | None = None
    if main_frames:
        try:
            ciphertext = reassemble_payload(
                main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT
            )
            doc_id, doc_hash = _doc_id_and_hash_from_ciphertext(ciphertext)
        except Exception as exc:
            main_error = str(exc)

    frame_records = tuple(
        _build_frame_record(frame, main_doc_hash=doc_hash) for frame in deduped_frames
    )

    recovered_secrets, shard_diagnostics, recovered_passphrase = _recover_secret_records(
        shard_frames,
        expected_doc_id=doc_id,
        expected_doc_hash=doc_hash,
    )

    manifest_text = "No manifest available. Provide a passphrase after MAIN frames reassemble.\n"
    manifest_json_text: str | None = None
    file_records: list[FileRecord] = []
    manifest_projection: dict[str, object] | None = None
    decrypt_error: str | None = None
    decryption_source: str | None = None
    decryption_passphrase = passphrase
    if decryption_passphrase:
        decryption_source = "manual passphrase"
    elif recovered_passphrase is not None:
        decryption_passphrase = recovered_passphrase
        decryption_source = "recovered passphrase shards"

    if ciphertext is not None and decryption_passphrase:
        try:
            plaintext = decrypt_bytes(ciphertext, passphrase=decryption_passphrase, debug=False)
            manifest, payload = decode_envelope(plaintext)
            extracted = extract_payloads(manifest, payload)
            manifest_projection, file_records = _manifest_projection(manifest, extracted)
            manifest_json_text = json_text(manifest_projection)
            manifest_text = manifest_json_text
        except Exception as exc:
            decrypt_error = str(exc)
            manifest_text = f"Decryption or manifest decode failed:\n{exc}\n"
    elif ciphertext is not None:
        manifest_text = (
            "MAIN frames reassembled. Add a passphrase to decrypt and inspect the manifest.\n"
        )
    elif main_error is not None:
        manifest_text = f"MAIN reassembly failed:\n{main_error}\n"

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
    if ciphertext is not None and doc_id is not None and doc_hash is not None:
        summary_lines.extend(
            [
                f"Reassembled ciphertext bytes: {len(ciphertext)}",
                f"Reassembled doc_id: {doc_id.hex()}",
                f"Reassembled doc_hash: {doc_hash.hex()}",
            ]
        )
    elif main_error is not None:
        summary_lines.append(f"MAIN reassembly: failed ({main_error})")
    if manifest_projection is not None:
        summary_lines.extend(
            [
                f"Manifest format_version: {manifest_projection['format_version']}",
                f"Manifest sealed: {bool_text(bool(manifest_projection['sealed']))}",
                f"Manifest input_origin: {manifest_projection['input_origin']}",
                f"Manifest payload_codec: {manifest_projection['payload_codec']}",
                f"Manifest files: {len(file_records)}",
            ]
        )
        if decryption_source is not None:
            summary_lines.append(f"Decrypted via: {decryption_source}")
    elif decrypt_error is not None:
        summary_lines.append(f"Decryption: failed ({decrypt_error})")
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
            if doc_hash is not None:
                match_text = "yes" if hmac.compare_digest(payload.doc_hash, doc_hash) else "no"
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
    if manifest_projection is not None:
        diagnostics_lines.append(
            f"Manifest decoded successfully with {len(file_records)} extracted file(s)."
        )
        if decryption_source is not None:
            diagnostics_lines.append(f"Manifest decryption source: {decryption_source}")
    elif decrypt_error is not None:
        diagnostics_lines.append(f"Manifest decode failed: {decrypt_error}")

    report = {
        "source_label": source_label,
        "input_mode": input_mode,
        "parsed_frame_count": len(parsed_frames),
        "deduped_frame_count": len(deduped_frames),
        "warnings": warnings,
        "summary_lines": summary_lines,
        "diagnostics_lines": diagnostics_lines,
        "reassembled": {
            "doc_id": hex_or_none(doc_id),
            "doc_hash": hex_or_none(doc_hash),
            "ciphertext_bytes": None if ciphertext is None else len(ciphertext),
            "error": main_error,
        },
        "frames": [record.detail for record in frame_records],
        "manifest": manifest_projection,
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
        manifest_text=manifest_text,
        manifest_json_text=manifest_json_text,
        frame_records=frame_records,
        files=tuple(file_records),
        recovered_secrets=recovered_secrets,
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
