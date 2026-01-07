import tempfile
import unittest
from pathlib import Path

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render import RenderInputs, render_frames_to_pdf

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dependency for tests
    sync_playwright = None


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


class TestPdfRender(unittest.TestCase):
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

        if not _PLAYWRIGHT_READY:
            self.skipTest("playwright not available")

        context = {
            "paper_size": "A4",
        }

        template_path = (
            Path(__file__).resolve().parents[2] / "ethernity" / "templates" / "main_document.html.j2"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.pdf"
            inputs = RenderInputs(
                frames=frames,
                template_path=template_path,
                output_path=output_path,
                context=context,
                render_fallback=False,
            )
            render_frames_to_pdf(inputs)

            pdf_bytes = output_path.read_bytes()
            self.assertTrue(pdf_bytes.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
