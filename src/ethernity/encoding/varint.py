#!/usr/bin/env python3
from __future__ import annotations


def encode_uvarint(value: int) -> bytes:
    if value < 0:
        raise ValueError("value must be non-negative")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def decode_uvarint(data: bytes, start: int) -> tuple[int, int]:
    value = 0
    shift = 0
    idx = start
    while True:
        if idx >= len(data):
            raise ValueError("truncated varint")
        byte = data[idx]
        idx += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value, idx
        shift += 7
        if shift > 63:
            raise ValueError("varint too large")
