import unittest
from pathlib import Path

from fpdf import FPDF

from ethernity.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.pdf_render import RenderInputs, _compute_layout


class TestPdfLayout(unittest.TestCase):
    def test_gap_override_when_max_rows_exceeds_fit(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x22" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2] / "ethernity" / "templates" / "main_document.toml.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frames[0].doc_id.hex()},
            render_fallback=False,
        )
        initial_cfg = {
            "page": {
                "size": (100, 100),
                "margin_mm": 0,
                "header_height_mm": 0,
                "instructions_gap_mm": 0,
            },
            "qr_grid": {
                "qr_size_mm": 30,
                "gap_mm": 10,
                "max_cols": 1,
                "max_rows": 3,
                "text_gap_mm": 2,
            },
            "fallback": {
                "group_size": 4,
                "line_length": 80,
                "line_count": 6,
                "line_height_mm": 3.5,
                "font_family": "Courier",
                "font_size": 8,
            },
            "header": {},
            "instructions": {"lines": []},
            "keys": {},
        }
        pdf = FPDF(unit="mm", format=(100, 100))
        layout, _ = _compute_layout(inputs, initial_cfg, pdf, key_lines=[])

        self.assertEqual(layout.rows, 3)
        self.assertIsNotNone(layout.gap_y_override)

    def test_fallback_reduces_rows(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x33" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2] / "ethernity" / "templates" / "main_document.toml.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frames[0].doc_id.hex()},
            render_fallback=True,
        )
        initial_cfg = {
            "page": {
                "size": (100, 100),
                "margin_mm": 0,
                "header_height_mm": 0,
                "instructions_gap_mm": 0,
            },
            "qr_grid": {
                "qr_size_mm": 30,
                "gap_mm": 10,
                "max_cols": 1,
                "max_rows": 3,
                "text_gap_mm": 2,
            },
            "fallback": {
                "group_size": 4,
                "line_length": 80,
                "line_count": 4,
                "line_height_mm": 10,
                "font_family": "Courier",
                "font_size": 8,
            },
            "header": {},
            "instructions": {"lines": []},
            "keys": {},
        }
        pdf = FPDF(unit="mm", format=(100, 100))
        layout, _ = _compute_layout(inputs, initial_cfg, pdf, key_lines=[])

        self.assertEqual(layout.rows, 1)
        self.assertGreater(layout.fallback_lines_per_page, 0)


if __name__ == "__main__":
    unittest.main()
