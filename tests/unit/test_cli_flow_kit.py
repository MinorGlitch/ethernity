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
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.flows import kit as kit_module
from ethernity.qr.codec import QrConfig


class TestKitFlowHelpers(unittest.TestCase):
    def test_split_bytes(self) -> None:
        self.assertEqual(kit_module._split_bytes(b"abcdef", 2), [b"ab", b"cd", b"ef"])

    @mock.patch("ethernity.cli.flows.kit.make_qr", return_value=object())
    def test_fits_qr_payload_true(self, _make_qr: mock.MagicMock) -> None:
        self.assertTrue(kit_module._fits_qr_payload(b"abc", QrConfig()))

    @mock.patch("ethernity.cli.flows.kit.make_qr", side_effect=ValueError("too big"))
    def test_fits_qr_payload_false_on_error(self, _make_qr: mock.MagicMock) -> None:
        self.assertFalse(kit_module._fits_qr_payload(b"abc", QrConfig()))

    def test_validate_qr_payload_bytes(self) -> None:
        with self.assertRaisesRegex(ValueError, "chunk_size must be positive"):
            kit_module._validate_qr_payload_bytes(0, b"abc", QrConfig())

        with mock.patch("ethernity.cli.flows.kit._fits_qr_payload", return_value=False):
            with self.assertRaisesRegex(ValueError, "chunk_size is too large"):
                kit_module._validate_qr_payload_bytes(100, b"abc", QrConfig())

    def test_max_qr_payload_bytes_binary_search(self) -> None:
        cfg = QrConfig()

        def _fits(payload: bytes, _cfg: QrConfig) -> bool:
            return len(payload) <= 10

        with mock.patch("ethernity.cli.flows.kit._fits_qr_payload", side_effect=_fits):
            self.assertEqual(kit_module._max_qr_payload_bytes(b"x" * 100, cfg), 7)

    def test_max_qr_payload_bytes_rejects_no_capacity(self) -> None:
        with mock.patch("ethernity.cli.flows.kit._fits_qr_payload", return_value=False):
            with self.assertRaisesRegex(ValueError, "cannot encode any payload bytes"):
                kit_module._max_qr_payload_bytes(b"x", QrConfig())

    def test_load_kit_bundle_custom_success_and_errors(self) -> None:
        with tempfile.NamedTemporaryFile() as fh:
            Path(fh.name).write_bytes(b"bundle")
            self.assertEqual(kit_module._load_kit_bundle(fh.name), b"bundle")

        with self.assertRaisesRegex(ValueError, "bundle file not found"):
            kit_module._load_kit_bundle("/definitely/missing.bundle.html")

        with tempfile.NamedTemporaryFile() as fh:
            with mock.patch("pathlib.Path.read_bytes", side_effect=OSError("denied")):
                with self.assertRaisesRegex(ValueError, "unable to read bundle file"):
                    kit_module._load_kit_bundle(fh.name)

    def test_load_kit_bundle_package_and_dev_fallback(self) -> None:
        fake_package = mock.Mock()
        fake_join = mock.Mock()
        fake_join.read_bytes.return_value = b"pkg"
        fake_package.joinpath.return_value = fake_join
        with mock.patch("ethernity.cli.flows.kit.files", return_value=fake_package):
            self.assertEqual(kit_module._load_kit_bundle(None), b"pkg")

        with tempfile.TemporaryDirectory() as tmp:
            pkg_root = Path(tmp) / "a" / "b" / "c"
            pkg_root.mkdir(parents=True)
            candidate = pkg_root.parents[2] / "kit" / "dist" / kit_module.DEFAULT_KIT_BUNDLE_NAME
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(b"dev")
            with mock.patch("ethernity.cli.flows.kit.files", side_effect=FileNotFoundError):
                with mock.patch("ethernity.cli.flows.kit.PACKAGE_ROOT", pkg_root):
                    self.assertEqual(kit_module._load_kit_bundle(None), b"dev")

            candidate.unlink()
            with mock.patch("ethernity.cli.flows.kit.files", side_effect=ModuleNotFoundError):
                with mock.patch("ethernity.cli.flows.kit.PACKAGE_ROOT", pkg_root):
                    with self.assertRaisesRegex(FileNotFoundError, "Recovery kit bundle not found"):
                        kit_module._load_kit_bundle(None)


class TestRenderKitDocument(unittest.TestCase):
    @mock.patch("ethernity.cli.flows.kit.render_frames_to_pdf")
    @mock.patch("ethernity.cli.flows.kit.RenderService")
    @mock.patch("ethernity.cli.flows.kit.status", return_value=contextlib.nullcontext(None))
    @mock.patch("ethernity.cli.flows.kit._split_bytes", return_value=[b"a", b"b", b"c"])
    @mock.patch("ethernity.cli.flows.kit._max_qr_payload_bytes", return_value=800)
    @mock.patch("ethernity.cli.flows.kit._load_kit_bundle", return_value=b"bundle-bytes")
    @mock.patch("ethernity.cli.flows.kit.apply_template_design")
    @mock.patch("ethernity.cli.flows.kit.load_app_config")
    def test_render_kit_qr_document_auto_chunk_size(
        self,
        load_app_config: mock.MagicMock,
        apply_template_design: mock.MagicMock,
        _load_kit_bundle: mock.MagicMock,
        _max_qr_payload_bytes: mock.MagicMock,
        _split_bytes: mock.MagicMock,
        _status: mock.MagicMock,
        render_service_cls: mock.MagicMock,
        render_frames_to_pdf: mock.MagicMock,
    ) -> None:
        config = SimpleNamespace(qr_config=QrConfig())
        load_app_config.return_value = config
        apply_template_design.return_value = config
        render_service = mock.Mock()
        render_service.base_context.return_value = {"ctx": True}
        render_service.kit_inputs.return_value = "inputs"
        render_service_cls.return_value = render_service

        result = kit_module.render_kit_qr_document(
            bundle_path=None,
            output_path="kit.pdf",
            config_path=None,
            paper_size="A4",
            design="forge",
            chunk_size=None,
            quiet=True,
        )

        self.assertEqual(result.output_path, Path("kit.pdf"))
        self.assertEqual(result.chunk_count, 3)
        self.assertEqual(result.chunk_size, 800)
        self.assertEqual(result.bytes_total, len(b"bundle-bytes"))
        render_service.kit_inputs.assert_called_once()
        render_frames_to_pdf.assert_called_once_with("inputs")

    @mock.patch("ethernity.cli.flows.kit.render_frames_to_pdf")
    @mock.patch("ethernity.cli.flows.kit.RenderService")
    @mock.patch("ethernity.cli.flows.kit.status", return_value=contextlib.nullcontext(None))
    @mock.patch("ethernity.cli.flows.kit._split_bytes", return_value=[b"chunk"])
    @mock.patch("ethernity.cli.flows.kit._validate_qr_payload_bytes")
    @mock.patch("ethernity.cli.flows.kit._load_kit_bundle", return_value=b"bundle-bytes")
    @mock.patch("ethernity.cli.flows.kit.apply_template_design")
    @mock.patch("ethernity.cli.flows.kit.load_app_config")
    def test_render_kit_qr_document_explicit_chunk_size(
        self,
        load_app_config: mock.MagicMock,
        apply_template_design: mock.MagicMock,
        _load_kit_bundle: mock.MagicMock,
        validate_qr_payload_bytes: mock.MagicMock,
        _split_bytes: mock.MagicMock,
        _status: mock.MagicMock,
        render_service_cls: mock.MagicMock,
        render_frames_to_pdf: mock.MagicMock,
    ) -> None:
        config = SimpleNamespace(qr_config=QrConfig())
        load_app_config.return_value = config
        apply_template_design.return_value = config
        render_service = mock.Mock()
        render_service.base_context.return_value = {}
        render_service.kit_inputs.return_value = "inputs"
        render_service_cls.return_value = render_service

        result = kit_module.render_kit_qr_document(
            bundle_path=None,
            output_path=None,
            config_path="cfg.toml",
            paper_size=None,
            design=None,
            chunk_size=256,
            quiet=False,
        )

        self.assertEqual(result.output_path, Path(kit_module.DEFAULT_KIT_OUTPUT))
        self.assertEqual(result.chunk_count, 1)
        self.assertEqual(result.chunk_size, 256)
        validate_qr_payload_bytes.assert_called_once_with(256, b"bundle-bytes", config.qr_config)
        render_frames_to_pdf.assert_called_once_with("inputs")


if __name__ == "__main__":
    unittest.main()
