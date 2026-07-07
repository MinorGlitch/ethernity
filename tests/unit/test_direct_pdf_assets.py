import unittest
from pathlib import Path

from ethernity.render.direct_pdf import (
    MATERIAL_SYMBOLS_FAMILY,
    PUBLIC_SANS_FAMILY,
    ROBOTO_MONO_FAMILY,
    BundledFont,
    DirectPdfAssets,
    FpdfSurface,
    packaged_direct_pdf_assets,
)


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


if __name__ == "__main__":
    unittest.main()
