import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfReader

from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle


class TestDirectPdfSurface(unittest.TestCase):
    def test_color_rejects_out_of_range_channels(self) -> None:
        with self.assertRaisesRegex(ValueError, "red must be between 0 and 255"):
            PdfColor(256, 0, 0)

    def test_rect_rejects_negative_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "width_mm must be non-negative"):
            PdfRect(0, 0, -1, 1)

    def test_core_font_measurement_and_line_height(self) -> None:
        surface = FpdfSurface(page_width_mm=80, page_height_mm=60)
        style = TextStyle(family="Helvetica", size_pt=10)

        self.assertGreater(surface.measure_text_width("Ethernity", style), 0)
        self.assertGreater(surface.line_height(style), 0)

    def test_text_style_character_spacing_changes_measurement(self) -> None:
        surface = FpdfSurface(page_width_mm=80, page_height_mm=60)
        compact = TextStyle(family="Helvetica", size_pt=10)
        tracked = TextStyle(family="Helvetica", size_pt=10, char_spacing_pt=0.25)

        self.assertAlmostEqual(
            surface.measure_text_width("ETERNITY", tracked)
            - surface.measure_text_width("ETERNITY", compact),
            8 * 0.25 * 25.4 / 72,
        )

    def test_character_spacing_is_painted_in_points(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "spacing.pdf"
            surface = FpdfSurface(page_width_mm=80, page_height_mm=60)
            surface.add_page()
            surface.draw_text(10, 20, "AB", TextStyle("Helvetica", 10, char_spacing_pt=1.0))
            surface.output(path)
            self.assertIn(b"1.00 Tc", PdfReader(path).pages[0].get_contents().get_data())


if __name__ == "__main__":
    unittest.main()
