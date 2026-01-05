import unittest

from ethernity.formats.envelope_codec import (
    MAGIC,
    build_manifest_and_payload,
    decode_envelope,
    encode_envelope,
    extract_payloads,
)
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile, MANIFEST_VERSION, PayloadPart


class TestEnvelope(unittest.TestCase):
    def test_roundtrip(self) -> None:
        payload = b"hello world"
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=1234.0,
            sealed=False,
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


if __name__ == "__main__":
    unittest.main()
