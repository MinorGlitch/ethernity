import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.render.direct_pdf import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    FpdfSurface,
    build_forge_recovery_preview_page,
    packaged_direct_pdf_assets,
    render_forge_recovery_preview,
)
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

    def test_render_preview_writes_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "forge_preview.pdf"

            result = render_forge_recovery_preview(output_path)

            self.assertFalse(result.page_plan.proof.overflow)
            validate_pdf_has_pages(output_path)


if __name__ == "__main__":
    unittest.main()
