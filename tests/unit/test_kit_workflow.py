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

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.qr.codec import QrConfig
from ethernity.workflows.kit import service as kit_module

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestKitFlowHelpers(unittest.TestCase):
    def test_build_kit_qr_payloads_shell_first_and_chunk_size_affects_following_qrs(
        self,
    ) -> None:
        bundle = (
            b'<!doctype html><script>(async()=>{const p="'
            + (b"A" * 200)
            + b'";if(!("DecompressionStream"in window))return;})();</script>'
        )
        cfg = QrConfig()

        shell_first = kit_module.build_kit_qr_payloads(bundle, 180, cfg)
        shell_second = kit_module.build_kit_qr_payloads(bundle, 120, cfg)

        self.assertGreaterEqual(len(shell_first), 2)
        self.assertGreaterEqual(len(shell_second), 2)
        self.assertTrue(shell_first[0].startswith(b"<!doctype html"))
        token = f"globalThis.{kit_module._KIT_CHUNK_ARRAY}".encode("ascii")
        self.assertIn(token, shell_first[0])
        self.assertIn(token, shell_second[0])
        self.assertNotEqual(
            len(shell_first),
            len(shell_second),
            msg="payload chunk count should change with chunk_size",
        )

    def test_build_kit_qr_payloads_validates_each_payload_qr(self) -> None:
        with (
            mock.patch(
                "ethernity.workflows.kit.service._extract_kit_bundle_loader_metadata",
                return_value=kit_module.KitBundleLoaderMetadata(payload="p", compression="gzip"),
            ),
            mock.patch(
                "ethernity.workflows.kit.service._split_kit_payload_chunks",
                return_value=[b"chunk-1", b"chunk-2"],
            ),
            mock.patch("ethernity.workflows.kit.service._kit_shell_payload", return_value=b"shell"),
            mock.patch(
                "ethernity.workflows.kit.service.fits_qr_payload", return_value=True
            ) as fits,
        ):
            payloads = kit_module.build_kit_qr_payloads(b"bundle", 120, QrConfig())

        self.assertEqual(payloads, [b"shell", b"chunk-1", b"chunk-2"])
        self.assertEqual(fits.call_count, 3)

    def test_build_kit_qr_payloads_rejects_chunk_that_does_not_fit(self) -> None:
        with (
            mock.patch(
                "ethernity.workflows.kit.service._extract_kit_bundle_loader_metadata",
                return_value=kit_module.KitBundleLoaderMetadata(payload="p", compression="gzip"),
            ),
            mock.patch(
                "ethernity.workflows.kit.service._split_kit_payload_chunks",
                return_value=[b"chunk-1", b"chunk-2"],
            ),
            mock.patch("ethernity.workflows.kit.service._kit_shell_payload", return_value=b"shell"),
            mock.patch(
                "ethernity.workflows.kit.service.fits_qr_payload",
                side_effect=[True, True, False],
            ),
        ):
            with self.assertRaisesRegex(ValueError, "chunk_size is too large"):
                kit_module.build_kit_qr_payloads(b"bundle", 120, QrConfig())

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

        self.assertEqual(kit_module._extract_kit_bundle_loader_payload(let_bundle), "abc<def")
        self.assertEqual(kit_module._extract_kit_bundle_loader_payload(var_bundle), "abc<def")

    def test_extract_kit_bundle_loader_metadata_preserves_brotli_compression(self) -> None:
        bundle = b'<script>const p="abc";const f="brotli";</script>'

        metadata = kit_module._extract_kit_bundle_loader_metadata(bundle)
        shell = kit_module._kit_shell_payload(chunk_count=1, compression=metadata.compression)

        self.assertEqual(metadata.payload, "abc")
        self.assertEqual(metadata.compression, "brotli")
        self.assertIn(b'const f="brotli"', shell)
        self.assertIn(b"new DecompressionStream(f)", shell)

    def test_reusable_kit_shell_has_no_chain_specific_identity(self) -> None:
        shell = kit_module._kit_shell_payload(chunk_count=1)

        self.assertIn(b"ethernity-unanchored-rescue", shell)
        self.assertNotIn(b"expected_latest_head_hash", shell)

    def test_extract_kit_bundle_loader_metadata_accepts_minified_comma_declarations(
        self,
    ) -> None:
        bundle = (
            b'<script>(async()=>{const p="abc",a="alphabet",f="brotli",h="fallback"})()</script>'
        )

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
