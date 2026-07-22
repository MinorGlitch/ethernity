import unittest
from pathlib import Path

from fontTools.ttLib import TTFont

from ethernity.render.direct_pdf.assets import (
    MATERIAL_SYMBOLS_FAMILY,
    PUBLIC_SANS_FAMILY,
    ROBOTO_MONO_FAMILY,
    BundledFont,
    DirectPdfAssets,
    packaged_direct_pdf_assets,
)
from ethernity.render.direct_pdf.surface import FpdfSurface


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
