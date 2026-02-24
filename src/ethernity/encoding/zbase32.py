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

"""z-base-32 encoding helpers for fallback text payloads."""

from __future__ import annotations

from typing import Iterable

ZBASE32_ALPHABET = "ybndrfg8ejkmcpqxot1uwisza345h769"
ZBASE32_LOOKUP = {ch: idx for idx, ch in enumerate(ZBASE32_ALPHABET)}


def decode_fallback_lines(lines: Iterable[str]) -> bytes:
    """Decode fallback text lines by concatenating and z-base-32 decoding."""

    text = "".join(lines)
    return decode_zbase32(text)


def encode_zbase32(data: bytes) -> str:
    """Encode bytes using z-base-32 without separators."""

    if not data:
        return ""
    bits = 0
    bit_count = 0
    out_chars: list[str] = []

    for byte in data:
        bits = (bits << 8) | byte
        bit_count += 8
        while bit_count >= 5:
            shift = bit_count - 5
            index = (bits >> shift) & 0x1F
            out_chars.append(ZBASE32_ALPHABET[index])
            bit_count -= 5
            bits &= (1 << bit_count) - 1

    if bit_count:
        index = (bits << (5 - bit_count)) & 0x1F
        out_chars.append(ZBASE32_ALPHABET[index])

    return "".join(out_chars)


def decode_zbase32(text: str) -> bytes:
    """Decode z-base-32 text, ignoring whitespace and hyphens."""

    bits = 0
    bit_count = 0
    out = bytearray()

    for char in text:
        if char.isspace() or char == "-":
            continue
        value = ZBASE32_LOOKUP.get(char.lower())
        if value is None:
            raise ValueError(f"invalid z-base-32 character: {char!r}")
        bits = (bits << 5) | value
        bit_count += 5
        if bit_count >= 8:
            shift = bit_count - 8
            out.append((bits >> shift) & 0xFF)
            bit_count -= 8
            bits &= (1 << bit_count) - 1
    return bytes(out)
