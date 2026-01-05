import tempfile
import unittest
from pathlib import Path

from ethernity.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.pdf_render import RenderInputs, render_frames_to_pdf


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
            "doc_id": frames[0].doc_id.hex(),
            "instructions_font": "Helvetica",
            "instructions_size": 8,
            "instructions_line_height_mm": 4,
            "instructions": ["Scan all QR codes.", "Use text fallback if needed."],
            "qr_size_mm": 35,
            "gap_mm": 6,
            "max_cols": 3,
            "max_rows": 4,
            "text_gap_mm": 2,
            "fallback_font": "Courier",
            "fallback_size": 8,
            "fallback_line_height_mm": 3.5,
            "fallback_group_size": 4,
            "fallback_line_length": 80,
            "fallback_line_count": 6,
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
                fallback_payload=frames[0].data,
            )
            render_frames_to_pdf(inputs)

            pdf_bytes = output_path.read_bytes()
            self.assertTrue(pdf_bytes.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
