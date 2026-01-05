import tempfile
import unittest
from pathlib import Path

from ethernity.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.pdf_render import RenderInputs, render_frames_to_pdf


class TestPdfPageCount(unittest.TestCase):
    def test_multi_page_output(self) -> None:
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf not installed")

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
            "margin_mm": 12,
            "header_height_mm": 10,
            "instructions_gap_mm": 2,
            "header_font": "Helvetica",
            "title_size": 14,
            "subtitle_size": 10,
            "meta_size": 8,
            "title": "Main Document",
            "subtitle": "Test Backup",
            "doc_id": doc_id.hex(),
            "instructions_font": "Helvetica",
            "instructions_size": 8,
            "instructions_line_height_mm": 4,
            "instructions": [],
            "qr_size_mm": 60,
            "gap_mm": 2,
            "max_cols": 3,
            "max_rows": 4,
            "text_gap_mm": 2,
        }

        template_path = (
            Path(__file__).resolve().parents[2] / "ethernity" / "templates" / "main_document.toml.j2"
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

            reader = PdfReader(str(output_path))
            self.assertEqual(len(reader.pages), 2)


if __name__ == "__main__":
    unittest.main()
