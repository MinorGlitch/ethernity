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

"""Envelope payload codec helpers for optional manifest-signaled compression."""

from __future__ import annotations

import gzip
import zlib
from typing import Literal

from ..core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES
from .envelope_types import PAYLOAD_CODEC_GZIP, PAYLOAD_CODEC_RAW, EnvelopeManifest

PAYLOAD_ENCODING_AUTO: Literal["auto"] = "auto"
PayloadEncodingMode = Literal["auto", "raw", "gzip"]


def encode_payload_for_manifest(
    payload: bytes, *, mode: PayloadEncodingMode = PAYLOAD_ENCODING_AUTO
) -> tuple[bytes, str, int | None]:
    """Encode payload bytes for storage and return `(payload, codec, raw_len)`.

    Compression is deterministic. In `auto` mode, gzip is selected only when it is smaller.
    """

    if len(payload) > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError(
            "payload exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES "
            f"({MAX_DECOMPRESSED_PAYLOAD_BYTES}): {len(payload)} bytes"
        )

    if mode not in {PAYLOAD_ENCODING_AUTO, PAYLOAD_CODEC_RAW, PAYLOAD_CODEC_GZIP}:
        raise ValueError(f"unsupported payload encoding mode: {mode}")

    if mode == PAYLOAD_CODEC_RAW:
        return payload, PAYLOAD_CODEC_RAW, None

    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    if mode == PAYLOAD_CODEC_GZIP:
        return compressed, PAYLOAD_CODEC_GZIP, len(payload)

    if len(compressed) < len(payload):
        return compressed, PAYLOAD_CODEC_GZIP, len(payload)
    return payload, PAYLOAD_CODEC_RAW, None


def decode_payload_from_manifest(manifest: EnvelopeManifest, payload: bytes) -> bytes:
    """Decode payload bytes according to manifest codec metadata."""

    codec = manifest.payload_codec
    if codec == PAYLOAD_CODEC_RAW:
        if manifest.payload_raw_len is not None:
            raise ValueError("manifest payload_raw_len must be null for raw payload codec")
        return payload
    if codec != PAYLOAD_CODEC_GZIP:
        raise ValueError(f"unsupported payload codec: {codec}")

    expected_len = manifest.payload_raw_len
    if expected_len is None or expected_len <= 0:
        raise ValueError("manifest payload_raw_len must be a positive int for gzip payload codec")
    if expected_len > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError(
            "manifest payload_raw_len exceeds MAX_DECOMPRESSED_PAYLOAD_BYTES "
            f"({MAX_DECOMPRESSED_PAYLOAD_BYTES}): {expected_len}"
        )

    expected_from_entries = sum(entry.size for entry in manifest.files)
    if expected_from_entries != expected_len:
        raise ValueError("manifest payload_raw_len must match sum of manifest file sizes")

    decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    try:
        decoded = decompressor.decompress(payload, max_length=expected_len + 1)
    except zlib.error as exc:
        raise ValueError("invalid gzip payload") from exc
    if len(decoded) > expected_len:
        raise ValueError("decoded payload exceeds manifest payload_raw_len")
    if decompressor.unconsumed_tail:
        raise ValueError("decoded payload exceeds manifest payload_raw_len")

    try:
        flushed = decompressor.flush(expected_len + 1 - len(decoded))
    except zlib.error as exc:
        raise ValueError("invalid gzip payload") from exc
    decoded += flushed
    if len(decoded) > expected_len:
        raise ValueError("decoded payload exceeds manifest payload_raw_len")
    if not decompressor.eof:
        raise ValueError("invalid gzip payload")
    if decompressor.unused_data:
        raise ValueError("gzip payload contains trailing data")
    if len(decoded) != expected_len:
        raise ValueError("decoded payload length does not match manifest payload_raw_len")

    return decoded


__all__ = [
    "decode_payload_from_manifest",
    "encode_payload_for_manifest",
    "PAYLOAD_ENCODING_AUTO",
    "PayloadEncodingMode",
]
