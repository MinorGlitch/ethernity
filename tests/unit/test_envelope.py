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

import hashlib
import unicodedata
import unittest
from unittest import mock

import cbor2

from ethernity.core.bounds import MAX_MANIFEST_CBOR_BYTES, MAX_MANIFEST_FILES
from ethernity.encoding.varint import encode_uvarint
from ethernity.formats.envelope_codec import (
    MAGIC,
    build_manifest_and_payload,
    decode_envelope,
    decode_manifest,
    encode_envelope,
    encode_manifest,
    extract_payloads,
)
from ethernity.formats.envelope_types import (
    MANIFEST_VERSION,
    PATH_ENCODING_DIRECT,
    PATH_ENCODING_PREFIX_TABLE,
    EnvelopeManifest,
    ManifestFile,
    PayloadPart,
)

TEST_SIGNING_SEED = b"\x11" * 32


def _make_manifest_file_entry(
    *,
    path: str = "payload.bin",
    size: int = 4,
    hash_value: object = b"\x00" * 32,
    mtime: object = None,
    prefix_index: int | None = None,
    suffix: str | None = None,
) -> list[object]:
    if prefix_index is None:
        return [path, size, hash_value, mtime]
    resolved_suffix = suffix if suffix is not None else path
    return [prefix_index, resolved_suffix, size, hash_value, mtime]


def _make_manifest_cbor(
    *,
    version: int = MANIFEST_VERSION,
    created: float = 0.0,
    sealed: bool = False,
    seed: object = TEST_SIGNING_SEED,
    input_origin: object = "file",
    input_roots: object | None = None,
    path_encoding: object = PATH_ENCODING_DIRECT,
    path_prefixes: object | None = None,
    files: list[list[object]] | None = None,
) -> dict[str, object]:
    if input_roots is None:
        if input_origin in {"directory", "mixed"}:
            input_roots = ["root"]
        else:
            input_roots = []
    if files is None:
        if path_encoding == PATH_ENCODING_PREFIX_TABLE:
            files = [_make_manifest_file_entry(prefix_index=0, suffix="payload.bin")]
        else:
            files = [_make_manifest_file_entry()]
    return {
        "version": version,
        "created": created,
        "sealed": sealed,
        "seed": seed,
        "input_origin": input_origin,
        "input_roots": input_roots,
        "path_encoding": path_encoding,
        "path_prefixes": path_prefixes if path_prefixes is not None else [""],
        "files": files,
    }


class TestEnvelope(unittest.TestCase):
    def test_encode_manifest_rejects_empty_files(self) -> None:
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=True,
            signing_seed=None,
            files=(),
        )
        with self.assertRaises(ValueError) as ctx:
            encode_manifest(manifest)
        self.assertIn("files", str(ctx.exception).lower())

    def test_manifest_encodes_to_map(self) -> None:
        payload = b"hello world"
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=1234.0,
            sealed=False,
            signing_seed=TEST_SIGNING_SEED,
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
        encoded = encode_manifest(manifest)
        decoded = cbor2.loads(encoded)
        self.assertIsInstance(decoded, dict)
        self.assertEqual(decoded["version"], MANIFEST_VERSION)
        self.assertEqual(decoded["input_origin"], "file")
        self.assertEqual(decoded["input_roots"], [])
        self.assertEqual(decoded["path_encoding"], PATH_ENCODING_DIRECT)
        self.assertIn("files", decoded)
        self.assertIsInstance(decoded["files"][0], list)

    def test_manifest_adaptive_encoding_chooses_direct_for_flat_paths(self) -> None:
        parts = [
            PayloadPart(path=f"file_{index:03d}.txt", data=b"x", mtime=index) for index in range(80)
        ]
        manifest, payload = build_manifest_and_payload(
            parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
        )
        encoded = encode_manifest(manifest)
        decoded = cbor2.loads(encoded)
        self.assertEqual(decoded["path_encoding"], PATH_ENCODING_DIRECT)
        self.assertNotIn("path_prefixes", decoded)

        roundtrip_manifest, roundtrip_payload = decode_envelope(encode_envelope(payload, manifest))
        self.assertEqual(roundtrip_payload, payload)
        self.assertEqual(len(roundtrip_manifest.files), 80)

    def test_manifest_adaptive_encoding_chooses_prefix_for_shared_deep_paths(self) -> None:
        parts = [
            PayloadPart(
                path=f"project/docs/sub/section/file_{index:03d}.txt",
                data=b"x",
                mtime=index,
            )
            for index in range(80)
        ]
        manifest, payload = build_manifest_and_payload(
            parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
        )
        encoded = encode_manifest(manifest)
        decoded = cbor2.loads(encoded)
        self.assertEqual(decoded["path_encoding"], PATH_ENCODING_PREFIX_TABLE)
        self.assertIn("path_prefixes", decoded)
        self.assertTrue(decoded["path_prefixes"])
        self.assertEqual(decoded["path_prefixes"][0], "")

        roundtrip_manifest, roundtrip_payload = decode_envelope(encode_envelope(payload, manifest))
        self.assertEqual(roundtrip_payload, payload)
        self.assertEqual(roundtrip_manifest.files[0].path, "project/docs/sub/section/file_000.txt")

    @mock.patch("ethernity.formats.envelope_types.dumps_canonical")
    def test_manifest_encoding_tie_breaker_prefers_direct(
        self, dumps_canonical: mock.MagicMock
    ) -> None:
        dumps_canonical.side_effect = [b"ab", b"cd"]
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=1.0,
            sealed=False,
            signing_seed=TEST_SIGNING_SEED,
            files=(
                ManifestFile(
                    path="docs/file.txt",
                    size=1,
                    sha256=hashlib.sha256(b"x").digest(),
                    mtime=None,
                ),
            ),
        )
        encoded = manifest.to_cbor()
        self.assertEqual(encoded["path_encoding"], PATH_ENCODING_DIRECT)

    def test_manifest_encoding_is_deterministic(self) -> None:
        payload = b"hello world"
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=1234.0,
            sealed=False,
            signing_seed=TEST_SIGNING_SEED,
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
        first = encode_manifest(manifest)
        second = encode_manifest(manifest)
        self.assertEqual(first, second)

    def test_roundtrip(self) -> None:
        payload = b"hello world"
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=1234.0,
            sealed=False,
            signing_seed=TEST_SIGNING_SEED,
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
            signing_seed=TEST_SIGNING_SEED,
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
            signing_seed=TEST_SIGNING_SEED,
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
            signing_seed=TEST_SIGNING_SEED,
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

    def test_build_manifest_and_payload_sorts_by_path(self) -> None:
        parts = [
            PayloadPart(path="beta.txt", data=b"beta", mtime=2),
            PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),
        ]
        manifest, payload = build_manifest_and_payload(parts, sealed=True, created_at=10.0)
        self.assertEqual(payload, b"alphabeta")
        self.assertEqual([file.path for file in manifest.files], ["alpha.txt", "beta.txt"])

    def test_path_roundtrip(self) -> None:
        parts = [
            PayloadPart(path="dir/alpha.txt", data=b"alpha", mtime=1),
            PayloadPart(path="dir/beta.txt", data=b"beta", mtime=2),
        ]
        manifest, payload = build_manifest_and_payload(
            parts, sealed=False, created_at=1.0, signing_seed=TEST_SIGNING_SEED
        )
        encoded = encode_envelope(payload, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(decoded_payload, payload)
        self.assertEqual(
            [file.path for file in decoded_manifest.files],
            ["dir/alpha.txt", "dir/beta.txt"],
        )

    def test_manifest_prefix_table_manual_roundtrip(self) -> None:
        data = _make_manifest_cbor(
            sealed=True,
            seed=None,
            path_encoding=PATH_ENCODING_PREFIX_TABLE,
            path_prefixes=["", "dir"],
            files=[
                _make_manifest_file_entry(prefix_index=1, suffix="alpha.txt", mtime=1),
                _make_manifest_file_entry(prefix_index=1, suffix="beta.txt", mtime=2),
            ],
        )
        manifest = EnvelopeManifest.from_cbor(data)
        self.assertEqual(
            [entry.path for entry in manifest.files],
            ["dir/alpha.txt", "dir/beta.txt"],
        )

    def test_manifest_normalizes_paths_to_nfc(self) -> None:
        composed = "caf\u00e9.txt"
        decomposed = "cafe\u0301.txt"
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(unicodedata.normalize("NFC", decomposed), composed)

        parts = [PayloadPart(path=decomposed, data=b"x", mtime=None)]
        manifest, payload = build_manifest_and_payload(
            parts,
            sealed=True,
            created_at=0.0,
        )
        self.assertEqual(manifest.files[0].path, composed)

        encoded = encode_envelope(payload, manifest)
        decoded_manifest, _ = decode_envelope(encoded)
        self.assertEqual(decoded_manifest.files[0].path, composed)

    def test_manifest_duplicate_paths_after_normalization_raise(self) -> None:
        composed = "caf\u00e9.txt"
        decomposed = "cafe\u0301.txt"
        parts = [
            PayloadPart(path=composed, data=b"a", mtime=None),
            PayloadPart(path=decomposed, data=b"b", mtime=None),
        ]
        with self.assertRaises(ValueError):
            build_manifest_and_payload(parts, sealed=True, created_at=0.0)

    def test_manifest_rejects_invalid_utf8_paths(self) -> None:
        parts = [PayloadPart(path="bad\udcff.txt", data=b"x", mtime=None)]
        with self.assertRaises(ValueError):
            build_manifest_and_payload(parts, sealed=True, created_at=0.0)

    def test_manifest_builder_rejects_absolute_paths(self) -> None:
        parts = [PayloadPart(path="/abs/file.txt", data=b"x", mtime=None)]
        with self.assertRaises(ValueError) as ctx:
            build_manifest_and_payload(parts, sealed=True, created_at=0.0)
        self.assertIn("relative", str(ctx.exception))

    def test_manifest_builder_rejects_backslash_paths(self) -> None:
        parts = [PayloadPart(path=r"dir\file.txt", data=b"x", mtime=None)]
        with self.assertRaises(ValueError) as ctx:
            build_manifest_and_payload(parts, sealed=True, created_at=0.0)
        self.assertIn("POSIX separators", str(ctx.exception))

    def test_manifest_builder_rejects_dotdot_segments(self) -> None:
        parts = [PayloadPart(path="dir/../file.txt", data=b"x", mtime=None)]
        with self.assertRaises(ValueError) as ctx:
            build_manifest_and_payload(parts, sealed=True, created_at=0.0)
        self.assertIn("'.' or '..'", str(ctx.exception))

    def test_manifest_builder_rejects_empty_segments(self) -> None:
        parts = [PayloadPart(path="dir//file.txt", data=b"x", mtime=None)]
        with self.assertRaises(ValueError) as ctx:
            build_manifest_and_payload(parts, sealed=True, created_at=0.0)
        self.assertIn("empty path segments", str(ctx.exception))

    def test_manifest_ascii_paths_unchanged(self) -> None:
        parts = [PayloadPart(path="docs/file.txt", data=b"x", mtime=None)]
        manifest, _ = build_manifest_and_payload(parts, sealed=True, created_at=0.0)
        self.assertEqual(manifest.files[0].path, "docs/file.txt")

    def test_manifest_decoder_normalizes_paths_to_nfc(self) -> None:
        composed = "caf\u00e9.txt"
        decomposed = "cafe\u0301.txt"
        data = _make_manifest_cbor(
            sealed=True,
            seed=None,
            files=[_make_manifest_file_entry(path=decomposed)],
        )
        manifest = EnvelopeManifest.from_cbor(data)
        self.assertEqual(manifest.files[0].path, composed)

    def test_manifest_decoder_rejects_duplicate_paths_after_normalization(self) -> None:
        composed = "caf\u00e9.txt"
        decomposed = "cafe\u0301.txt"
        data = _make_manifest_cbor(
            sealed=True,
            seed=None,
            files=[
                _make_manifest_file_entry(path=composed),
                _make_manifest_file_entry(path=decomposed),
            ],
        )
        with self.assertRaises(ValueError):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_decoder_rejects_absolute_paths(self) -> None:
        data = _make_manifest_cbor(
            sealed=True,
            seed=None,
            files=[_make_manifest_file_entry(path="/abs/file.txt")],
        )
        with self.assertRaises(ValueError) as ctx:
            EnvelopeManifest.from_cbor(data)
        self.assertIn("relative", str(ctx.exception))

    def test_manifest_decoder_rejects_backslash_paths(self) -> None:
        data = _make_manifest_cbor(
            sealed=True,
            seed=None,
            files=[_make_manifest_file_entry(path=r"dir\file.txt")],
        )
        with self.assertRaises(ValueError) as ctx:
            EnvelopeManifest.from_cbor(data)
        self.assertIn("POSIX separators", str(ctx.exception))

    def test_manifest_decoder_rejects_dotdot_segments(self) -> None:
        data = _make_manifest_cbor(
            sealed=True,
            seed=None,
            files=[_make_manifest_file_entry(path="dir/../file.txt")],
        )
        with self.assertRaises(ValueError) as ctx:
            EnvelopeManifest.from_cbor(data)
        self.assertIn("'.' or '..'", str(ctx.exception))

    def test_manifest_decoder_rejects_empty_segments(self) -> None:
        data = _make_manifest_cbor(
            sealed=True,
            seed=None,
            files=[_make_manifest_file_entry(path="dir//file.txt")],
        )
        with self.assertRaises(ValueError) as ctx:
            EnvelopeManifest.from_cbor(data)
        self.assertIn("empty path segments", str(ctx.exception))

    def test_manifest_rejects_invalid_signing_seed(self) -> None:
        data = _make_manifest_cbor(seed="not-bytes")
        with self.assertRaises(ValueError):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_requires_input_origin(self) -> None:
        data = _make_manifest_cbor()
        del data["input_origin"]
        with self.assertRaisesRegex(ValueError, "input_origin"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_invalid_input_origin(self) -> None:
        data = _make_manifest_cbor(input_origin="archive")
        with self.assertRaisesRegex(ValueError, "input_origin"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_requires_input_roots(self) -> None:
        data = _make_manifest_cbor()
        del data["input_roots"]
        with self.assertRaisesRegex(ValueError, "input_roots"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_requires_path_encoding(self) -> None:
        data = _make_manifest_cbor()
        del data["path_encoding"]
        with self.assertRaisesRegex(ValueError, "path_encoding"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_invalid_path_encoding(self) -> None:
        data = _make_manifest_cbor(path_encoding="legacy")
        with self.assertRaisesRegex(ValueError, "path_encoding"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_prefix_table_requires_path_prefixes(self) -> None:
        data = _make_manifest_cbor(path_encoding=PATH_ENCODING_PREFIX_TABLE)
        del data["path_prefixes"]
        with self.assertRaisesRegex(ValueError, "path_prefixes"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_invalid_path_prefixes_shape(self) -> None:
        data = _make_manifest_cbor(
            path_encoding=PATH_ENCODING_PREFIX_TABLE,
            path_prefixes="not-a-list",
        )
        with self.assertRaisesRegex(ValueError, "path_prefixes"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_invalid_path_prefixes_values(self) -> None:
        data = _make_manifest_cbor(
            path_encoding=PATH_ENCODING_PREFIX_TABLE,
            path_prefixes=["", "dir//name"],
            files=[_make_manifest_file_entry(prefix_index=1, suffix="payload.bin")],
        )
        with self.assertRaisesRegex(ValueError, "path_prefix"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_prefix_index_out_of_range(self) -> None:
        data = _make_manifest_cbor(
            path_encoding=PATH_ENCODING_PREFIX_TABLE,
            path_prefixes=[""],
            files=[_make_manifest_file_entry(prefix_index=1, suffix="payload.bin")],
        )
        with self.assertRaisesRegex(ValueError, "prefix_index"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_legacy_map_file_entries(self) -> None:
        data = _make_manifest_cbor(
            path_encoding=PATH_ENCODING_DIRECT,
            files=[
                {
                    "path": "payload.bin",
                    "size": 4,
                    "hash": b"\x00" * 32,
                    "mtime": None,
                }
            ],
        )
        with self.assertRaisesRegex(ValueError, "array encoding"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_invalid_input_roots_shape(self) -> None:
        data = _make_manifest_cbor(input_roots="root")
        with self.assertRaisesRegex(ValueError, "input_roots"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_invalid_input_root_label(self) -> None:
        data = _make_manifest_cbor(input_roots=["dir/name"])
        with self.assertRaisesRegex(ValueError, "input_root"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_accepts_directory_and_mixed_input_origin(self) -> None:
        data = _make_manifest_cbor(input_origin="directory", input_roots=["vault"])
        directory_manifest = EnvelopeManifest.from_cbor(data)
        self.assertEqual(directory_manifest.input_origin, "directory")
        self.assertEqual(directory_manifest.input_roots, ("vault",))

        data = _make_manifest_cbor(input_origin="mixed", input_roots=["vault"])
        mixed_manifest = EnvelopeManifest.from_cbor(data)
        self.assertEqual(mixed_manifest.input_origin, "mixed")
        self.assertEqual(mixed_manifest.input_roots, ("vault",))

    def test_manifest_rejects_file_origin_with_input_roots(self) -> None:
        data = _make_manifest_cbor(input_origin="file", input_roots=["vault"])
        with self.assertRaisesRegex(ValueError, "input_roots"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_rejects_directory_or_mixed_without_input_roots(self) -> None:
        data = _make_manifest_cbor(input_origin="directory", input_roots=[])
        with self.assertRaisesRegex(ValueError, "input_roots"):
            EnvelopeManifest.from_cbor(data)
        data = _make_manifest_cbor(input_origin="mixed", input_roots=[])
        with self.assertRaisesRegex(ValueError, "input_roots"):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_ignores_unknown_keys(self) -> None:
        data = _make_manifest_cbor()
        data["extra"] = 123
        manifest = EnvelopeManifest.from_cbor(data)
        self.assertEqual(manifest.format_version, MANIFEST_VERSION)
        self.assertEqual(manifest.signing_seed, TEST_SIGNING_SEED)

    def test_manifest_decoder_rejects_non_canonical_cbor(self) -> None:
        data = _make_manifest_cbor()
        non_canonical = cbor2.dumps(data, canonical=False)
        canonical = cbor2.dumps(data, canonical=True)
        self.assertNotEqual(non_canonical, canonical)
        with self.assertRaisesRegex(ValueError, "canonical CBOR"):
            decode_manifest(non_canonical)

    def test_manifest_rejects_hex_sha256(self) -> None:
        data = _make_manifest_cbor(files=[_make_manifest_file_entry(hash_value="00" * 32)])
        with self.assertRaises(ValueError) as ctx:
            EnvelopeManifest.from_cbor(data)
        self.assertIn("hash", str(ctx.exception).lower())

    def test_manifest_rejects_unsupported_version(self) -> None:
        data = _make_manifest_cbor(version=4)
        with self.assertRaises(ValueError):
            EnvelopeManifest.from_cbor(data)

    def test_manifest_requires_seed_when_unsealed(self) -> None:
        data = _make_manifest_cbor(seed=None)
        with self.assertRaises(ValueError):
            EnvelopeManifest.from_cbor(data)

    def test_encode_manifest_respects_manifest_cbor_bound(self) -> None:
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=True,
            signing_seed=None,
            files=(
                ManifestFile(
                    path="payload.bin",
                    size=1,
                    sha256=hashlib.sha256(b"x").digest(),
                    mtime=None,
                ),
            ),
        )
        encoded = encode_manifest(manifest)
        self.assertLessEqual(len(encoded), MAX_MANIFEST_CBOR_BYTES)
        with mock.patch(
            "ethernity.formats.envelope_codec.MAX_MANIFEST_CBOR_BYTES",
            len(encoded),
        ):
            self.assertEqual(encode_manifest(manifest), encoded)
        with mock.patch(
            "ethernity.formats.envelope_codec.MAX_MANIFEST_CBOR_BYTES",
            len(encoded) - 1,
        ):
            with self.assertRaisesRegex(ValueError, "MAX_MANIFEST_CBOR_BYTES"):
                encode_manifest(manifest)

    def test_decode_manifest_rejects_manifest_cbor_bound_overflow(self) -> None:
        oversize_bytes = b"\x00" * (MAX_MANIFEST_CBOR_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "MAX_MANIFEST_CBOR_BYTES"):
            decode_manifest(oversize_bytes)

    def test_manifest_accepts_max_files(self) -> None:
        files = tuple(
            ManifestFile(
                path=f"f{i}.txt",
                size=1,
                sha256=hashlib.sha256(bytes([i % 256])).digest(),
                mtime=None,
            )
            for i in range(MAX_MANIFEST_FILES)
        )
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=True,
            signing_seed=None,
            files=files,
        )
        encoded = encode_manifest(manifest)
        decoded = decode_manifest(encoded)
        self.assertEqual(len(decoded.files), MAX_MANIFEST_FILES)

    def test_manifest_rejects_more_than_max_files(self) -> None:
        files = tuple(
            ManifestFile(
                path=f"f{i}.txt",
                size=1,
                sha256=hashlib.sha256(bytes([i % 256])).digest(),
                mtime=None,
            )
            for i in range(MAX_MANIFEST_FILES + 1)
        )
        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=True,
            signing_seed=None,
            files=files,
        )
        with self.assertRaisesRegex(ValueError, "MAX_MANIFEST_FILES"):
            encode_manifest(manifest)

    def test_manifest_rejects_seed_when_sealed(self) -> None:
        data = _make_manifest_cbor(sealed=True, seed=TEST_SIGNING_SEED)
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
        manifest, payload_out = build_manifest_and_payload(
            parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
        )
        encoded = encode_envelope(payload_out, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(decoded_payload, payload)

    def test_large_payload(self) -> None:
        """Test envelope with large payload (1MB)."""
        payload = b"X" * (1024 * 1024)
        parts = [PayloadPart(path="large.bin", data=payload, mtime=None)]
        manifest, payload_out = build_manifest_and_payload(
            parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
        )
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
        manifest, payload = build_manifest_and_payload(
            parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
        )
        self.assertEqual(len(manifest.files), 100)
        encoded = encode_envelope(payload, manifest)
        decoded_manifest, decoded_payload = decode_envelope(encoded)
        self.assertEqual(len(decoded_manifest.files), 100)

    def test_empty_parts_raises(self) -> None:
        """Test that empty parts list raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            build_manifest_and_payload([], sealed=False, created_at=0.0)
        self.assertIn("at least one", str(ctx.exception).lower())

    def test_decode_envelope_rejects_empty_files(self) -> None:
        manifest_data = _make_manifest_cbor(sealed=True, seed=None, files=[])
        manifest_bytes = cbor2.dumps(manifest_data, canonical=True)
        payload = b""
        encoded = (
            MAGIC
            + encode_uvarint(1)
            + encode_uvarint(len(manifest_bytes))
            + manifest_bytes
            + encode_uvarint(len(payload))
            + payload
        )
        with self.assertRaises(ValueError) as ctx:
            decode_envelope(encoded)
        self.assertIn("files", str(ctx.exception).lower())

    def test_duplicate_paths_raises(self) -> None:
        """Test that duplicate paths raise ValueError."""
        parts = [
            PayloadPart(path="same.txt", data=b"first", mtime=None),
            PayloadPart(path="same.txt", data=b"second", mtime=None),
        ]
        with self.assertRaises(ValueError) as ctx:
            build_manifest_and_payload(
                parts,
                sealed=False,
                created_at=0.0,
                signing_seed=TEST_SIGNING_SEED,
            )
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
            manifest, payload = build_manifest_and_payload(
                parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
            )
            encoded = encode_envelope(payload, manifest)
            decoded_manifest, _ = decode_envelope(encoded)
            self.assertEqual(decoded_manifest.files[0].path, path)

    def test_binary_payload_all_bytes(self) -> None:
        """Test payload containing all possible byte values."""
        payload = bytes(range(256))
        parts = [PayloadPart(path="binary.bin", data=payload, mtime=None)]
        manifest, payload_out = build_manifest_and_payload(
            parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
        )
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
            signing_seed=TEST_SIGNING_SEED,
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

        manifest = EnvelopeManifest(
            format_version=MANIFEST_VERSION,
            created_at=0.0,
            sealed=False,
            signing_seed=TEST_SIGNING_SEED,
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
        manifest, payload = build_manifest_and_payload(
            parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
        )
        self.assertEqual(manifest.files[0].mtime, mtime)
        encoded = encode_envelope(payload, manifest)
        decoded_manifest, _ = decode_envelope(encoded)
        self.assertEqual(decoded_manifest.files[0].mtime, mtime)

    def test_manifest_with_none_mtime(self) -> None:
        """Test manifest files with None mtime."""
        parts = [PayloadPart(path="no_mtime.bin", data=b"data", mtime=None)]
        manifest, _ = build_manifest_and_payload(
            parts, sealed=False, created_at=0.0, signing_seed=TEST_SIGNING_SEED
        )
        self.assertIsNone(manifest.files[0].mtime)

    def test_decode_envelope_too_short(self) -> None:
        """Test decoding envelope that's too short."""
        with self.assertRaises(ValueError) as ctx:
            decode_envelope(b"A")
        self.assertIn("short", str(ctx.exception).lower())

    def test_decode_envelope_invalid_version(self) -> None:
        """Test decoding envelope with invalid version."""
        # Manually construct an envelope with wrong version
        manifest_data = _make_manifest_cbor(
            sealed=True,
            seed=None,
            files=[_make_manifest_file_entry(path="f.bin", size=1)],
        )
        manifest_bytes = cbor2.dumps(manifest_data, canonical=True)
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

    def test_decode_envelope_rejects_non_canonical_version_varint(self) -> None:
        manifest_data = _make_manifest_cbor(
            sealed=True,
            seed=None,
            files=[_make_manifest_file_entry(path="f.bin", size=1)],
        )
        manifest_bytes = cbor2.dumps(manifest_data, canonical=True)
        payload = b"x"
        encoded = (
            MAGIC
            + encode_uvarint(1)
            + encode_uvarint(len(manifest_bytes))
            + manifest_bytes
            + encode_uvarint(len(payload))
            + payload
        )
        # Replace canonical VERSION=1 (0x01) with overlong encoding (0x81 0x00).
        non_canonical = encoded[:2] + b"\x81\x00" + encoded[3:]
        with self.assertRaisesRegex(ValueError, "non-canonical varint"):
            decode_envelope(non_canonical)


if __name__ == "__main__":
    unittest.main()
