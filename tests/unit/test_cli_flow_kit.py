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

import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.features.kit import workflow as kit_module
from ethernity.qr.codec import QrConfig

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _home_env(home: Path) -> dict[str, str]:
    env = {"HOME": str(home), "USERPROFILE": str(home)}
    drive, tail = os.path.splitdrive(str(home))
    if drive:
        env["HOMEDRIVE"] = drive
        env["HOMEPATH"] = tail or "\\"
    return env


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

        shell_first = kit_module._build_kit_qr_payloads(bundle, 180, cfg)
        shell_second = kit_module._build_kit_qr_payloads(bundle, 120, cfg)

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

    @mock.patch("ethernity.cli.features.kit.workflow.make_qr", return_value=object())
    def test_fits_qr_payload_true(self, _make_qr: mock.MagicMock) -> None:
        self.assertTrue(kit_module._fits_qr_payload(b"abc", QrConfig()))

    @mock.patch("ethernity.cli.features.kit.workflow.make_qr", side_effect=ValueError("too big"))
    def test_fits_qr_payload_false_on_error(self, _make_qr: mock.MagicMock) -> None:
        self.assertFalse(kit_module._fits_qr_payload(b"abc", QrConfig()))

    def test_build_kit_qr_payloads_validates_each_payload_qr(self) -> None:
        with (
            mock.patch(
                "ethernity.cli.features.kit.workflow._extract_kit_bundle_loader_metadata",
                return_value=kit_module.KitBundleLoaderMetadata(payload="p", compression="gzip"),
            ),
            mock.patch(
                "ethernity.cli.features.kit.workflow._split_kit_payload_chunks",
                return_value=[b"chunk-1", b"chunk-2"],
            ),
            mock.patch(
                "ethernity.cli.features.kit.workflow._kit_shell_payload", return_value=b"shell"
            ),
            mock.patch(
                "ethernity.cli.features.kit.workflow._fits_qr_payload", return_value=True
            ) as fits,
        ):
            payloads = kit_module._build_kit_qr_payloads(b"bundle", 120, QrConfig())

        self.assertEqual(payloads, [b"shell", b"chunk-1", b"chunk-2"])
        self.assertEqual(fits.call_count, 3)

    def test_build_kit_qr_payloads_rejects_chunk_that_does_not_fit(self) -> None:
        with (
            mock.patch(
                "ethernity.cli.features.kit.workflow._extract_kit_bundle_loader_metadata",
                return_value=kit_module.KitBundleLoaderMetadata(payload="p", compression="gzip"),
            ),
            mock.patch(
                "ethernity.cli.features.kit.workflow._split_kit_payload_chunks",
                return_value=[b"chunk-1", b"chunk-2"],
            ),
            mock.patch(
                "ethernity.cli.features.kit.workflow._kit_shell_payload", return_value=b"shell"
            ),
            mock.patch(
                "ethernity.cli.features.kit.workflow._fits_qr_payload",
                side_effect=[True, True, False],
            ),
        ):
            with self.assertRaisesRegex(ValueError, "chunk_size is too large"):
                kit_module._build_kit_qr_payloads(b"bundle", 120, QrConfig())

    def test_max_qr_payload_bytes_binary_search(self) -> None:
        cfg = QrConfig()

        def _fits(payload: bytes, _cfg: QrConfig) -> bool:
            return len(payload) <= 10

        with mock.patch("ethernity.cli.features.kit.workflow._fits_qr_payload", side_effect=_fits):
            self.assertEqual(kit_module._max_qr_payload_bytes(b"x" * 100, cfg), 10)

    def test_max_qr_payload_bytes_rejects_no_capacity(self) -> None:
        with mock.patch("ethernity.cli.features.kit.workflow._fits_qr_payload", return_value=False):
            with self.assertRaisesRegex(ValueError, "cannot encode any payload bytes"):
                kit_module._max_qr_payload_bytes(b"x", QrConfig())

    def test_load_kit_bundle_package_and_dev_fallback(self) -> None:
        fake_package = mock.Mock()
        fake_join = mock.Mock()
        fake_join.read_bytes.return_value = b"pkg"
        fake_package.joinpath.return_value = fake_join
        with mock.patch("ethernity.cli.features.kit.workflow.files", return_value=fake_package):
            self.assertEqual(kit_module._load_kit_bundle(), b"pkg")
            fake_package.joinpath.assert_called_with("kit", kit_module.DEFAULT_KIT_BUNDLE_NAME)

        fake_package_scanner = mock.Mock()
        fake_join_scanner = mock.Mock()
        fake_join_scanner.read_bytes.return_value = b"scanner-pkg"
        fake_package_scanner.joinpath.return_value = fake_join_scanner
        with mock.patch(
            "ethernity.cli.features.kit.workflow.files", return_value=fake_package_scanner
        ):
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
            with mock.patch(
                "ethernity.cli.features.kit.workflow.files", side_effect=FileNotFoundError
            ):
                with mock.patch(
                    "ethernity.cli.features.kit.workflow._DEV_KIT_DIST_ROOT", dev_dist_root
                ):
                    self.assertEqual(kit_module._load_kit_bundle(), b"dev")

            scanner_candidate = dev_dist_root / kit_module.SCANNER_KIT_BUNDLE_NAME
            scanner_candidate.write_bytes(b"scanner-dev")
            with mock.patch(
                "ethernity.cli.features.kit.workflow.files", side_effect=FileNotFoundError
            ):
                with mock.patch(
                    "ethernity.cli.features.kit.workflow._DEV_KIT_DIST_ROOT", dev_dist_root
                ):
                    self.assertEqual(kit_module._load_kit_bundle(variant="scanner"), b"scanner-dev")
            scanner_candidate.unlink()

            candidate.unlink()
            with mock.patch(
                "ethernity.cli.features.kit.workflow.files", side_effect=ModuleNotFoundError
            ):
                with mock.patch(
                    "ethernity.cli.features.kit.workflow._DEV_KIT_DIST_ROOT", dev_dist_root
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
            self.assertEqual(metadata.compression, "brotli")


class TestRenderKitDocument(unittest.TestCase):
    @mock.patch("ethernity.cli.features.kit.workflow.render_frames_to_pdf")
    @mock.patch("ethernity.cli.features.kit.workflow.RenderService")
    @mock.patch(
        "ethernity.cli.features.kit.workflow.status", return_value=contextlib.nullcontext(None)
    )
    @mock.patch(
        "ethernity.cli.features.kit.workflow._build_kit_qr_payloads",
        return_value=[b"shell", b"a", b"b", b"c"],
    )
    @mock.patch("ethernity.cli.features.kit.workflow._max_qr_payload_bytes", return_value=800)
    @mock.patch(
        "ethernity.cli.features.kit.workflow._load_kit_bundle", return_value=b"bundle-bytes"
    )
    @mock.patch("ethernity.cli.features.kit.workflow.apply_render_style")
    @mock.patch("ethernity.cli.features.kit.workflow.load_app_config")
    def test_render_kit_qr_document_auto_chunk_size(
        self,
        load_app_config: mock.MagicMock,
        apply_render_style: mock.MagicMock,
        _load_kit_bundle: mock.MagicMock,
        _max_qr_payload_bytes: mock.MagicMock,
        _build_kit_qr_payloads: mock.MagicMock,
        _status: mock.MagicMock,
        render_service_cls: mock.MagicMock,
        render_frames_to_pdf: mock.MagicMock,
    ) -> None:
        config = SimpleNamespace(qr_config=QrConfig())
        load_app_config.return_value = config
        apply_render_style.return_value = config
        render_service = mock.Mock()
        render_service.base_context.return_value = {"ctx": True}
        render_service.kit_inputs.return_value = "inputs"
        render_service_cls.return_value = render_service

        result = kit_module.render_kit_qr_document(
            output_path="kit.pdf",
            config_path=None,
            paper_size="A4",
            design="forge",
            variant="lean",
            chunk_size=None,
            quiet=True,
        )

        self.assertEqual(result.output_path, Path("kit.pdf"))
        self.assertEqual(result.chunk_count, 4)
        self.assertEqual(result.chunk_size, 800)
        self.assertEqual(result.bytes_total, len(b"bundle-bytes"))
        render_service.kit_inputs.assert_called_once()
        render_frames_to_pdf.assert_called_once_with("inputs")

    @mock.patch("ethernity.cli.features.kit.workflow.render_frames_to_pdf")
    @mock.patch("ethernity.cli.features.kit.workflow.RenderService")
    @mock.patch(
        "ethernity.cli.features.kit.workflow.status", return_value=contextlib.nullcontext(None)
    )
    @mock.patch(
        "ethernity.cli.features.kit.workflow._build_kit_qr_payloads",
        return_value=[b"shell", b"chunk"],
    )
    @mock.patch(
        "ethernity.cli.features.kit.workflow._load_kit_bundle", return_value=b"bundle-bytes"
    )
    @mock.patch("ethernity.cli.features.kit.workflow.apply_render_style")
    @mock.patch("ethernity.cli.features.kit.workflow.load_app_config")
    def test_render_kit_qr_document_explicit_chunk_size(
        self,
        load_app_config: mock.MagicMock,
        apply_render_style: mock.MagicMock,
        _load_kit_bundle: mock.MagicMock,
        build_kit_qr_payloads: mock.MagicMock,
        _status: mock.MagicMock,
        render_service_cls: mock.MagicMock,
        render_frames_to_pdf: mock.MagicMock,
    ) -> None:
        config = SimpleNamespace(qr_config=QrConfig())
        load_app_config.return_value = config
        apply_render_style.return_value = config
        render_service = mock.Mock()
        render_service.base_context.return_value = {}
        render_service.kit_inputs.return_value = "inputs"
        render_service_cls.return_value = render_service

        result = kit_module.render_kit_qr_document(
            output_path=None,
            config_path="cfg.toml",
            paper_size=None,
            design=None,
            variant="lean",
            chunk_size=256,
            quiet=False,
        )

        self.assertEqual(result.output_path, Path(kit_module.DEFAULT_KIT_OUTPUT))
        self.assertEqual(result.chunk_count, 2)
        self.assertEqual(result.chunk_size, 256)
        build_kit_qr_payloads.assert_called_once_with(b"bundle-bytes", 256, config.qr_config)
        render_frames_to_pdf.assert_called_once_with("inputs")

    @mock.patch("ethernity.cli.features.kit.workflow.render_frames_to_pdf")
    @mock.patch("ethernity.cli.features.kit.workflow.RenderService")
    @mock.patch(
        "ethernity.cli.features.kit.workflow.status", return_value=contextlib.nullcontext(None)
    )
    @mock.patch(
        "ethernity.cli.features.kit.workflow._build_kit_qr_payloads",
        return_value=[b"shell", b"chunk"],
    )
    @mock.patch(
        "ethernity.cli.features.kit.workflow._load_kit_bundle", return_value=b"bundle-bytes"
    )
    @mock.patch("ethernity.cli.features.kit.workflow.apply_render_style")
    @mock.patch("ethernity.cli.features.kit.workflow.load_app_config")
    def test_render_kit_qr_document_expands_output_path(
        self,
        load_app_config: mock.MagicMock,
        apply_render_style: mock.MagicMock,
        _load_kit_bundle: mock.MagicMock,
        _build_kit_qr_payloads: mock.MagicMock,
        _status: mock.MagicMock,
        render_service_cls: mock.MagicMock,
        _render_frames_to_pdf: mock.MagicMock,
    ) -> None:
        config = SimpleNamespace(qr_config=QrConfig())
        load_app_config.return_value = config
        apply_render_style.return_value = config
        render_service = mock.Mock()
        render_service.base_context.return_value = {}
        render_service.kit_inputs.return_value = "inputs"
        render_service_cls.return_value = render_service
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", _home_env(home), clear=False):
                result = kit_module.render_kit_qr_document(
                    output_path="~/kit.pdf",
                    config_path=None,
                    paper_size=None,
                    design=None,
                    variant="lean",
                    chunk_size=256,
                    quiet=True,
                )
        self.assertEqual(result.output_path, home / "kit.pdf")

    @mock.patch("ethernity.cli.features.kit.workflow.render_frames_to_pdf")
    @mock.patch("ethernity.cli.features.kit.workflow.RenderService")
    @mock.patch(
        "ethernity.cli.features.kit.workflow.status", return_value=contextlib.nullcontext(None)
    )
    @mock.patch(
        "ethernity.cli.features.kit.workflow._build_kit_qr_payloads",
        return_value=[b"shell", b"chunk"],
    )
    @mock.patch(
        "ethernity.cli.features.kit.workflow._load_kit_bundle", return_value=b"bundle-bytes"
    )
    @mock.patch("ethernity.cli.features.kit.workflow.apply_render_style")
    @mock.patch("ethernity.cli.features.kit.workflow.load_app_config")
    def test_render_kit_qr_document_explicit_chunk_size_uses_requested_size(
        self,
        load_app_config: mock.MagicMock,
        apply_render_style: mock.MagicMock,
        _load_kit_bundle: mock.MagicMock,
        build_kit_qr_payloads: mock.MagicMock,
        _status: mock.MagicMock,
        render_service_cls: mock.MagicMock,
        render_frames_to_pdf: mock.MagicMock,
    ) -> None:
        config = SimpleNamespace(qr_config=QrConfig())
        load_app_config.return_value = config
        apply_render_style.return_value = config
        render_service = mock.Mock()
        render_service.base_context.return_value = {}
        render_service.kit_inputs.return_value = "inputs"
        render_service_cls.return_value = render_service

        huge = kit_module._MAX_QR_PROBE_BYTES * 100
        kit_module.render_kit_qr_document(
            output_path=None,
            config_path=None,
            paper_size=None,
            design=None,
            variant="lean",
            chunk_size=huge,
            quiet=True,
        )

        build_kit_qr_payloads.assert_called_once_with(b"bundle-bytes", huge, config.qr_config)
        render_frames_to_pdf.assert_called_once_with("inputs")

    @mock.patch("ethernity.cli.features.kit.workflow._load_kit_bundle")
    @mock.patch("ethernity.cli.features.kit.workflow.apply_render_style")
    @mock.patch("ethernity.cli.features.kit.workflow.load_app_config")
    def test_render_kit_qr_document_rejects_invalid_variant_before_loading_bundle(
        self,
        load_app_config: mock.MagicMock,
        apply_render_style: mock.MagicMock,
        load_kit_bundle: mock.MagicMock,
    ) -> None:
        config = SimpleNamespace(qr_config=QrConfig())
        load_app_config.return_value = config
        apply_render_style.return_value = config

        with self.assertRaisesRegex(ValueError, "variant must be 'lean' or 'scanner'"):
            kit_module.render_kit_qr_document(
                output_path=None,
                config_path=None,
                paper_size=None,
                design=None,
                variant="notreal",
                chunk_size=256,
                quiet=True,
            )

        load_kit_bundle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
