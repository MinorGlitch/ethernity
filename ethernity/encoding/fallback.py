#!/usr/bin/env python3
from __future__ import annotations

from typing import Iterable

ZBASE32_ALPHABET = "ybndrfg8ejkmcpqxot1uwisza345h769"
ZBASE32_LOOKUP = {ch: idx for idx, ch in enumerate(ZBASE32_ALPHABET)}

DEFAULT_GROUP_SIZE = 4
DEFAULT_LINE_LENGTH = 80
DEFAULT_LINE_COUNT = 6


def encode_fallback_lines(
    data: bytes,
    *,
    group_size: int = DEFAULT_GROUP_SIZE,
    line_length: int = DEFAULT_LINE_LENGTH,
    line_count: int | None = DEFAULT_LINE_COUNT,
) -> list[str]:
    if group_size <= 0:
        raise ValueError("group_size must be positive")
    if line_length <= 0:
        raise ValueError("line_length must be positive")
    if line_count is not None and line_count <= 0:
        raise ValueError("line_count must be positive")

    encoded = encode_zbase32(data)
    groups = [encoded[i : i + group_size] for i in range(0, len(encoded), group_size)]

    lines: list[str] = []
    current = ""
    for group in groups:
        candidate = group if not current else f"{current} {group}"
        if len(candidate) > line_length:
            lines.append(current)
            current = group
        else:
            current = candidate

    if current:
        lines.append(current)

    if line_count is not None and len(lines) > line_count:
        raise ValueError("fallback text exceeds line_count")
    return lines


def decode_fallback_lines(lines: Iterable[str]) -> bytes:
    text = "".join(lines)
    return decode_zbase32(text)


def encode_zbase32(data: bytes) -> str:
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
