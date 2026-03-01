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

import gzip
import hashlib
import os
import unittest
from unittest import mock

from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES
from ethernity.formats.envelope_types import (
    MANIFEST_VERSION,
    PAYLOAD_CODEC_GZIP,
    PAYLOAD_CODEC_RAW,
    EnvelopeManifest,
    ManifestFile,
)
from ethernity.formats.payload_codec import (
    decode_payload_from_manifest,
    encode_payload_for_manifest,
)


class TestPayloadCodec(unittest.TestCase):
    _SEED = b"1" * 32

    def _manifest_for(self, payload: bytes, *, codec: str, raw_len: int | None) -> EnvelopeManifest:
        return EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=False,
            signing_seed=self._SEED,
            payload_codec=codec,
            payload_raw_len=raw_len,
            files=(
                ManifestFile(
                    path="payload.bin",
                    size=len(payload),
                    sha256=hashlib.sha256(payload).digest(),
                    mtime=None,
                ),
            ),
        )

    def test_encode_payload_for_manifest_auto_compresses_when_smaller(self) -> None:
        raw = b"A" * 4096
        encoded, codec, raw_len = encode_payload_for_manifest(raw)
        self.assertEqual(codec, PAYLOAD_CODEC_GZIP)
        self.assertEqual(raw_len, len(raw))
        self.assertLess(len(encoded), len(raw))

    def test_encode_payload_for_manifest_keeps_raw_when_not_smaller(self) -> None:
        raw = os.urandom(4096)
        encoded, codec, raw_len = encode_payload_for_manifest(raw)
        self.assertEqual(codec, PAYLOAD_CODEC_RAW)
        self.assertIsNone(raw_len)
        self.assertEqual(encoded, raw)

    def test_encode_payload_for_manifest_rejects_payload_over_max_decompressed_bound(self) -> None:
        with mock.patch("ethernity.formats.payload_codec.MAX_DECOMPRESSED_PAYLOAD_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "MAX_DECOMPRESSED_PAYLOAD_BYTES"):
                encode_payload_for_manifest(b"A" * 9)

    def test_decode_payload_from_manifest_roundtrip_gzip(self) -> None:
        raw = b"hello world\n" * 300
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        manifest = self._manifest_for(raw, codec=PAYLOAD_CODEC_GZIP, raw_len=len(raw))
        self.assertEqual(decode_payload_from_manifest(manifest, compressed), raw)

    def test_decode_payload_from_manifest_rejects_length_mismatch(self) -> None:
        raw = b"hello world\n" * 100
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        manifest = self._manifest_for(raw, codec=PAYLOAD_CODEC_GZIP, raw_len=len(raw) + 5)
        with self.assertRaisesRegex(ValueError, "payload_raw_len"):
            decode_payload_from_manifest(manifest, compressed)

    def test_decode_payload_from_manifest_rejects_raw_len_on_raw_codec(self) -> None:
        raw = b"raw"
        manifest = self._manifest_for(raw, codec=PAYLOAD_CODEC_RAW, raw_len=len(raw))
        with self.assertRaisesRegex(ValueError, "payload_raw_len"):
            decode_payload_from_manifest(manifest, raw)

    def test_decode_payload_from_manifest_rejects_gzip_over_max_decompressed_bound(self) -> None:
        expected_len = MAX_DECOMPRESSED_PAYLOAD_BYTES + 1
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=False,
            signing_seed=self._SEED,
            payload_codec=PAYLOAD_CODEC_GZIP,
            payload_raw_len=expected_len,
            files=(
                ManifestFile(
                    path="payload.bin",
                    size=expected_len,
                    sha256=b"\x00" * 32,
                    mtime=None,
                ),
            ),
        )
        compressed = gzip.compress(b"A", compresslevel=9, mtime=0)
        with self.assertRaisesRegex(ValueError, "MAX_DECOMPRESSED_PAYLOAD_BYTES"):
            decode_payload_from_manifest(manifest, compressed)


if __name__ == "__main__":
    unittest.main()
