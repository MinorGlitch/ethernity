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

# 1 MiB maximum ciphertext size for v1 profile.
MAX_CIPHERTEXT_BYTES = 1_048_576

# MAIN frame data cap (single-frame fallback MAIN compatibility).
MAX_MAIN_FRAME_DATA_BYTES = 1_048_576

# MAIN frame count cap for chunked QR transport.
MAX_MAIN_FRAME_TOTAL = 4_096

# Maximum QR payload characters (whitespace-stripped).
MAX_QR_PAYLOAD_CHARS = 3_072

# Maximum AUTH payload size (CBOR bytes).
MAX_AUTH_CBOR_BYTES = 512

# Maximum shard payload size (CBOR bytes).
MAX_SHARD_CBOR_BYTES = 2_048

# Maximum canonical manifest size (CBOR bytes).
MAX_MANIFEST_CBOR_BYTES = 1_048_576

# Maximum number of files in a manifest.
MAX_MANIFEST_FILES = 2_048

# Maximum UTF-8 byte length for manifest paths.
MAX_PATH_BYTES = 512

# Maximum normalized z-base-32 characters in fallback input.
MAX_FALLBACK_NORMALIZED_CHARS = 2_000_000

# Maximum fallback lines per parsed frame section.
MAX_FALLBACK_LINES = 50_000

# Maximum recovery text input size (UTF-8 bytes).
MAX_RECOVERY_TEXT_BYTES = 10_485_760


__all__ = [
    "MAX_AUTH_CBOR_BYTES",
    "MAX_CIPHERTEXT_BYTES",
    "MAX_FALLBACK_LINES",
    "MAX_FALLBACK_NORMALIZED_CHARS",
    "MAX_MAIN_FRAME_DATA_BYTES",
    "MAX_MAIN_FRAME_TOTAL",
    "MAX_MANIFEST_CBOR_BYTES",
    "MAX_MANIFEST_FILES",
    "MAX_PATH_BYTES",
    "MAX_QR_PAYLOAD_CHARS",
    "MAX_RECOVERY_TEXT_BYTES",
    "MAX_SHARD_CBOR_BYTES",
]
