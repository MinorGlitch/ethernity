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

import unicodedata
from collections.abc import Iterable
from typing import Any, TypeVar

from .bounds import MAX_PATH_BYTES

T = TypeVar("T")


def require_list(value: object, min_length: int, *, label: str) -> list[Any] | tuple[Any, ...]:
    """Validate that value is a list/tuple with at least min_length elements."""
    if not isinstance(value, (list, tuple)) or len(value) < min_length:
        raise ValueError(f"{label} must be a list")
    return value


def require_dict(value: object, *, label: str) -> dict[Any, Any]:
    """Validate that value is a dict."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a dict")
    return value


def require_keys(mapping: dict[Any, Any], keys: Iterable[str], *, label: str) -> None:
    """Validate that all keys are present in mapping."""
    for key in keys:
        if key not in mapping:
            raise ValueError(f"{label} {key} is required")


def normalize_path(path: object, *, label: str = "path") -> str:
    """Normalize a path to Unicode NFC and ensure it is valid UTF-8."""
    if not isinstance(path, str):
        raise ValueError(f"{label} must be a string")
    try:
        path.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8") from exc
    return unicodedata.normalize("NFC", path)


def normalize_manifest_path(path: object, *, label: str = "path") -> str:
    """Normalize and validate manifest path constraints."""
    normalized = normalize_path(path, label=label)
    if not normalized:
        raise ValueError(f"{label} must be a non-empty string")
    if normalized.startswith("/"):
        raise ValueError(f"{label} must be relative (no leading '/')")
    if "\\" in normalized:
        raise ValueError(f"{label} must use POSIX separators ('/')")
    segments = normalized.split("/")
    if any(segment == "" for segment in segments):
        raise ValueError(f"{label} must not contain empty path segments")
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError(f"{label} must not contain '.' or '..' path segments")
    path_bytes = len(normalized.encode("utf-8"))
    if path_bytes > MAX_PATH_BYTES:
        raise ValueError(
            f"{label} exceeds MAX_PATH_BYTES ({MAX_PATH_BYTES} bytes): {path_bytes} bytes"
        )
    return normalized


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
