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

import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.qr.codec import QrConfig, make_qr
from ethernity.workflows.kit import printed, service as kit_module

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestKitFlowHelpers(unittest.TestCase):
    def test_build_kit_qr_payloads_startup_first_and_numbered_data_within_budget(self) -> None:
        bundle = b'<script>const p="' + b"A" * 200 + b'";</script>'
        first = kit_module.build_kit_qr_payloads(bundle, 180, QrConfig())
        second = kit_module.build_kit_qr_payloads(bundle, 120, QrConfig())
        for payloads, limit in ((first, 180), (second, 120)):
            self.assertTrue(payloads[0].startswith(b"<!doctype html"))
            self.assertIn(b"<textarea hidden id=code>", payloads[0])
            self.assertTrue(all(len(part) <= limit for part in payloads[2:]))
            self.assertTrue(all(part.startswith(b"EK1:") for part in payloads[2:]))
            self.assertTrue(set(b"".join(payloads[2:]).decode()) <= set(printed.BASE44_ALPHABET))
        self.assertEqual(
            b"".join(p[printed.HEADER_SIZE :] for p in first[2:]),
            b"".join(p[printed.HEADER_SIZE :] for p in second[2:]),
        )
        self.assertNotEqual(len(first), len(second))
        self.assertNotEqual(first[2][4:16], second[2][4:16])

    def test_build_kit_qr_payloads_validates_startup_and_data_capacity(self) -> None:
        with mock.patch.object(printed, "fits_qr_payload", side_effect=[True, True, False]):
            with self.assertRaisesRegex(ValueError, "chunk_size is too large"):
                printed.build_payloads(b"abc", "gzip", 120, QrConfig())
        with mock.patch.object(printed, "fits_qr_payload", return_value=False):
            with self.assertRaisesRegex(ValueError, "startup codes"):
                printed.build_payloads(b"abc", "gzip", 120, QrConfig())

    def test_printed_kit_identity_separates_encoding_and_partitioning(self) -> None:
        data = b"abc"
        size = 120
        payload = printed.build_payloads(data, "gzip", size, QrConfig())[2]
        identifier = payload.split(b":")[1].decode()
        digest_input = data + size.to_bytes(4, "big")

        self.assertEqual(
            identifier, hashlib.sha256(b"base44-15" + digest_input).hexdigest()[:12].upper()
        )
        self.assertNotEqual(identifier, hashlib.sha256(digest_input).hexdigest()[:12].upper())

    def test_max_qr_payload_bytes_binary_search(self) -> None:
        cfg = QrConfig()

        def _fits(payload: bytes, _cfg: QrConfig) -> bool:
            return len(payload) <= 10

        with mock.patch("ethernity.workflows.kit.service.fits_qr_payload", side_effect=_fits):
            self.assertEqual(kit_module._max_qr_payload_bytes(b"x" * 100, cfg), 10)

    def test_max_qr_payload_bytes_rejects_no_capacity(self) -> None:
        with mock.patch("ethernity.workflows.kit.service.fits_qr_payload", return_value=False):
            with self.assertRaisesRegex(ValueError, "cannot encode any payload bytes"):
                kit_module._max_qr_payload_bytes(b"x", QrConfig())

    def test_load_kit_bundle_package_and_dev_fallback(self) -> None:
        fake_package = mock.Mock()
        fake_join = mock.Mock()
        fake_join.read_bytes.return_value = b"pkg"
        fake_package.joinpath.return_value = fake_join
        with mock.patch("ethernity.workflows.kit.service.files", return_value=fake_package):
            self.assertEqual(kit_module._load_kit_bundle(), b"pkg")
            fake_package.joinpath.assert_called_with("kit", kit_module.DEFAULT_KIT_BUNDLE_NAME)

        fake_package_scanner = mock.Mock()
        fake_join_scanner = mock.Mock()
        fake_join_scanner.read_bytes.return_value = b"scanner-pkg"
        fake_package_scanner.joinpath.return_value = fake_join_scanner
        with mock.patch("ethernity.workflows.kit.service.files", return_value=fake_package_scanner):
            self.assertEqual(kit_module._load_kit_bundle(variant="scanner"), b"scanner-pkg")
            fake_package_scanner.joinpath.assert_called_with(
                "kit", kit_module.SCANNER_KIT_BUNDLE_NAME
            )

        with tempfile.TemporaryDirectory() as tmp:
            dev_dist_root = Path(tmp) / "kit" / "dist"
            dev_dist_root.mkdir(parents=True)
            candidate = dev_dist_root / kit_module.DEFAULT_KIT_BUNDLE_NAME
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(b"dev")
            with mock.patch("ethernity.workflows.kit.service.files", side_effect=FileNotFoundError):
                with mock.patch(
                    "ethernity.workflows.kit.service._DEV_KIT_DIST_ROOT", dev_dist_root
                ):
                    self.assertEqual(kit_module._load_kit_bundle(), b"dev")

            scanner_candidate = dev_dist_root / kit_module.SCANNER_KIT_BUNDLE_NAME
            scanner_candidate.write_bytes(b"scanner-dev")
            with mock.patch("ethernity.workflows.kit.service.files", side_effect=FileNotFoundError):
                with mock.patch(
                    "ethernity.workflows.kit.service._DEV_KIT_DIST_ROOT", dev_dist_root
                ):
                    self.assertEqual(kit_module._load_kit_bundle(variant="scanner"), b"scanner-dev")
            scanner_candidate.unlink()

            candidate.unlink()
            with mock.patch(
                "ethernity.workflows.kit.service.files", side_effect=ModuleNotFoundError
            ):
                with mock.patch(
                    "ethernity.workflows.kit.service._DEV_KIT_DIST_ROOT", dev_dist_root
                ):
                    with self.assertRaisesRegex(FileNotFoundError, "Recovery kit bundle not found"):
                        kit_module._load_kit_bundle()

    def test_load_kit_bundle_rejects_invalid_variant(self) -> None:
        with self.assertRaisesRegex(ValueError, "variant must be 'lean' or 'scanner'"):
            kit_module._load_kit_bundle(variant="weird")

    def test_extract_kit_bundle_loader_payload_accepts_js_string_variants(self) -> None:
        let_bundle = b"<script>let p = 'abc\\u003cdef';</script>"
        var_bundle = b'<script>var p="abc\\u003cdef";</script>'

        self.assertEqual(
            kit_module._extract_kit_bundle_loader_metadata(let_bundle).payload, "abc<def"
        )
        self.assertEqual(
            kit_module._extract_kit_bundle_loader_metadata(var_bundle).payload, "abc<def"
        )

    def test_extract_kit_bundle_loader_metadata_preserves_brotli_compression(self) -> None:
        bundle = b'<script>const p="abc";const f="brotli";</script>'

        metadata = kit_module._extract_kit_bundle_loader_metadata(bundle)
        shell = printed.build_payloads(b"abc", metadata.compression, 1800, QrConfig())[0]

        self.assertEqual(metadata.payload, "abc")
        self.assertEqual(metadata.compression, "brotli")
        self.assertIn(b',"brotli"]', shell)

    def test_reusable_kit_shell_has_no_chain_specific_identity(self) -> None:
        shell = printed.build_payloads(b"abc", "gzip", 1800, QrConfig())[0]

        self.assertNotIn(b"expected_latest_head_hash", shell)

    def test_extract_kit_bundle_loader_metadata_accepts_minified_comma_declarations(
        self,
    ) -> None:
        alphabet = json.dumps(kit_module._BASE91_ALPHABET)
        bundle = (
            f'<script>(async()=>{{const p="abc",a={alphabet},f="brotli",h="fallback"}})()</script>'
        ).encode()

        metadata = kit_module._extract_kit_bundle_loader_metadata(bundle)

        self.assertEqual(metadata.payload, "abc")
        self.assertEqual(metadata.compression, "brotli")

    def test_extract_kit_bundle_loader_metadata_accepts_generated_bundles(self) -> None:
        bundle_paths = [
            _PROJECT_ROOT / "src/ethernity/resources/kit/recovery_kit.bundle.html",
            _PROJECT_ROOT / "src/ethernity/resources/kit/recovery_kit.scanner.bundle.html",
        ]

        for bundle_path in bundle_paths:
            metadata = kit_module._extract_kit_bundle_loader_metadata(bundle_path.read_bytes())

            self.assertGreater(len(metadata.payload), 1000)
            self.assertEqual(metadata.compression, "gzip")
            compressed = kit_module._decode_base91(metadata.payload, metadata.alphabet)
            raw = gzip.decompress(compressed)
            raw_path = (
                _PROJECT_ROOT / "kit/dist" / bundle_path.name.replace(".html", ".packed.html")
            )
            self.assertEqual(raw.strip(), raw_path.read_bytes().strip())

    def test_base44_vectors_preserve_block_width_and_byte_order(self) -> None:
        for data, encoded in (
            (b"", ""),
            (b"\x00", "00"),
            (b"\xff", "Z5"),
            (b"\x00\x00", "000"),
            (b"\xff\xff", "J%X"),
            (b"ABC", "34961"),
            (bytes(15), "0000000000000000000000"),
            (b"\xff" * 15, "BNCN-7AMTDEDHLTWA/Q:$-"),
            (bytes(range(16)), "/7VBLW5EV/X/+D344M9100F0"),
        ):
            with self.subTest(data=data):
                self.assertEqual(printed.encode_base44(data), encoded)

    def test_base44_blocks_reduce_text_without_enlarging_symbols(self) -> None:
        old_qr = make_qr(b"x" * 1200)
        data = bytes(range(256)) * 4 + bytes(range(176))
        payload = printed.encode_base44(data).encode("ascii")
        self.assertEqual(len(payload), 1760)
        new_qr = make_qr(payload)
        self.assertEqual(new_qr.mode, "alphanumeric")
        self.assertEqual((new_qr.version, new_qr.error), (old_qr.version, old_qr.error))

    def test_default_data_codes_fill_the_same_symbol_without_reducing_correction(self) -> None:
        size = kit_module.DEFAULT_KIT_CHUNK_SIZE
        payloads = printed.build_payloads(bytes(range(256)) * 8, "gzip", size, QrConfig())
        payload = payloads[2]
        previous = make_qr(b"A" * 1800)
        current = make_qr(payload)

        self.assertEqual(len(payload), size)
        self.assertEqual((current.version, current.error, current.mode), (29, "M", "alphanumeric"))
        self.assertEqual(current.symbol_size(), previous.symbol_size())
        with self.assertRaisesRegex(ValueError, "does not fit"):
            make_qr(payload + b"A", version=29, error="M")

    def test_capacity_probe_respects_custom_qr_version_and_correction(self) -> None:
        for config in (QrConfig(version=20), QrConfig(version=29, error="H")):
            with self.subTest(config=config):
                probe = b"A" * kit_module.DEFAULT_KIT_CHUNK_SIZE
                capacity = kit_module._max_qr_payload_bytes(probe, config)
                self.assertLess(capacity, len(probe))
                qr = make_qr(probe[:capacity], version=config.version, error=config.error)
                self.assertEqual((qr.version, qr.error), (config.version, config.error))
                with self.assertRaisesRegex(ValueError, "does not fit"):
                    make_qr(probe[: capacity + 1], version=config.version, error=config.error)

    def test_kit_rejects_empty_payload_invalid_alphabet_and_invalid_encoded_input(self) -> None:
        for bundle, message in (
            (b'<script>const p="";</script>', "payload is empty"),
            (b'<script>const p="abc",a="bad";</script>', "invalid Base91 alphabet"),
            (b'<script>const p=" ";</script>', "invalid Base91 character"),
        ):
            with self.subTest(bundle=bundle), self.assertRaisesRegex(ValueError, message):
                kit_module.build_kit_qr_payloads(bundle, 1800, QrConfig())

    def test_kit_rejects_invalid_chunk_sizes(self) -> None:
        for size in (0, -1):
            with self.assertRaisesRegex(ValueError, "chunk_size must exceed"):
                kit_module.build_kit_qr_payloads(
                    b'<script>const p="abc";</script>', size, QrConfig()
                )
