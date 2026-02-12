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

_MAX_UVARINT = (1 << 64) - 1


def encode_uvarint(value: int) -> bytes:
    if value < 0:
        raise ValueError("value must be non-negative")
    if value > _MAX_UVARINT:
        raise ValueError("value must be <= 2^64-1")
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
    if start < 0:
        raise ValueError("start must be non-negative")
    value = 0
    shift = 0
    idx = start
    while True:
        if idx >= len(data):
            raise ValueError("truncated varint")
        byte = data[idx]
        payload = byte & 0x7F
        if shift == 63 and payload > 1:
            raise ValueError("varint too large")
        idx += 1
        value |= payload << shift
        if byte & 0x80 == 0:
            if data[start:idx] != encode_uvarint(value):
                raise ValueError("non-canonical varint")
            return value, idx
        shift += 7
        if shift > 63:
            raise ValueError("varint too large")
