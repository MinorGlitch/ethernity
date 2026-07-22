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

# Root plus extension documents admitted to one recovery/append session.
MAX_RECOVERY_DOCUMENTS = 128

# Aggregate ciphertext admitted across one root-plus-extension chain.
MAX_RECOVERY_CIPHERTEXT_BYTES = 64 * MAX_CIPHERTEXT_BYTES

# Largest integer represented exactly by both Python and JavaScript runtimes.
MAX_JS_SAFE_INTEGER = 9_007_199_254_740_991

# A complete chain includes one root document, so extension indexes stop one below the document cap.
MAX_EXTENSION_INDEX = MAX_RECOVERY_DOCUMENTS - 1

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

# Maximum normalized raw payload bytes allowed after manifest-signaled decode.
MAX_DECOMPRESSED_PAYLOAD_BYTES = 67_108_864  # 64 MiB

# Cumulative inline chunk bytes decoded while replaying one extension chain.
MAX_RECOVERY_DECODED_CHUNK_BYTES = 4 * MAX_DECOMPRESSED_PAYLOAD_BYTES


__all__ = [
    "MAX_AUTH_CBOR_BYTES",
    "MAX_CIPHERTEXT_BYTES",
    "MAX_DECOMPRESSED_PAYLOAD_BYTES",
    "MAX_EXTENSION_INDEX",
    "MAX_FALLBACK_LINES",
    "MAX_FALLBACK_NORMALIZED_CHARS",
    "MAX_MAIN_FRAME_DATA_BYTES",
    "MAX_MAIN_FRAME_TOTAL",
    "MAX_MANIFEST_CBOR_BYTES",
    "MAX_MANIFEST_FILES",
    "MAX_JS_SAFE_INTEGER",
    "MAX_PATH_BYTES",
    "MAX_QR_PAYLOAD_CHARS",
    "MAX_RECOVERY_TEXT_BYTES",
    "MAX_RECOVERY_CIPHERTEXT_BYTES",
    "MAX_RECOVERY_DECODED_CHUNK_BYTES",
    "MAX_RECOVERY_DOCUMENTS",
    "MAX_SHARD_CBOR_BYTES",
]
