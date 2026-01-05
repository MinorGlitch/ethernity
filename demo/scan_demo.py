#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from ethernity.crypto import decrypt_bytes, encrypt_bytes_with_passphrase
from ethernity.encoding.chunking import DEFAULT_CHUNK_SIZE, chunk_payload, reassemble_payload
from ethernity.formats.compression import wrap_payload, unwrap_payload
from ethernity.config import DEFAULT_PAPER_SIZE, load_app_config
from ethernity.formats.envelope_codec import (
    build_single_file_manifest,
    decode_envelope,
    encode_envelope,
)
from ethernity.encoding.framing import FrameType, decode_frame, encode_frame
from ethernity.render import RenderInputs, render_frames_to_pdf
from ethernity.encoding.qr_payloads import decode_qr_payload, encode_qr_payload, normalize_qr_payload_encoding
from ethernity.qr.scan import QrScanError, scan_qr_payloads


def _context_int(context: dict[str, object], key: str, default: int) -> int:
    value = context.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return int(value)
    return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan demo: render QR PDF then recover it.")
    parser.add_argument("--config", help="Path to a TOML config file.")
    parser.add_argument("--paper", choices=["A4", "LETTER"], help="Paper size preset.")
    parser.add_argument("--output-dir", help="Directory for demo outputs.")
    args = parser.parse_args()

    config = load_app_config(args.config, paper_size=args.paper or DEFAULT_PAPER_SIZE)

    max_cols = _context_int(config.context, "max_cols", 3)
    max_rows = _context_int(config.context, "max_rows", 3)
    grid_total = max_cols * max_rows
    if grid_total <= 0:
        raise RuntimeError("invalid grid size")

    payload, ciphertext, passphrase, frames = _fit_payload_to_grid(
        grid_total,
        compression=config.compression,
    )
    doc_id = hashlib.blake2b(ciphertext, digest_size=16).digest()
    frames = chunk_payload(ciphertext, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT)
    qr_frames = frames

    output_dir = Path(args.output_dir or f"scan-demo-{doc_id.hex()}")
    output_dir.mkdir(parents=True, exist_ok=False)
    qr_path = output_dir / "qr_document.pdf"
    recovered_path = output_dir / "recovered_payload.bin"

    context = dict(config.context)
    context["title"] = "Scan Demo"
    context["subtitle"] = "QR Document"
    context["doc_id"] = doc_id.hex()
    payload_encoding = normalize_qr_payload_encoding(config.qr_payload_encoding)
    qr_payloads = [encode_qr_payload(encode_frame(frame), payload_encoding) for frame in qr_frames]
    render_frames_to_pdf(
        RenderInputs(
            frames=qr_frames,
            template_path=config.template_path,
            output_path=qr_path,
            context=context,
            qr_config=config.qr_config,
            qr_payloads=qr_payloads,
            render_fallback=False,
        )
    )

    try:
        payloads = scan_qr_payloads([qr_path])
    except QrScanError as exc:
        raise RuntimeError(str(exc)) from exc

    decoded_payloads = [decode_qr_payload(payload, payload_encoding) for payload in payloads]
    scanned_frames = [decode_frame(payload) for payload in decoded_payloads]
    scanned_frames = _dedupe_frames(scanned_frames)
    recovered_ciphertext = reassemble_payload(scanned_frames)

    recovered_envelope = decrypt_bytes(recovered_ciphertext, passphrase=passphrase)
    envelope, _compression_info = unwrap_payload(recovered_envelope)
    _manifest, recovered_payload = decode_envelope(envelope)
    recovered_path.write_bytes(recovered_payload)

    if recovered_payload != payload:
        raise RuntimeError("recovered payload mismatch")

    print("Scan demo succeeded.")
    print(f"- QR PDF: {qr_path}")
    print(f"- Recovered payload: {recovered_path}")
    print(f"- Passphrase: {passphrase}")
    return 0


def _dedupe_frames(frames):
    seen = {}
    deduped = []
    for frame in frames:
        key = (int(frame.frame_type), int(frame.index), frame.doc_id)
        existing = seen.get(key)
        if existing:
            if existing.data != frame.data or existing.total != frame.total:
                raise RuntimeError("conflicting duplicate frames detected")
            continue
        seen[key] = frame
        deduped.append(frame)
    return deduped


def _fit_payload_to_grid(grid_total: int, *, compression):
    base_payload = b"Scan demo payload.\n" * 200
    max_payload_len = max(1, grid_total * DEFAULT_CHUNK_SIZE)
    payload_len = max_payload_len
    last_result = None
    for _ in range(12):
        payload = base_payload[:payload_len]
        manifest = build_single_file_manifest("scan-demo.bin", payload)
        envelope = encode_envelope(payload, manifest)
        wrapped, _compression_info = wrap_payload(envelope, compression)
        ciphertext, passphrase = encrypt_bytes_with_passphrase(wrapped, passphrase=None)
        if not passphrase:
            raise RuntimeError("age did not return a passphrase")
        doc_id = hashlib.blake2b(ciphertext, digest_size=16).digest()
        frames = chunk_payload(ciphertext, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT)
        last_result = (payload, ciphertext, passphrase, frames)
        if len(frames) <= grid_total:
            return last_result
        payload_len = max(1, payload_len - DEFAULT_CHUNK_SIZE // 2)

    if last_result is None:
        raise RuntimeError("failed to generate demo payload")
    return last_result


if __name__ == "__main__":
    raise SystemExit(main())
