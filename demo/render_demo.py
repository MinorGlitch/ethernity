#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from ethernity.chunking import DEFAULT_CHUNK_SIZE, chunk_payload
from ethernity.config import load_app_config
from ethernity.framing import FrameType, encode_frame
from ethernity.pdf_render import RenderInputs, render_frames_to_pdf
from ethernity.qr_payloads import encode_qr_payload, normalize_qr_payload_encoding


def _context_int(context: dict[str, object], key: str, default: int) -> int:
    value = context.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return int(value)
    return default


def main(config_path: str | Path | None = None, paper_size: str | None = None) -> None:
    config = load_app_config(config_path, paper_size=paper_size)

    max_cols = _context_int(config.context, "max_cols", 3)
    max_rows = _context_int(config.context, "max_rows", 3)
    target_frames = max_cols * max_rows
    payload_len = max(1, target_frames) * DEFAULT_CHUNK_SIZE
    line = b"Demo data for PDF rendering.\n"
    payload = (line * ((payload_len // len(line)) + 1))[:payload_len]
    doc_id = b"\x42" * 16
    frames = chunk_payload(payload, doc_id=doc_id, frame_type=FrameType.MAIN_DOCUMENT)
    payload_encoding = normalize_qr_payload_encoding(config.qr_payload_encoding)
    qr_payloads = [encode_qr_payload(encode_frame(frame), payload_encoding) for frame in frames]

    qr_output = Path("render_demo_qr.pdf")
    qr_inputs = RenderInputs(
        frames=frames,
        template_path=config.template_path,
        output_path=qr_output,
        context=config.context,
        qr_config=config.qr_config,
        qr_payloads=qr_payloads,
        render_fallback=False,
    )
    render_frames_to_pdf(qr_inputs)

    recovery_output = Path("render_demo_recovery.pdf")
    recovery_context = dict(config.context)
    recovery_context.setdefault("recovery_title", "Recovery Document")
    recovery_context.setdefault("recovery_subtitle", "Keys + Text Fallback")
    recovery_context.setdefault(
        "recovery_instructions",
        [
            "This document contains recovery keys and full text fallback.",
            "Keep it separate from the QR document.",
        ],
    )
    recovery_inputs = RenderInputs(
        frames=frames,
        template_path=config.recovery_template_path,
        output_path=recovery_output,
        context=recovery_context,
        qr_config=config.qr_config,
        fallback_payload=payload,
        render_qr=False,
        key_lines=["Demo Key:", "example-value"],
    )
    render_frames_to_pdf(recovery_inputs)

    print(f"Wrote {qr_output}")
    print(f"Wrote {recovery_output}")


if __name__ == "__main__":
    main()
