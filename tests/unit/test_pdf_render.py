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

from playwright.sync_api import sync_playwright

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render import RenderInputs, pdf_render as pdf_render_module, render_frames_to_pdf
from tests.test_support import ensure_playwright_browsers


def _playwright_ready() -> bool:
    if sync_playwright is None:
        return False
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False


class TestPdfRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_playwright_browsers()

    def test_pdf_output(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x55" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]

        if not _playwright_ready():
            self.skipTest("playwright not available")

        context = {
            "paper_size": "A4",
        }

        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "ledger"
            / "main_document.html.j2"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.pdf"
            inputs = RenderInputs(
                frames=frames,
                template_path=template_path,
                output_path=output_path,
                context=context,
                doc_type="main",
                render_fallback=False,
            )
            render_frames_to_pdf(inputs)

            pdf_bytes = output_path.read_bytes()
            self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_render_frames_to_pdf_preserves_inventory_rows_context(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x55" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "ledger"
            / "main_document.html.j2"
        )
        context = {
            "paper_size": "A4",
            "inventory_rows": [
                {
                    "component_id": "QR-DOC-01",
                    "detail": "Encrypted payload and auth QR frames",
                    "status": "Generated",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.pdf"
            inputs = RenderInputs(
                frames=frames,
                template_path=template_path,
                output_path=output_path,
                context=context,
                doc_type="main",
                render_qr=False,
                render_fallback=False,
            )
            with mock.patch("ethernity.render.pdf_render.render_html_to_pdf"):
                with mock.patch(
                    "ethernity.render.pdf_render.render_template",
                    return_value="<html></html>",
                ) as render_template_mock:
                    render_frames_to_pdf(inputs)

        rendered_context = render_template_mock.call_args[0][1]
        self.assertIn("inventory_rows", rendered_context)
        inventory_rows = rendered_context["inventory_rows"]
        self.assertEqual(inventory_rows[0]["component_id"], "QR-DOC-01")
        self.assertNotIn("forge_copy", rendered_context)

    def test_render_frames_to_pdf_injects_forge_copy_from_style_capability(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x55" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        context = {
            "paper_size": "A4",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            template_dir = Path(tmpdir) / "forge_copy_clone"
            template_dir.mkdir(parents=True, exist_ok=True)
            template_path = template_dir / "main_document.html.j2"
            template_path.write_text("{{ forge_copy.generator_label }}", encoding="utf-8")
            (template_dir / "style.json").write_text(
                """{
  "name": "forge-copy-clone",
  "header": {
    "meta_row_gap_mm": 1.2,
    "stack_gap_mm": 1.2,
    "divider_thickness_mm": 0.5
  },
  "content_offset": {
    "divider_gap_extra_mm": 0.0,
    "doc_types": []
  },
  "capabilities": {
    "inject_forge_copy": true
  }
}
""",
                encoding="utf-8",
            )
            output_path = Path(tmpdir) / "out.pdf"
            inputs = RenderInputs(
                frames=frames,
                template_path=template_path,
                output_path=output_path,
                context=context,
                doc_type="main",
                render_qr=False,
                render_fallback=False,
            )
            with mock.patch("ethernity.render.pdf_render.render_html_to_pdf"):
                with mock.patch(
                    "ethernity.render.pdf_render.render_template",
                    return_value="<html></html>",
                ) as render_template_mock:
                    render_frames_to_pdf(inputs)

        rendered_context = render_template_mock.call_args[0][1]
        self.assertIn("forge_copy", rendered_context)
        self.assertEqual(
            rendered_context["forge_copy"]["generator_label"],
            "Generated by Ethernity Forge",
        )

    @mock.patch.dict("os.environ", {}, clear=True)
    @mock.patch("ethernity.render.pdf_render.os.process_cpu_count", return_value=8)
    def test_resolve_qr_workers_uses_config_when_env_absent(
        self,
        _cpu_count: mock.MagicMock,
    ) -> None:
        workers = pdf_render_module._resolve_qr_workers(32, configured=3)
        self.assertEqual(workers, 3)

    @mock.patch.dict("os.environ", {"ETHERNITY_RENDER_JOBS": "5"}, clear=True)
    @mock.patch("ethernity.render.pdf_render.os.process_cpu_count", return_value=8)
    def test_resolve_qr_workers_env_overrides_config(
        self,
        _cpu_count: mock.MagicMock,
    ) -> None:
        workers = pdf_render_module._resolve_qr_workers(32, configured=2)
        self.assertEqual(workers, 5)

    @mock.patch.dict("os.environ", {"ETHERNITY_RENDER_JOBS": "invalid"}, clear=True)
    @mock.patch("ethernity.render.pdf_render.os.process_cpu_count", return_value=8)
    def test_resolve_qr_workers_invalid_env_still_errors_with_valid_config(
        self,
        _cpu_count: mock.MagicMock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "ETHERNITY_RENDER_JOBS"):
            pdf_render_module._resolve_qr_workers(32, configured=2)

    @mock.patch.dict("os.environ", {}, clear=True)
    @mock.patch("ethernity.render.pdf_render.os.process_cpu_count", return_value=8)
    def test_resolve_qr_workers_auto_config_keeps_auto_heuristic(
        self,
        _cpu_count: mock.MagicMock,
    ) -> None:
        workers = pdf_render_module._resolve_qr_workers(32, configured="auto")
        self.assertEqual(workers, 8)


if __name__ == "__main__":
    unittest.main()
