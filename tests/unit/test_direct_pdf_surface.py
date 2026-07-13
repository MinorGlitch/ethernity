import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.qr.codec import qr_bytes
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.proofs import validate_pdf_has_pages

_ICON_FONT = Path("src/ethernity/resources/templates/_shared/assets/material-symbols-outlined.ttf")


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
        tracked = TextStyle(family="Helvetica", size_pt=10, char_spacing_mm=0.25)

        self.assertGreater(
            surface.measure_text_width("ETERNITY", tracked),
            surface.measure_text_width("ETERNITY", compact),
        )

    def test_pdf_output_supports_registered_font_and_images(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_pdf_surface.pdf"
            surface = FpdfSurface(page_width_mm=80, page_height_mm=80)
            surface.add_page()
            surface.register_ttf_font("Material Symbols Outlined", _ICON_FONT)
            surface.draw_rect(
                PdfRect(5, 5, 70, 70),
                stroke=PdfColor(20, 20, 20),
                line_width_mm=0.4,
            )
            surface.draw_text(
                10,
                18,
                "hub",
                TextStyle(family="Material Symbols Outlined", size_pt=14),
            )
            surface.draw_text(
                10,
                30,
                "Direct PDF",
                TextStyle(family="Helvetica", size_pt=12, color=PdfColor(40, 40, 40)),
            )
            surface.draw_image_bytes(
                qr_bytes("direct-pdf-feasibility", scale=2),
                PdfRect(10, 36, 28, 28),
                image_type="PNG",
            )
            surface.output(output_path)

            validate_pdf_has_pages(output_path)


if __name__ == "__main__":
    unittest.main()
