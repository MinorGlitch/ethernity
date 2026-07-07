import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.render.direct_pdf import (
    FpdfSurface,
    PdfRect,
    TextAlign,
    TextBox,
    TextFitError,
    TextFitPolicy,
    TextStyle,
)
from ethernity.render.proofs import validate_pdf_has_pages


class TestDirectPdfTextBox(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = FpdfSurface(page_width_mm=100, page_height_mm=100)
        self.style = TextStyle(family="Helvetica", size_pt=10)

    def test_plan_wraps_text_and_records_non_overflow_proof(self) -> None:
        box = TextBox(
            component_id="instructions",
            text="Record all segment labels for this document set.",
            style=self.style,
            policy=TextFitPolicy.WRAP,
        )

        plan = box.plan(self.surface, PdfRect(10, 10, 32, 25))

        self.assertEqual(plan.component_id, "instructions")
        self.assertGreater(len(plan.lines), 1)
        self.assertFalse(plan.proof.overflow)
        self.assertEqual(plan.proof.overflow_line_count, 0)
        self.assertLessEqual(plan.proof.used_rect.width_mm, 32)
        self.assertLessEqual(plan.proof.used_rect.height_mm, 25)
        for line in plan.lines:
            self.assertGreaterEqual(line.x_mm, 10)
            self.assertLessEqual(line.x_mm + line.width_mm, 42)

    def test_plan_split_policy_keeps_overflow_lines_out_of_paint_plan(self) -> None:
        box = TextBox(
            component_id="fallback",
            text="AUTH MAIN SECTION CONTINUES ACROSS PAGES",
            style=self.style,
            policy=TextFitPolicy.SPLIT,
        )

        plan = box.plan(self.surface, PdfRect(0, 0, 18, self.surface.line_height(self.style)))

        self.assertEqual(len(plan.lines), 1)
        self.assertTrue(plan.proof.overflow)
        self.assertGreater(plan.proof.overflow_line_count, 0)
        self.assertEqual(len(plan.fit.overflow_lines), plan.proof.overflow_line_count)

    def test_plan_rejects_box_that_cannot_fit_one_line(self) -> None:
        box = TextBox(component_id="tiny", text="Nope", style=self.style)

        with self.assertRaisesRegex(TextFitError, "text box height cannot fit one line"):
            box.plan(self.surface, PdfRect(0, 0, 30, 0.1))

    def test_plan_rejects_zero_width_box(self) -> None:
        box = TextBox(component_id="zero-width", text="Nope", style=self.style)

        with self.assertRaisesRegex(ValueError, "text box width must be positive"):
            box.plan(self.surface, PdfRect(0, 0, 0, 10))

    def test_center_alignment_positions_line_inside_rect(self) -> None:
        box = TextBox(
            component_id="centered",
            text="Centered",
            style=self.style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        )
        rect = PdfRect(10, 10, 60, 20)

        plan = box.plan(self.surface, rect)
        line = plan.lines[0]

        self.assertGreater(line.x_mm, rect.x_mm)
        self.assertLess(line.x_mm + line.width_mm, rect.right_mm)

    def test_paint_writes_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "text_box.pdf"
            self.surface.add_page()
            box = TextBox(
                component_id="title",
                text="Direct PDF TextBox",
                style=TextStyle(family="Helvetica", size_pt=14),
                policy=TextFitPolicy.FAIL,
            )

            plan = box.plan(self.surface, PdfRect(10, 10, 70, 20))
            plan.paint(self.surface)
            self.surface.output(output_path)

            validate_pdf_has_pages(output_path)


if __name__ == "__main__":
    unittest.main()
