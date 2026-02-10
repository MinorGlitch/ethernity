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
from ethernity.render import RenderInputs, render_frames_to_pdf
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


if __name__ == "__main__":
    unittest.main()
