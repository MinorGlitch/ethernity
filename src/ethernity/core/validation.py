#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, TypeVar

T = TypeVar("T")


def require_list(value: object, min_length: int, *, label: str) -> list[Any] | tuple[Any, ...]:
    """Validate that value is a list/tuple with at least min_length elements."""
    if not isinstance(value, (list, tuple)) or len(value) < min_length:
        raise ValueError(f"{label} must be a list")
    return value


def require_length(value: bytes, length: int, *, label: str, prefix: str = "") -> None:
    """Validate that bytes value has exact length."""
    if len(value) != length:
        raise ValueError(f"{prefix}{label} must be {length} bytes")


def require_bytes(
    value: object,
    length: int,
    *,
    label: str,
    prefix: str = "",
) -> bytes:
    """Validate that value is bytes with exact length."""
    if not isinstance(value, (bytes, bytearray)):
        raise ValueError(f"{prefix}{label} must be bytes")
    raw = bytes(value)
    require_length(raw, length, label=label, prefix=prefix)
    return raw


def require_positive_int(value: object, *, label: str) -> int:
    """Validate that value is a positive integer (> 0)."""
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive int")
    return value


def require_non_negative_int(value: object, *, label: str) -> int:
    """Validate that value is a non-negative integer (>= 0)."""
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative int")
    return value


def require_int_range(value: int, *, min_val: int, max_val: int, label: str) -> int:
    """Validate that integer value is within range [min_val, max_val]."""
    if value < min_val or value > max_val:
        raise ValueError(f"{label} must be between {min_val} and {max_val}")
    return value


def require_non_empty_bytes(value: object, *, label: str) -> bytes:
    """Validate that value is non-empty bytes."""
    if not isinstance(value, (bytes, bytearray)) or not value:
        raise ValueError(f"{label} must be non-empty bytes")
    return bytes(value)


def require_version(actual: int, expected: int, *, label: str) -> None:
    """Validate that version matches expected value."""
    if actual != expected:
        raise ValueError(f"unsupported {label} version: {actual}")
