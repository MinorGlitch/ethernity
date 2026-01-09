import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render import RenderInputs, render_frames_to_pdf


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


_PLAYWRIGHT_READY = _playwright_ready()


class TestPdfPageCount(unittest.TestCase):
    def test_multi_page_output(self) -> None:
        if not _PLAYWRIGHT_READY:
            self.skipTest("playwright not available")

        doc_id = b"\x77" * DOC_ID_LEN
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=doc_id,
                index=i,
                total=13,
                data=f"payload-{i}".encode("utf-8"),
            )
            for i in range(13)
        ]
        context = {
            "paper_size": "A4",
        }

        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
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

            reader = PdfReader(str(output_path))
            self.assertEqual(len(reader.pages), 2)


if __name__ == "__main__":
    unittest.main()
