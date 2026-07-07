import unittest

from ethernity.render.direct_pdf import FORGE_THEME
from ethernity.render.direct_pdf.forge_common import (
    FORGE_CONTENT_WIDTH_MM,
    FORGE_CONTENT_X_MM,
    FORGE_MONO_FONT,
    FORGE_SANS_FONT,
    FORGE_SERIF_FONT,
    FORGE_SLATE_900,
    FORGE_SYMBOLS_FONT,
)


class TestDirectPdfForgeTheme(unittest.TestCase):
    def test_theme_records_reference_fonts_and_current_pdf_fallbacks(self) -> None:
        self.assertEqual(FORGE_THEME.fonts.serif.reference_family, "Libre Baskerville")
        self.assertEqual(FORGE_THEME.fonts.sans.reference_family, "Public Sans")
        self.assertEqual(FORGE_THEME.fonts.mono.reference_family, "Roboto Mono")
        self.assertEqual(FORGE_THEME.fonts.serif.pdf_family, "Times")
        self.assertEqual(FORGE_THEME.fonts.sans.pdf_family, "Helvetica")
        self.assertEqual(FORGE_THEME.fonts.mono.pdf_family, "Courier")

    def test_shared_forge_constants_are_theme_backed(self) -> None:
        self.assertEqual(FORGE_CONTENT_X_MM, FORGE_THEME.layout.content_x_mm)
        self.assertEqual(FORGE_CONTENT_WIDTH_MM, FORGE_THEME.layout.content_width_mm)
        self.assertEqual(FORGE_SLATE_900, FORGE_THEME.palette.slate_900)
        self.assertEqual(FORGE_SERIF_FONT, FORGE_THEME.fonts.serif.pdf_family)
        self.assertEqual(FORGE_SANS_FONT, FORGE_THEME.fonts.sans.pdf_family)
        self.assertEqual(FORGE_MONO_FONT, FORGE_THEME.fonts.mono.pdf_family)
        self.assertEqual(FORGE_SYMBOLS_FONT, FORGE_THEME.fonts.symbols.pdf_family)

    def test_shard_watermark_omission_is_explicit(self) -> None:
        self.assertTrue(FORGE_THEME.omit_shard_watermark)


if __name__ == "__main__":
    unittest.main()
