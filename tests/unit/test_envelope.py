import unittest

from ethernity.formats.envelope_codec import (
    MAGIC,
    build_manifest_and_payload,
    decode_envelope,
    encode_envelope,
    extract_payloads,
)
from ethernity.formats.envelope_types import (
    MANIFEST_VERSION,
    EnvelopeManifest,
    ManifestFile,
    PayloadPart,
)


class TestEnvelope(unittest.TestCase):
    def test_roundtrip(self) -> None:
        payload = b"hello world"
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=1234.0,
            sealed=False,
            signing_seed=None,
            files=(
                ManifestFile(
                    path="payload.bin",
                    size=len(payload),
                    sha256=bytes.fromhex(
                        "64ec88ca00b268e5ba1a35678a1b5316d212f4f366b2477232534a8aeca37f3c"
                    ),
                    mtime=None,
                ),
            ),
        )
        encoded = encode_envelope(payload, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(decoded_payload, payload)
        self.assertEqual(decoded_manifest.format_version, MANIFEST_VERSION)
        self.assertEqual(decoded_manifest.files[0].path, "payload.bin")

    def test_invalid_magic(self) -> None:
        payload = b"data"
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=False,
            signing_seed=None,
            files=(
                ManifestFile(
                    path="payload.bin",
                    size=len(payload),
                    sha256=bytes.fromhex(
                        "3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7"
                    ),
                    mtime=None,
                ),
            ),
        )
        encoded = encode_envelope(payload, manifest)
        corrupted = b"ZZ" + encoded[len(MAGIC) :]
        with self.assertRaises(ValueError):
            decode_envelope(corrupted)

    def test_truncated_payload(self) -> None:
        payload = b"data"
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=False,
            signing_seed=None,
            files=(
                ManifestFile(
                    path="payload.bin",
                    size=len(payload),
                    sha256=bytes.fromhex(
                        "3a6eb0790f39ac87c94f3856b2dd2c5d110e6811602261a9a923d3bb23adc8b7"
                    ),
                    mtime=None,
                ),
            ),
        )
        encoded = encode_envelope(payload, manifest)
        with self.assertRaises(ValueError):
            decode_envelope(encoded[:-1])

    def test_extract_payloads_hash_mismatch(self) -> None:
        payload = b"data"
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=False,
            signing_seed=None,
            files=(
                ManifestFile(
                    path="payload.bin",
                    size=len(payload),
                    sha256=b"\x00" * 32,
                    mtime=None,
                ),
            ),
        )
        with self.assertRaises(ValueError):
            extract_payloads(manifest, payload)

    def test_build_manifest_and_payload_multiple(self) -> None:
        parts = [
            PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),
            PayloadPart(path="beta.txt", data=b"beta", mtime=2),
        ]
        manifest, payload = build_manifest_and_payload(parts, sealed=True, created_at=10.0)
        self.assertEqual(payload, b"alphabeta")
        self.assertEqual(len(manifest.files), 2)
        self.assertEqual(manifest.files[0].path, "alpha.txt")
        self.assertEqual(manifest.files[1].path, "beta.txt")

    def test_prefix_table_roundtrip(self) -> None:
        parts = [
            PayloadPart(path="dir/alpha.txt", data=b"alpha", mtime=1),
            PayloadPart(path="dir/beta.txt", data=b"beta", mtime=2),
        ]
        manifest, payload = build_manifest_and_payload(parts, sealed=False, created_at=1.0)
        encoded = encode_envelope(payload, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(decoded_payload, payload)
        self.assertEqual(
            [file.path for file in decoded_manifest.files],
            ["dir/alpha.txt", "dir/beta.txt"],
        )

    def test_manifest_rejects_invalid_signing_seed(self) -> None:
        data = [
            MANIFEST_VERSION,
            0.0,
            False,
            "not-bytes",
            [""],
            [[0, "payload.bin", 4, b"\x00" * 32, None]],
        ]
        with self.assertRaises(ValueError):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_unsupported_version(self) -> None:
        data = [
            4,
            0.0,
            False,
            None,
            [""],
            [[0, "payload.bin", 4, b"\x00" * 32, None]],
        ]
        with self.assertRaises(ValueError):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_roundtrip_with_signing_seed(self) -> None:
        payload = b"hello"
        parts = [PayloadPart(path="payload.bin", data=payload, mtime=None)]
        signing_seed = b"\x11" * 32
        manifest, payload_out = build_manifest_and_payload(
            parts,
            sealed=False,
            created_at=1.0,
            signing_seed=signing_seed,
        )
        self.assertEqual(payload_out, payload)
        encoded = encode_envelope(payload_out, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(decoded_payload, payload)
        self.assertEqual(decoded_manifest.signing_seed, signing_seed)

    # ==========================================================================
    # Edge Case Tests
    # ==========================================================================

    def test_single_byte_payload(self) -> None:
        """Test envelope with single byte payload."""
        payload = b"X"
        parts = [PayloadPart(path="single.bin", data=payload, mtime=None)]
        manifest, payload_out = build_manifest_and_payload(parts, sealed=False, created_at=0.0)
        encoded = encode_envelope(payload_out, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(decoded_payload, payload)

    def test_large_payload(self) -> None:
        """Test envelope with large payload (1MB)."""
        payload = b"X" * (1024 * 1024)
        parts = [PayloadPart(path="large.bin", data=payload, mtime=None)]
        manifest, payload_out = build_manifest_and_payload(parts, sealed=False, created_at=0.0)
        encoded = encode_envelope(payload_out, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(decoded_payload, payload)
        self.assertEqual(len(decoded_payload), 1024 * 1024)

    def test_many_files_manifest(self) -> None:
        """Test manifest with many files (100)."""
        parts = [
            PayloadPart(path=f"file_{i:03d}.txt", data=f"content {i}".encode(), mtime=i)
            for i in range(100)
        ]
        manifest, payload = build_manifest_and_payload(parts, sealed=False, created_at=0.0)
        self.assertEqual(len(manifest.files), 100)
        encoded = encode_envelope(payload, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(len(decoded_manifest.files), 100)

    def test_empty_parts_raises(self) -> None:
        """Test that empty parts list raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            build_manifest_and_payload([], sealed=False, created_at=0.0)
        self.assertIn("at least one", str(ctx.exception).lower())

    def test_duplicate_paths_raises(self) -> None:
        """Test that duplicate paths raise ValueError."""
        parts = [
            PayloadPart(path="same.txt", data=b"first", mtime=None),
            PayloadPart(path="same.txt", data=b"second", mtime=None),
        ]
        with self.assertRaises(ValueError) as ctx:
            build_manifest_and_payload(parts, sealed=False, created_at=0.0)
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_special_characters_in_path(self) -> None:
        """Test paths with special characters."""
        special_paths = [
            "file with spaces.txt",
            "file-with-dashes.txt",
            "file_with_underscores.txt",
            "dir/subdir/nested.txt",
            "unicode-\u00e9\u00e8.txt",
        ]
        for path in special_paths:
            parts = [PayloadPart(path=path, data=b"content", mtime=None)]
            manifest, payload = build_manifest_and_payload(parts, sealed=False, created_at=0.0)
            encoded = encode_envelope(payload, manifest)
            decoded_manifest, _ = decode_envelope(encoded)
            self.assertEqual(decoded_manifest.files[0].path, path)

    def test_binary_payload_all_bytes(self) -> None:
        """Test payload containing all possible byte values."""
        payload = bytes(range(256))
        parts = [PayloadPart(path="binary.bin", data=payload, mtime=None)]
        manifest, payload_out = build_manifest_and_payload(parts, sealed=False, created_at=0.0)
        encoded = encode_envelope(payload_out, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(decoded_payload, payload)

    def test_extract_payloads_size_mismatch(self) -> None:
        """Test extract_payloads with payload shorter than manifest claims."""
        payload = b"short"
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=False,
            signing_seed=None,
            files=(
                ManifestFile(
                    path="file.bin",
                    size=100,  # Claims 100 bytes, but payload is only 5
                    sha256=b"\x00" * 32,
                    mtime=None,
                ),
            ),
        )
        with self.assertRaises(ValueError) as ctx:
            extract_payloads(manifest, payload)
        self.assertIn("exceeds", str(ctx.exception).lower())

    def test_extract_payloads_total_length_mismatch(self) -> None:
        """Test extract_payloads when payload is longer than manifest total."""
        payload = b"extra data here"
        import hashlib

        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=False,
            signing_seed=None,
            files=(
                ManifestFile(
                    path="file.bin",
                    size=5,
                    sha256=hashlib.sha256(b"extra").digest(),
                    mtime=None,
                ),
            ),
        )
        with self.assertRaises(ValueError) as ctx:
            extract_payloads(manifest, payload)
        self.assertIn("length", str(ctx.exception).lower())

    def test_sealed_manifest(self) -> None:
        """Test manifest with sealed=True."""
        parts = [PayloadPart(path="sealed.bin", data=b"secret", mtime=None)]
        manifest, payload = build_manifest_and_payload(parts, sealed=True, created_at=0.0)
        self.assertTrue(manifest.sealed)
        encoded = encode_envelope(payload, manifest)
        decoded_manifest, _ = decode_envelope(encoded)
        self.assertTrue(decoded_manifest.sealed)

    def test_manifest_with_mtime(self) -> None:
        """Test manifest files preserve mtime."""
        mtime = 1704067200  # 2024-01-01 00:00:00 UTC
        parts = [PayloadPart(path="timed.bin", data=b"data", mtime=mtime)]
        manifest, payload = build_manifest_and_payload(parts, sealed=False, created_at=0.0)
        self.assertEqual(manifest.files[0].mtime, mtime)
        encoded = encode_envelope(payload, manifest)
        decoded_manifest, _ = decode_envelope(encoded)
        self.assertEqual(decoded_manifest.files[0].mtime, mtime)

    def test_manifest_with_none_mtime(self) -> None:
        """Test manifest files with None mtime."""
        parts = [PayloadPart(path="no_mtime.bin", data=b"data", mtime=None)]
        manifest, _ = build_manifest_and_payload(parts, sealed=False, created_at=0.0)
        self.assertIsNone(manifest.files[0].mtime)

    def test_decode_envelope_too_short(self) -> None:
        """Test decoding envelope that's too short."""
        with self.assertRaises(ValueError) as ctx:
            decode_envelope(b"A")
        self.assertIn("short", str(ctx.exception).lower())

    def test_decode_envelope_invalid_version(self) -> None:
        """Test decoding envelope with invalid version."""
        # Manually construct an envelope with wrong version
        import cbor2

        from ethernity.encoding.varint import encode_uvarint

        manifest_data = [
            MANIFEST_VERSION,
            0.0,
            False,
            None,
            [""],
            [[0, "f.bin", 1, b"\x00" * 32, None]],
        ]
        manifest_bytes = cbor2.dumps(manifest_data)
        payload = b"x"
        bad_envelope = (
            MAGIC
            + encode_uvarint(99)  # Invalid version
            + encode_uvarint(len(manifest_bytes))
            + manifest_bytes
            + encode_uvarint(len(payload))
            + payload
        )
        with self.assertRaises(ValueError) as ctx:
            decode_envelope(bad_envelope)
        self.assertIn("version", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
