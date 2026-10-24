import unittest
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont, TTLibError
from fpdf import FPDF
from pypdf import PdfReader

from ethernity.render.direct_pdf.assets import (
    MATERIAL_SYMBOLS_FAMILY,
    PUBLIC_SANS_FAMILY,
    ROBOTO_MONO_FAMILY,
    BundledFont,
    DirectPdfAssets,
    packaged_direct_pdf_assets,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import TextStyle


def test_only_used_fonts_are_loaded_and_embedded(monkeypatch, tmp_path) -> None:
    loaded = []
    add_font = FPDF.add_font

    def track_font(pdf, family, *args, **kwargs):
        loaded.append(family)
        return add_font(pdf, family, *args, **kwargs)

    monkeypatch.setattr(FPDF, "add_font", track_font)
    surface = FpdfSurface(page_width_mm=100, page_height_mm=100)
    packaged_direct_pdf_assets().register_fonts(surface)
    assert not loaded
    surface.add_page()
    for row, text in enumerate(("First line", "Second line")):
        style = TextStyle("Helvetica", 10)
        assert surface.measure_text_width(text, style) > 0
        surface.draw_text(10, 20 + row * 10, text, style)
    surface.draw_text(10, 40, "Monospace", TextStyle("Courier", 10))
    assert loaded == ["embedded-Helvetica", "embedded-Courier"]
    path = tmp_path / "used-fonts.pdf"
    surface.output(path)
    page = PdfReader(path).pages[0]
    assert all(text in page.extract_text() for text in ("First line", "Second line", "Monospace"))
    assert len(page["/Resources"]["/Font"]) == 2


@pytest.mark.parametrize(
    "font", packaged_direct_pdf_assets().fonts, ids=lambda font: f"{font.family}-{font.style}"
)
def test_every_bundled_font_can_be_measured_and_embedded(font, tmp_path) -> None:
    surface = FpdfSurface(page_width_mm=100, page_height_mm=100)
    surface.register_ttf_font(font.family, font.path, style=font.style)
    style = TextStyle(font.family, 10, style=font.style)
    text = "hub" if font.family == MATERIAL_SYMBOLS_FAMILY else "Backup 123"
    assert surface.measure_text_width(text, style) > 0
    surface.add_page()
    surface.draw_text(10, 20, text, style)
    path = tmp_path / "font.pdf"
    surface.output(path)
    page = PdfReader(path).pages[0]
    assert text in page.extract_text()
    fonts = page["/Resources"]["/Font"]
    assert len(fonts) == 1
    for reference in fonts.values():
        embedded = reference.get_object()
        assert embedded["/Subtype"] == "/Type0"
        descriptor = embedded["/DescendantFonts"][0].get_object()["/FontDescriptor"]
        assert descriptor["/FontFile2"].get_data()


def test_invalid_registered_font_never_falls_back_to_a_core_font(tmp_path) -> None:
    path = tmp_path / "invalid.ttf"
    path.write_bytes(b"invalid font")
    surface = FpdfSurface(page_width_mm=100, page_height_mm=100)
    surface.register_ttf_font("Helvetica", path)
    for _ in range(2):
        with pytest.raises(TTLibError):
            surface.measure_text_width("Backup", TextStyle("Helvetica", 10))


class TestDirectPdfAssets(unittest.TestCase):
    def test_packaged_assets_register_material_symbols_font(self) -> None:
        surface = FpdfSurface(page_width_mm=40, page_height_mm=40)
        assets = packaged_direct_pdf_assets()

        assets.register_fonts(surface)

        self.assertIn((MATERIAL_SYMBOLS_FAMILY, ""), surface.registered_fonts)
        self.assertIn((PUBLIC_SANS_FAMILY, ""), surface.registered_fonts)
        self.assertIn((PUBLIC_SANS_FAMILY, "B"), surface.registered_fonts)
        self.assertIn((ROBOTO_MONO_FAMILY, ""), surface.registered_fonts)
        self.assertIn((ROBOTO_MONO_FAMILY, "B"), surface.registered_fonts)

    def test_register_fonts_rejects_missing_font_file(self) -> None:
        surface = FpdfSurface(page_width_mm=40, page_height_mm=40)
        assets = DirectPdfAssets(
            fonts=(BundledFont(family="Missing", path=Path("missing-font.ttf")),)
        )

        with self.assertRaises(FileNotFoundError):
            assets.register_fonts(surface)

    def test_public_sans_assets_are_true_type_glyf_fonts(self) -> None:
        public_sans_fonts = tuple(
            font for font in packaged_direct_pdf_assets().fonts if font.family == PUBLIC_SANS_FAMILY
        )

        self.assertEqual(len(public_sans_fonts), 2)
        for bundled_font in public_sans_fonts:
            with self.subTest(path=bundled_font.path.name):
                font = TTFont(bundled_font.path)
                self.assertIn("glyf", font)
                self.assertNotIn("CFF ", font)


if __name__ == "__main__":
    unittest.main()
