import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from ethernity.render.direct_pdf.envelope import build_envelope_direct_plan, render_envelope_pdf
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.proofs import validate_pdf_has_pages
from ethernity.render.storage_paths import DEFAULT_LOGO_PATH


class TestDirectPdfEnvelope(unittest.TestCase):
    def test_build_c6_portrait_plan_matches_template_geometry(self) -> None:
        surface = FpdfSurface(page_width_mm=114, page_height_mm=162)

        plan = build_envelope_direct_plan(
            surface,
            kind="c6",
            logo_path=DEFAULT_LOGO_PATH,
            orientation="portrait",
        )

        self.assertEqual(plan.page_plan.proof.rect, PdfRect(0.0, 0.0, 114.0, 162.0))
        self.assertEqual(
            plan.page_plan.proof.component_ids,
            (
                "envelope-background",
                "envelope-frame",
                "envelope-logo",
            ),
        )
        self.assertEqual(plan.logo_rect, PdfRect(9.0, 49.0, 96.0, 64.0))
        self.assertFalse(plan.page_plan.proof.overflow)

    def test_build_landscape_plan_uses_rotated_page_size(self) -> None:
        surface = FpdfSurface(page_width_mm=162, page_height_mm=114)

        plan = build_envelope_direct_plan(
            surface,
            kind="c6",
            logo_path=DEFAULT_LOGO_PATH,
            orientation="landscape",
        )

        self.assertEqual(plan.page_plan.proof.rect, PdfRect(0.0, 0.0, 162.0, 114.0))
        self.assertAlmostEqual(plan.logo_rect.width_mm, 100.0)
        self.assertAlmostEqual(plan.logo_rect.height_mm, 100.0 * 2.0 / 3.0)
        self.assertFalse(plan.page_plan.proof.overflow)

    def test_custom_tall_logo_is_scaled_to_avoid_page_clipping(self) -> None:
        with TemporaryDirectory() as tmp:
            logo_path = Path(tmp) / "logo.png"
            Image.new("RGBA", (100, 400), (0, 0, 0, 255)).save(logo_path)
            surface = FpdfSurface(page_width_mm=114, page_height_mm=162)

            plan = build_envelope_direct_plan(
                surface,
                kind="c6",
                logo_path=logo_path,
                orientation="portrait",
            )

        self.assertEqual(plan.logo_rect.height_mm, 144.0)
        self.assertEqual(plan.logo_rect.y_mm, 9.0)
        self.assertFalse(plan.page_plan.proof.overflow)

    def test_missing_logo_raises_actionable_error(self) -> None:
        surface = FpdfSurface(page_width_mm=114, page_height_mm=162)

        with self.assertRaisesRegex(FileNotFoundError, "logo file not found"):
            build_envelope_direct_plan(surface, kind="c6", logo_path=Path("missing.png"))

    def test_render_envelope_pdf_writes_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "envelope-c6.pdf"

            result = render_envelope_pdf(output_path, kind="c6", logo_path=DEFAULT_LOGO_PATH)

            self.assertEqual(result, output_path)
            validate_pdf_has_pages(output_path)


if __name__ == "__main__":
    unittest.main()
