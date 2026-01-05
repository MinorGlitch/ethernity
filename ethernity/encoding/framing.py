#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import zlib

from .varint import decode_uvarint as _decode_uvarint
from .varint import encode_uvarint as _encode_uvarint

MAGIC = b"AP"
VERSION = 1
DOC_ID_LEN = 16
CRC_LEN = 4


class FrameType(IntEnum):
    MAIN_DOCUMENT = 0x44  # "D"
    KEY_DOCUMENT = 0x4B   # "K"
    CHECKSUM = 0x43       # "C"
    MANIFEST = 0x4D       # "M"
    AUTH = 0x41           # "A"


@dataclass(frozen=True)
class Frame:
    version: int
    frame_type: int
    doc_id: bytes
    index: int
    total: int
    data: bytes


def encode_frame(frame: Frame) -> bytes:
    _validate_frame(frame)

    parts: list[bytes] = [
        MAGIC,
        _encode_uvarint(frame.version),
        bytes([frame.frame_type]),
        frame.doc_id,
        _encode_uvarint(frame.index),
        _encode_uvarint(frame.total),
        _encode_uvarint(len(frame.data)),
        frame.data,
    ]
    body = b"".join(parts)
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return body + crc.to_bytes(CRC_LEN, "big")


def decode_frame(payload: bytes) -> Frame:
    if len(payload) < len(MAGIC) + CRC_LEN:
        raise ValueError("frame too short")

    idx = 0
    if payload[: len(MAGIC)] != MAGIC:
        raise ValueError("bad magic")
    idx += len(MAGIC)

    version, idx = _decode_uvarint(payload, idx)
    if idx >= len(payload):
        raise ValueError("missing frame type")

    frame_type = payload[idx]
    idx += 1

    if idx + DOC_ID_LEN > len(payload):
        raise ValueError("missing doc_id")
    doc_id = payload[idx : idx + DOC_ID_LEN]
    idx += DOC_ID_LEN

    index, idx = _decode_uvarint(payload, idx)
    total, idx = _decode_uvarint(payload, idx)
    data_len, idx = _decode_uvarint(payload, idx)

    if idx + data_len + CRC_LEN != len(payload):
        raise ValueError("frame length mismatch")

    data = payload[idx : idx + data_len]
    idx += data_len

    crc_expected = int.from_bytes(payload[idx : idx + CRC_LEN], "big")
    crc_actual = zlib.crc32(payload[: idx]) & 0xFFFFFFFF
    if crc_expected != crc_actual:
        raise ValueError("crc mismatch")

    frame = Frame(
        version=version,
        frame_type=frame_type,
        doc_id=doc_id,
        index=index,
        total=total,
        data=data,
    )
    _validate_frame(frame, allow_empty=False)
    return frame


def _validate_frame(frame: Frame, *, allow_empty: bool = True) -> None:
    if frame.version < 0:
        raise ValueError("version must be non-negative")
    if not allow_empty and frame.total <= 0:
        raise ValueError("total must be positive")
    if frame.total < 0:
        raise ValueError("total must be non-negative")
    if frame.index < 0:
        raise ValueError("index must be non-negative")
    if frame.total and frame.index >= frame.total:
        raise ValueError("index must be < total")
    if len(frame.doc_id) != DOC_ID_LEN:
        raise ValueError(f"doc_id must be {DOC_ID_LEN} bytes")
    if not allow_empty and len(frame.data) == 0:
        raise ValueError("data cannot be empty")

