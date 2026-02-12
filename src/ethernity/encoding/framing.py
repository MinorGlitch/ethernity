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

from __future__ import annotations

import zlib
from dataclasses import dataclass
from enum import IntEnum

from ..core.bounds import (
    MAX_AUTH_CBOR_BYTES,
    MAX_MAIN_FRAME_DATA_BYTES,
    MAX_MAIN_FRAME_TOTAL,
    MAX_SHARD_CBOR_BYTES,
)
from .varint import decode_uvarint as _decode_uvarint, encode_uvarint as _encode_uvarint

MAGIC = b"AP"
VERSION = 1
DOC_ID_LEN = 8
CRC_LEN = 4


class FrameType(IntEnum):
    MAIN_DOCUMENT = 0x44  # "D"
    KEY_DOCUMENT = 0x4B  # "K"
    AUTH = 0x41  # "A"


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
    if version != VERSION:
        raise ValueError(f"unsupported frame version: {version}")
    if idx >= len(payload):
        raise ValueError("missing frame type")

    frame_type = payload[idx]
    idx += 1
    try:
        FrameType(frame_type)
    except ValueError as exc:
        raise ValueError(f"unsupported frame type: {frame_type}") from exc

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
    crc_actual = zlib.crc32(payload[:idx]) & 0xFFFFFFFF
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
    _validate_frame(frame)
    return frame


def _validate_frame(frame: Frame) -> None:
    if frame.version != VERSION:
        raise ValueError(f"unsupported frame version: {frame.version}")

    frame_type = int(frame.frame_type)
    try:
        frame_type_enum = FrameType(frame_type)
    except ValueError as exc:
        raise ValueError(f"unsupported frame type: {frame_type}") from exc

    if frame.total <= 0:
        raise ValueError("total must be positive")
    if frame.index < 0:
        raise ValueError("index must be non-negative")
    if frame.index >= frame.total:
        raise ValueError("index must be < total")
    if len(frame.doc_id) != DOC_ID_LEN:
        raise ValueError(f"doc_id must be {DOC_ID_LEN} bytes")

    data_len = len(frame.data)
    if frame_type_enum == FrameType.MAIN_DOCUMENT:
        if frame.total > MAX_MAIN_FRAME_TOTAL:
            raise ValueError(
                f"MAIN_DOCUMENT total exceeds MAX_MAIN_FRAME_TOTAL ({MAX_MAIN_FRAME_TOTAL}): "
                f"{frame.total}"
            )
        if data_len > MAX_MAIN_FRAME_DATA_BYTES:
            raise ValueError(
                "MAIN_DOCUMENT data exceeds "
                f"MAX_MAIN_FRAME_DATA_BYTES ({MAX_MAIN_FRAME_DATA_BYTES}): {data_len} bytes"
            )
    elif frame_type_enum == FrameType.AUTH:
        if frame.total != 1 or frame.index != 0:
            raise ValueError("AUTH payload must be a single-frame payload (index=0,total=1)")
        if data_len > MAX_AUTH_CBOR_BYTES:
            raise ValueError(
                f"AUTH data exceeds MAX_AUTH_CBOR_BYTES ({MAX_AUTH_CBOR_BYTES}): "
                f"{data_len} bytes"
            )
    elif frame_type_enum == FrameType.KEY_DOCUMENT:
        if frame.total != 1 or frame.index != 0:
            raise ValueError(
                "KEY_DOCUMENT payload must be a single-frame payload (index=0,total=1)"
            )
        if data_len > MAX_SHARD_CBOR_BYTES:
            raise ValueError(
                f"KEY_DOCUMENT data exceeds MAX_SHARD_CBOR_BYTES ({MAX_SHARD_CBOR_BYTES}): "
                f"{data_len} bytes"
            )
