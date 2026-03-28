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

"""Canonical CBOR encoding and decoding helpers."""

from __future__ import annotations

import cbor2


def dumps_canonical(value: object) -> bytes:
    """Encode a value using canonical CBOR."""

    return cbor2.dumps(value, canonical=True)


def loads_canonical(data: bytes, *, label: str) -> object:
    """Decode CBOR and reject non-canonical encodings."""

    try:
        decoded = cbor2.loads(data)
    except (cbor2.CBORDecodeError, ValueError) as exc:
        raise ValueError(f"invalid {label} CBOR payload") from exc
    except RecursionError as exc:
        raise ValueError(f"{label} CBOR nesting is too deep") from exc
    try:
        if dumps_canonical(decoded) != data:
            raise ValueError(
                f"{label} must use canonical CBOR encoding "
                "(indefinite-length items are not allowed)"
            )
    except cbor2.CBOREncodeError as exc:
        raise ValueError(f"invalid {label} CBOR payload") from exc
    return decoded
