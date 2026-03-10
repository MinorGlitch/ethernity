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

"""Compatibility helpers for minting Shamir replacement shares.

This module intentionally keeps the GF(2^128) interpolation logic isolated from
the public sharding API. The arithmetic matches the field used by PyCryptodome's
public ``Shamir.split``/``Shamir.combine`` helpers so that we can mint shares
for missing indices without importing any underscore-prefixed private symbols.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

BLOCK_SIZE = 16
_GF128_IRREDUCIBLE = 1 + 2 + 4 + 128 + 2**128


def interpolate_share_blocks(
    source_shares: Sequence[tuple[int, bytes]],
    *,
    target_index: int,
    block_count: int,
) -> bytes:
    """Interpolate a missing share for the requested index.

    ``source_shares`` must contain quorum-compatible shares as ``(index, share)``
    tuples, where ``share`` is the full concatenated share bytes for all blocks.
    """

    if not source_shares:
        raise ValueError("no source shares provided")
    if target_index < 1:
        raise ValueError("target index must be >= 1")
    if block_count < 1:
        raise ValueError("block count must be >= 1")

    share_len = block_count * BLOCK_SIZE
    for index, share in source_shares:
        if index < 1:
            raise ValueError("share index must be >= 1")
        if len(share) != share_len:
            raise ValueError("share length does not match block count")

    return b"".join(
        _interpolate_share_block(source_shares, target_index=target_index, block_index=block_index)
        for block_index in range(block_count)
    )


def _interpolate_share_block(
    source_shares: Sequence[tuple[int, bytes]],
    *,
    target_index: int,
    block_index: int,
) -> bytes:
    x = _GF128Element.from_index(target_index)
    start = block_index * BLOCK_SIZE
    end = start + BLOCK_SIZE
    points = [
        (_GF128Element.from_index(index), _GF128Element.from_bytes(share[start:end]))
        for index, share in source_shares
    ]
    result = _GF128Element(0)
    for point_index, (x_j, y_j) in enumerate(points):
        numerator = _GF128Element(1)
        denominator = _GF128Element(1)
        for other_index, (x_m, _y_m) in enumerate(points):
            if other_index == point_index:
                continue
            numerator = numerator * (x + x_m)
            denominator = denominator * (x_j + x_m)
        result = result + (y_j * numerator * denominator.inverse())
    return result.to_bytes()


def _gf2_mul(left: int, right: int) -> int:
    result = 0
    while right:
        if right & 1:
            result ^= left
        left <<= 1
        right >>= 1
    return result


def _gf2_divmod(dividend: int, divisor: int) -> tuple[int, int]:
    if dividend < divisor:
        return 0, dividend
    quotient = 0
    remainder = dividend
    divisor_degree = divisor.bit_length() - 1
    while remainder and remainder.bit_length() - 1 >= divisor_degree:
        shift = (remainder.bit_length() - 1) - divisor_degree
        quotient ^= 1 << shift
        remainder ^= _gf2_mul(divisor, 1 << shift)
    return quotient, remainder


@dataclass(frozen=True)
class _GF128Element:
    value: int

    @classmethod
    def from_index(cls, index: int) -> _GF128Element:
        return cls(index)

    @classmethod
    def from_bytes(cls, encoded: bytes) -> _GF128Element:
        if len(encoded) != BLOCK_SIZE:
            raise ValueError(f"GF(2^128) element must be {BLOCK_SIZE} bytes")
        return cls(int.from_bytes(encoded, "big"))

    def to_bytes(self) -> bytes:
        return self.value.to_bytes(BLOCK_SIZE, "big")

    def __add__(self, other: _GF128Element) -> _GF128Element:
        return _GF128Element(self.value ^ other.value)

    def __mul__(self, other: _GF128Element) -> _GF128Element:
        left = self.value
        right = other.value
        if right > left:
            left, right = right, left
        if _GF128_IRREDUCIBLE in (left, right):
            return _GF128Element(0)
        mask = 1 << 128
        value = left
        result = 0
        while right:
            if right & 1:
                result ^= value
            value <<= 1
            if value & mask:
                value ^= _GF128_IRREDUCIBLE
            right >>= 1
        return _GF128Element(result)

    def inverse(self) -> _GF128Element:
        if self.value == 0:
            raise ValueError("Inversion of zero")
        r0, r1 = self.value, _GF128_IRREDUCIBLE
        s0, s1 = 1, 0
        while r1 > 0:
            quotient, _remainder = _gf2_divmod(r0, r1)
            r0, r1 = r1, r0 ^ _gf2_mul(quotient, r1)
            s0, s1 = s1, s0 ^ _gf2_mul(quotient, s1)
        return _GF128Element(s0)
