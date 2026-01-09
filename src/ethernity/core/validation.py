#!/usr/bin/env python3
from __future__ import annotations


def require_length(value: bytes, length: int, *, label: str, prefix: str = "") -> None:
    if len(value) != length:
        raise ValueError(f"{prefix}{label} must be {length} bytes")


def require_bytes(
    value: object,
    length: int,
    *,
    label: str,
    prefix: str = "",
) -> bytes:
    if not isinstance(value, (bytes, bytearray)):
        raise ValueError(f"{prefix}{label} must be bytes")
    raw = bytes(value)
    require_length(raw, length, label=label, prefix=prefix)
    return raw
