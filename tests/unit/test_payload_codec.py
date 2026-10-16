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
from ethernity.formats.manifest import (
    PAYLOAD_CODEC_GZIP,
    PAYLOAD_CODEC_RAW,
    BackupManifest,
    ManifestFile,
)
from ethernity.formats.payload_codec import (
    PAYLOAD_ENCODING_AUTO,
    decode_payload_from_manifest,
    encode_payload_for_manifest,
)


class TestPayloadCodec(unittest.TestCase):
    _SEED = b"1" * 32

    def _manifest_for(
        self, payload: bytes, *, codec: str, size: int | None = None
    ) -> BackupManifest:
        return BackupManifest(
            created_at=0.0,
            signing_seed=self._SEED,
            payload_codec=codec,
            files=(
                ManifestFile(
                    path="payload.bin",
                    size=len(payload) if size is None else size,
                    sha256=hashlib.sha256(payload).digest(),
                    mtime=None,
                ),
            ),
        )

    def test_encode_payload_for_manifest_auto_compresses_when_smaller(self) -> None:
        raw = b"A" * 4096
        encoded, codec = encode_payload_for_manifest(raw, mode=PAYLOAD_ENCODING_AUTO)
        self.assertEqual(codec, PAYLOAD_CODEC_GZIP)
        self.assertLess(len(encoded), len(raw))

    def test_encode_payload_for_manifest_keeps_raw_when_not_smaller(self) -> None:
        raw = os.urandom(4096)
        encoded, codec = encode_payload_for_manifest(raw, mode=PAYLOAD_ENCODING_AUTO)
        self.assertEqual(codec, PAYLOAD_CODEC_RAW)
        self.assertEqual(encoded, raw)

    def test_encode_payload_for_manifest_forces_raw_mode(self) -> None:
        raw = b"A" * 4096
        encoded, codec = encode_payload_for_manifest(raw, mode=PAYLOAD_CODEC_RAW)
        self.assertEqual(codec, PAYLOAD_CODEC_RAW)
        self.assertEqual(encoded, raw)

    def test_encode_payload_for_manifest_forces_gzip_mode(self) -> None:
        raw = os.urandom(4096)
        encoded, codec = encode_payload_for_manifest(raw, mode=PAYLOAD_CODEC_GZIP)
        self.assertEqual(codec, PAYLOAD_CODEC_GZIP)
        self.assertNotEqual(encoded, raw)

    def test_encode_payload_for_manifest_rejects_payload_over_max_decompressed_bound(self) -> None:
        with mock.patch("ethernity.formats.payload_codec.MAX_DECOMPRESSED_PAYLOAD_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "MAX_DECOMPRESSED_PAYLOAD_BYTES"):
                encode_payload_for_manifest(b"A" * 9)

    def test_encode_payload_for_manifest_rejects_unknown_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported payload encoding mode"):
            encode_payload_for_manifest(b"payload", mode="brotli")  # type: ignore[arg-type]

    def test_decode_payload_from_manifest_roundtrip_gzip(self) -> None:
        raw = b"hello world\n" * 300
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        manifest = self._manifest_for(raw, codec=PAYLOAD_CODEC_GZIP)
        self.assertEqual(decode_payload_from_manifest(manifest, compressed), raw)

    def test_decode_payload_from_manifest_rejects_length_mismatch(self) -> None:
        raw = b"hello world\n" * 100
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        manifest = self._manifest_for(raw, codec=PAYLOAD_CODEC_GZIP, size=len(raw) + 5)
        with self.assertRaisesRegex(ValueError, "payload_raw_len"):
            decode_payload_from_manifest(manifest, compressed)

    def test_decode_payload_from_manifest_rejects_gzip_over_max_decompressed_bound(self) -> None:
        expected_len = MAX_DECOMPRESSED_PAYLOAD_BYTES + 1
        manifest = BackupManifest(
            created_at=0.0,
            signing_seed=self._SEED,
            payload_codec=PAYLOAD_CODEC_GZIP,
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
