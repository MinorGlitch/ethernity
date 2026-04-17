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

"""Shared public constants for the extension envelope format."""

EXTENSION_ENVELOPE_VERSION = 2
EXTENSION_SCHEMA_VERSION = 1
CHAIN_ID_PERSONALIZATION = b"ETHERNITY-CHAIN-V1"
CHUNK_CODEC_RAW = 0
CHUNK_CODEC_GZIP = 1
CHUNK_ALGORITHM_FASTCDC = 1

__all__ = [
    "CHAIN_ID_PERSONALIZATION",
    "CHUNK_ALGORITHM_FASTCDC",
    "CHUNK_CODEC_GZIP",
    "CHUNK_CODEC_RAW",
    "EXTENSION_ENVELOPE_VERSION",
    "EXTENSION_SCHEMA_VERSION",
]
