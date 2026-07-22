import unittest

from ethernity.render.direct_pdf.assets import (
    MATERIAL_SYMBOLS_FAMILY,
    PUBLIC_SANS_FAMILY,
    ROBOTO_MONO_FAMILY,
    packaged_direct_pdf_assets,
)
from ethernity.render.direct_pdf.sentinel.common import (
    SENTINEL_BACKGROUND,
    SENTINEL_CONTENT_WIDTH_MM,
    SENTINEL_CONTENT_X_MM,
    SENTINEL_ORANGE,
    SENTINEL_PAGE_RECT,
    build_sentinel_surface,
)
from ethernity.render.direct_pdf.sentinel.theme import (
    SENTINEL_THEME,
    SentinelLayoutScale,
    SentinelTextScale,
)


class TestDirectPdfSentinelTheme(unittest.TestCase):
    def test_theme_records_bundled_font_families(self) -> None:
        self.assertEqual(SENTINEL_THEME.fonts.sans, PUBLIC_SANS_FAMILY)
        self.assertEqual(SENTINEL_THEME.fonts.mono, ROBOTO_MONO_FAMILY)
        self.assertEqual(SENTINEL_THEME.fonts.symbols, MATERIAL_SYMBOLS_FAMILY)

    def test_shell_constants_are_theme_backed(self) -> None:
        self.assertIsInstance(SENTINEL_THEME.layout, SentinelLayoutScale)
        self.assertIsInstance(SENTINEL_THEME.text, SentinelTextScale)
        self.assertEqual(SENTINEL_CONTENT_X_MM, SENTINEL_THEME.layout.content_x_mm)
        self.assertEqual(SENTINEL_CONTENT_WIDTH_MM, SENTINEL_THEME.layout.content_width_mm)
        self.assertEqual(SENTINEL_PAGE_RECT.width_mm, SENTINEL_THEME.layout.page_width_mm)
        self.assertEqual(SENTINEL_PAGE_RECT.height_mm, SENTINEL_THEME.layout.page_height_mm)
        self.assertEqual(SENTINEL_ORANGE, SENTINEL_THEME.palette.primary)
        self.assertEqual(SENTINEL_BACKGROUND, SENTINEL_THEME.palette.background)

    def test_surface_uses_sentinel_page_geometry(self) -> None:
        surface = build_sentinel_surface()
        packaged_direct_pdf_assets().register_fonts(surface)
        text_width = surface.measure_text_width(
            "SENTINEL",
            SENTINEL_THEME.sans_style(
                size_pt=SENTINEL_THEME.text.header_meta_pt,
                color=SENTINEL_THEME.palette.text_main,
            ),
        )

        self.assertGreater(text_width, 0.0)


if __name__ == "__main__":
    unittest.main()
