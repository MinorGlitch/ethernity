import unittest

from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.text_fit import (
    TextFitError,
    TextFitPolicy,
    fit_text_to_width,
)
from ethernity.render.direct_pdf.types import TextStyle


class TestDirectPdfTextFit(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = FpdfSurface(page_width_mm=100, page_height_mm=100)
        self.style = TextStyle(family="Helvetica", size_pt=12)

    def test_fail_policy_rejects_text_that_exceeds_width(self) -> None:
        with self.assertRaisesRegex(TextFitError, "text exceeds max_width_mm"):
            fit_text_to_width(
                self.surface,
                "this line is too wide",
                self.style,
                max_width_mm=8,
                policy=TextFitPolicy.FAIL,
            )

    def test_wrap_policy_splits_words_without_overflow(self) -> None:
        result = fit_text_to_width(
            self.surface,
            "Record all segment labels for this document set.",
            self.style,
            max_width_mm=28,
            policy=TextFitPolicy.WRAP,
        )

        self.assertGreater(len(result.lines), 1)
        self.assertLessEqual(result.width_mm, 28)
        self.assertEqual(result.overflow_lines, ())

    def test_wrap_policy_rejects_too_many_lines(self) -> None:
        with self.assertRaisesRegex(TextFitError, "wrapped text exceeds max_lines"):
            fit_text_to_width(
                self.surface,
                "Record all segment labels for this document set.",
                self.style,
                max_width_mm=25,
                max_lines=1,
                policy=TextFitPolicy.WRAP,
            )

    def test_wrap_policy_rejects_single_character_that_cannot_fit(self) -> None:
        with self.assertRaisesRegex(TextFitError, "single character exceeds max_width_mm"):
            fit_text_to_width(
                self.surface,
                "A",
                TextStyle(family="Helvetica", size_pt=12),
                max_width_mm=0.1,
                policy=TextFitPolicy.WRAP,
            )

    def test_split_policy_returns_overflow_lines(self) -> None:
        result = fit_text_to_width(
            self.surface,
            "Record all segment labels for this document set.",
            self.style,
            max_width_mm=25,
            max_lines=1,
            policy=TextFitPolicy.SPLIT,
        )

        self.assertEqual(len(result.lines), 1)
        self.assertGreater(len(result.overflow_lines), 0)
        self.assertTrue(result.split)

    def test_shrink_policy_reduces_font_size_to_satisfy_line_limit(self) -> None:
        result = fit_text_to_width(
            self.surface,
            "Important label",
            TextStyle(family="Helvetica", size_pt=24),
            max_width_mm=42,
            max_lines=1,
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8,
        )

        self.assertEqual(result.lines, ("Important label",))
        self.assertLess(result.style.size_pt, 24)
        self.assertLessEqual(result.width_mm, 42)

    def test_shrink_policy_raises_when_minimum_size_still_overflows(self) -> None:
        with self.assertRaisesRegex(TextFitError, "text cannot shrink enough to fit"):
            fit_text_to_width(
                self.surface,
                "many words that cannot fit into one line",
                TextStyle(family="Helvetica", size_pt=12),
                max_width_mm=12,
                max_lines=1,
                policy=TextFitPolicy.SHRINK,
                min_size_pt=11.5,
            )

    def test_shrink_policy_checks_exact_minimum_when_step_would_skip_it(self) -> None:
        text = "W" * 20
        minimum_style = TextStyle(family="Helvetica", size_pt=6.0)
        minimum_width_mm = self.surface.measure_text_width(text, minimum_style)

        result = fit_text_to_width(
            self.surface,
            text,
            TextStyle(family="Helvetica", size_pt=6.4),
            max_width_mm=minimum_width_mm,
            max_lines=1,
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        )

        self.assertEqual(result.lines, (text,))
        self.assertEqual(result.style.size_pt, 6.0)


if __name__ == "__main__":
    unittest.main()
