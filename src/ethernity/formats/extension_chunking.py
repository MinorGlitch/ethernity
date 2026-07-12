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

"""Content-defined chunking helpers shared by extension build, envelope, and replay."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Sequence
from typing import Protocol


class ExtensionChunkingProfileLike(Protocol):
    @property
    def target_size(self) -> int: ...

    @property
    def min_size(self) -> int: ...

    @property
    def max_size(self) -> int: ...


Chunker = Callable[[bytes, ExtensionChunkingProfileLike], Sequence[bytes]]

_ROLLING_HASH_MASK = (1 << 64) - 1
_MIN_MASK_BITS = 4
_ROLLING_WINDOW_SIZE = 64


def _build_gear_table() -> tuple[int, ...]:
    state = 0x9E3779B97F4A7C15
    values: list[int] = []
    for _index in range(256):
        state ^= (state >> 12) & _ROLLING_HASH_MASK
        state ^= (state << 25) & _ROLLING_HASH_MASK
        state ^= (state >> 27) & _ROLLING_HASH_MASK
        state = (state * 0x2545F4914F6CDD1D) & _ROLLING_HASH_MASK
        values.append(state)
    return tuple(values)


_GEAR_TABLE = _build_gear_table()


def default_extension_chunker(
    data: bytes,
    profile: ExtensionChunkingProfileLike,
) -> tuple[bytes, ...]:
    if not data:
        return ()
    chunks: list[bytes] = []
    start = 0
    data_view = memoryview(data)
    primary_mask, secondary_mask = _rolling_masks(profile.target_size)
    while start < len(data):
        chunk_end = _next_chunk_boundary(
            data_view,
            start=start,
            min_size=profile.min_size,
            target_size=profile.target_size,
            max_size=profile.max_size,
            primary_mask=primary_mask,
            secondary_mask=secondary_mask,
        )
        chunks.append(bytes(data_view[start:chunk_end]))
        start = chunk_end
    return tuple(chunks)


def canonical_chunk_refs_for_bytes(
    data: bytes,
    profile: ExtensionChunkingProfileLike,
) -> tuple[tuple[bytes, int], ...]:
    """Return the canonical chunk reference sequence for bytes under an extension profile."""

    return tuple(
        (hashlib.sha256(chunk).digest(), len(chunk))
        for chunk in default_extension_chunker(data, profile)
    )


def require_canonical_chunk_refs(
    declared_refs: Sequence[tuple[bytes, int]],
    data: bytes,
    profile: ExtensionChunkingProfileLike,
) -> None:
    """Reject chunk refs that do not match the locked extension chunking profile."""

    if tuple(declared_refs) != canonical_chunk_refs_for_bytes(data, profile):
        raise ValueError("extension file chunk_refs do not match locked chunking profile")


def _rolling_masks(target_size: int) -> tuple[int, int]:
    target_bits = max(_MIN_MASK_BITS, int(round(math.log2(max(2, target_size)))))
    primary_bits = min(63, target_bits)
    secondary_bits = max(_MIN_MASK_BITS, target_bits - 2)
    return (1 << primary_bits) - 1, (1 << secondary_bits) - 1


def _next_chunk_boundary(
    data: memoryview,
    *,
    start: int,
    min_size: int,
    target_size: int,
    max_size: int,
    primary_mask: int,
    secondary_mask: int,
) -> int:
    total_len = len(data)
    if total_len - start <= min_size:
        return total_len

    min_end = min(total_len, start + min_size)
    target_end = min(total_len, start + target_size)
    max_end = min(total_len, start + max_size)
    fingerprint = 0
    window = [0] * _ROLLING_WINDOW_SIZE
    window_count = 0
    window_pos = 0

    for index in range(start, max_end):
        byte_value = data[index]
        if window_count < _ROLLING_WINDOW_SIZE:
            fingerprint = _roll_fingerprint(fingerprint, byte_value)
            window[window_pos] = byte_value
            window_pos = (window_pos + 1) % _ROLLING_WINDOW_SIZE
            window_count += 1
        else:
            outgoing = window[window_pos]
            window[window_pos] = byte_value
            window_pos = (window_pos + 1) % _ROLLING_WINDOW_SIZE
            fingerprint = (
                _rotate_left(fingerprint, 1) ^ _GEAR_TABLE[outgoing] ^ _GEAR_TABLE[byte_value]
            ) & _ROLLING_HASH_MASK
        if index + 1 < min_end:
            continue
        mask = primary_mask if index + 1 < target_end else secondary_mask
        if fingerprint & mask == 0:
            return index + 1

    return max_end


def _roll_fingerprint(current: int, byte_value: int) -> int:
    return _rotate_left(current, 1) ^ _GEAR_TABLE[byte_value]


def _rotate_left(value: int, shift: int) -> int:
    shift &= 63
    return ((value << shift) | (value >> (64 - shift))) & _ROLLING_HASH_MASK


__all__ = [
    "Chunker",
    "canonical_chunk_refs_for_bytes",
    "default_extension_chunker",
    "require_canonical_chunk_refs",
]
