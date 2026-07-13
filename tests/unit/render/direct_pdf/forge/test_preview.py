import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.forge.preview import (
    build_forge_recovery_preview_page,
    render_forge_recovery_preview,
)
from ethernity.render.direct_pdf.page_geometry import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    LETTER_HEIGHT_MM,
    LETTER_WIDTH_MM,
    PageGeometry,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.proofs import validate_pdf_has_pages


class TestDirectPdfForgePreview(unittest.TestCase):
    def test_build_preview_page_has_expected_forge_component_inventory(self) -> None:
        surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
        packaged_direct_pdf_assets().register_fonts(surface)

        page = build_forge_recovery_preview_page(surface)

        self.assertFalse(page.proof.overflow)
        self.assertIn("forge-heavy-header-rule", page.proof.component_ids)
        self.assertIn("forge-warning-panel", page.proof.component_ids)
        self.assertIn("forge-preview-qr", page.proof.component_ids)
        self.assertIn("forge-footer-left", page.proof.component_ids)
        self.assertEqual(len(page.proof.separation_constraints), 4)
        self.assertTrue(all(item.satisfied for item in page.proof.separation_constraints))

    def test_render_preview_writes_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "forge_preview.pdf"

            result = render_forge_recovery_preview(output_path)

            self.assertFalse(result.page_plan.proof.overflow)
            validate_pdf_has_pages(output_path)

    def test_letter_preview_contains_components_and_separates_footer(self) -> None:
        geometry = PageGeometry("LETTER", LETTER_WIDTH_MM, LETTER_HEIGHT_MM)
        surface = FpdfSurface(
            page_width_mm=geometry.width_mm,
            page_height_mm=geometry.height_mm,
        )
        packaged_direct_pdf_assets().register_fonts(surface)

        page = build_forge_recovery_preview_page(surface, geometry=geometry)

        self.assertAlmostEqual(page.rect.width_mm, LETTER_WIDTH_MM)
        self.assertAlmostEqual(page.rect.height_mm, LETTER_HEIGHT_MM)
        self.assertTrue(all(item.satisfied for item in page.proof.separation_constraints))
        for plan in page.plans:
            rect = plan.proof.rect
            self.assertGreaterEqual(rect.x_mm, 0.0)
            self.assertGreaterEqual(rect.y_mm, 0.0)
            self.assertLessEqual(rect.right_mm, page.rect.right_mm)
            self.assertLessEqual(rect.bottom_mm, page.rect.bottom_mm)
        fallback = next(plan for plan in page.plans if plan.component_id == "forge-fallback-panel")
        footer = next(plan for plan in page.plans if plan.component_id == "forge-footer-rule")
        self.assertAlmostEqual(
            footer.proof.rect.y_mm - fallback.proof.rect.bottom_mm,
            20.0,
        )

    def test_custom_portrait_geometry_controls_rendered_page_size(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "forge_preview_custom.pdf"
            geometry = PageGeometry("CUSTOM_PORTRAIT", 220.0, 310.0)

            result = render_forge_recovery_preview(output_path, geometry=geometry)

            self.assertAlmostEqual(result.page_plan.rect.width_mm, geometry.width_mm)
            self.assertAlmostEqual(result.page_plan.rect.height_mm, geometry.height_mm)
            self.assertTrue(
                all(item.satisfied for item in result.page_plan.proof.separation_constraints)
            )
            border = next(
                plan for plan in result.page_plan.plans if plan.component_id == "forge-page-border"
            )
            self.assertAlmostEqual(border.proof.rect.width_mm, 190.0)
            self.assertAlmostEqual(border.proof.rect.height_mm, 280.0)
            reader = validate_pdf_has_pages(output_path)
            width_mm = float(reader.pages[0].mediabox.width) * 25.4 / 72.0
            height_mm = float(reader.pages[0].mediabox.height) * 25.4 / 72.0
            self.assertAlmostEqual(width_mm, geometry.width_mm, places=1)
            self.assertAlmostEqual(height_mm, geometry.height_mm, places=1)


if __name__ == "__main__":
    unittest.main()
