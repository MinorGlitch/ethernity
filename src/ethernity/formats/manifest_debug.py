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

"""Debug-friendly envelope manifest decoding helpers."""

from __future__ import annotations

import json
from pathlib import Path

import cbor2


def json_safe_debug_value(value: object) -> object:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe_debug_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_debug_value(item) for item in value]
    return value


def decode_manifest_debug_value(data: bytes) -> object | None:
    try:
        decoded = cbor2.loads(data)
    except (ValueError, cbor2.CBORDecodeError):
        decoded = None
    if decoded is not None:
        return json_safe_debug_value(decoded)

    try:
        decoded_json = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return json_safe_debug_value(decoded_json)
