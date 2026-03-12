from __future__ import annotations

import json
import string
from pathlib import Path
from typing import Any

from ethernity.encoding.cbor import loads_canonical
from ethernity.encoding.framing import Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import QR_PAYLOAD_CODEC_BASE64, encode_qr_payload
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.render.fallback_text import format_zbase32_lines

from .bootstrap import SRC_ROOT as _SRC_ROOT  # noqa: F401
from .constants import (
    DEFAULT_FALLBACK_GROUP_SIZE,
    DEFAULT_FALLBACK_LINE_LENGTH,
    FRAME_TYPE_LABELS,
    RAW_PREVIEW_LIMIT,
    TEXT_PREVIEW_LIMIT,
)


def hex_or_none(data: bytes | None) -> str | None:
    return None if data is None else data.hex()


def frame_type_name(frame_type: int) -> str:
    return FRAME_TYPE_LABELS.get(int(frame_type), f"UNKNOWN({frame_type})")


def bool_text(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def json_ready(value: object) -> object:
    if isinstance(value, bytes):
        return {"hex": value.hex(), "bytes": len(value)}
    if isinstance(value, bytearray):
        data = bytes(value)
        return {"hex": data.hex(), "bytes": len(data)}
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def json_text(value: object) -> str:
    return json.dumps(json_ready(value), indent=2, sort_keys=True) + "\n"


def preview_bytes(data: bytes, *, limit: int = RAW_PREVIEW_LIMIT) -> str:
    trimmed = data[:limit]
    text = trimmed.hex()
    if len(data) > limit:
        return f"{text}... ({len(data)} bytes total)"
    return text


def hex_ascii_dump(data: bytes, *, width: int = 16) -> str:
    if not data:
        return "<empty>\n"
    lines: list[str] = []
    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]
        hex_part = " ".join(f"{byte:02x}" for byte in chunk)
        ascii_part = "".join(
            chr(byte) if chr(byte) in string.printable[:-5] else "." for byte in chunk
        )
        lines.append(f"{offset:08x}  {hex_part:<{width * 3 - 1}}  |{ascii_part}|")
    return "\n".join(lines) + "\n"


def preview_file_data(data: bytes, *, path: str) -> tuple[str, str]:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        return "binary", hex_ascii_dump(data)

    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        try:
            return "json", json.dumps(json.loads(decoded), indent=2, sort_keys=True) + "\n"
        except json.JSONDecodeError:
            pass

    if any(ord(ch) < 9 or (13 < ord(ch) < 32) for ch in decoded):
        return "binary", hex_ascii_dump(data)

    preview = decoded[:TEXT_PREVIEW_LIMIT]
    if len(decoded) > TEXT_PREVIEW_LIMIT:
        preview += "\n..."
    return "text", preview


def frame_payload_text(frame: Frame) -> str:
    encoded = encode_qr_payload(encode_frame(frame), codec=QR_PAYLOAD_CODEC_BASE64)
    return (encoded.decode("ascii") if isinstance(encoded, bytes) else encoded) + "\n"


def payload_lines_from_frames(frames: list[Frame] | tuple[Frame, ...]) -> list[str]:
    return [frame_payload_text(frame).strip() for frame in frames]


def frame_fallback_lines(frame: Frame) -> list[str]:
    return format_zbase32_lines(
        encode_zbase32(encode_frame(frame)),
        group_size=DEFAULT_FALLBACK_GROUP_SIZE,
        line_length=DEFAULT_FALLBACK_LINE_LENGTH,
        line_count=None,
    )


def frame_fallback_text(frame: Frame) -> str:
    return "\n".join(frame_fallback_lines(frame)) + "\n"


def combined_fallback_text(frames: list[Frame] | tuple[Frame, ...]) -> str:
    main_frames = [frame for frame in frames if frame.frame_type == FrameType.MAIN_DOCUMENT]
    auth_frames = [frame for frame in frames if frame.frame_type == FrameType.AUTH]
    shard_frames = [frame for frame in frames if frame.frame_type == FrameType.KEY_DOCUMENT]

    lines: list[str] = []
    for frame in main_frames:
        lines.append("MAIN FRAME")
        lines.extend(frame_fallback_lines(frame))
        lines.append("")
    for frame in auth_frames:
        lines.append("AUTH FRAME")
        lines.extend(frame_fallback_lines(frame))
        lines.append("")
    for index, frame in enumerate(shard_frames, start=1):
        lines.append(f"SHARD FRAME {index}")
        lines.extend(frame_fallback_lines(frame))
        lines.append("")
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def frame_raw_text(frame: Frame) -> str:
    encoded = encode_frame(frame)
    parts = [
        f"frame_type: {frame_type_name(frame.frame_type)}",
        f"doc_id: {frame.doc_id.hex()}",
        f"index: {frame.index}",
        f"total: {frame.total}",
        f"frame_data_bytes: {len(frame.data)}",
        f"encoded_frame_bytes: {len(encoded)}",
        "",
        "encoded_frame:",
        hex_ascii_dump(encoded).rstrip(),
        "",
        "frame_data:",
        hex_ascii_dump(frame.data).rstrip(),
    ]
    return "\n".join(parts) + "\n"


def frame_cbor_text(frame: Frame) -> str:
    if frame.frame_type == FrameType.MAIN_DOCUMENT:
        return "MAIN_DOCUMENT frame data is ciphertext, not CBOR.\n"
    decoded: Any = loads_canonical(frame.data, label="frame payload")
    return json_text(decoded)


__all__ = [
    "bool_text",
    "combined_fallback_text",
    "frame_cbor_text",
    "frame_fallback_text",
    "frame_payload_text",
    "frame_raw_text",
    "frame_type_name",
    "hex_or_none",
    "json_text",
    "payload_lines_from_frames",
    "preview_bytes",
    "preview_file_data",
]
