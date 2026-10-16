from __future__ import annotations

import math
import unittest

from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.text_measure import measured_grouped_line_length
from ethernity.render.direct_pdf.types import TextStyle


class TestDirectPdfTextMeasure(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = FpdfSurface(page_width_mm=100.0, page_height_mm=100.0)
        self.style = TextStyle(family="Helvetica", size_pt=10.0)

    def test_returns_longest_grouped_line_using_widest_alphabet_glyph(self) -> None:
        alphabet = "iW"
        group_size = 2
        two_groups = "WW WW"
        three_groups = "WW WW WW"
        max_width_mm = (
            self.surface.measure_text_width(two_groups, self.style)
            + self.surface.measure_text_width(three_groups, self.style)
        ) / 2.0

        line_length = measured_grouped_line_length(
            self.surface,
            style=self.style,
            alphabet=alphabet,
            group_size=group_size,
            max_width_mm=max_width_mm,
        )

        self.assertEqual(line_length, len(two_groups))
        self.assertLessEqual(
            self.surface.measure_text_width(two_groups, self.style),
            max_width_mm,
        )
        self.assertGreater(
            self.surface.measure_text_width(three_groups, self.style),
            max_width_mm,
        )

    def test_safety_margin_reduces_the_usable_group_count(self) -> None:
        one_group = "WW"
        two_groups = "WW WW"
        three_groups = "WW WW WW"
        two_group_width_mm = self.surface.measure_text_width(two_groups, self.style)
        three_group_width_mm = self.surface.measure_text_width(three_groups, self.style)
        max_width_mm = (two_group_width_mm + three_group_width_mm) / 2.0
        one_group_width_mm = self.surface.measure_text_width(one_group, self.style)
        safety_mm = max_width_mm - (one_group_width_mm + two_group_width_mm) / 2.0

        without_safety = measured_grouped_line_length(
            self.surface,
            style=self.style,
            alphabet="iW",
            group_size=2,
            max_width_mm=max_width_mm,
        )
        with_safety = measured_grouped_line_length(
            self.surface,
            style=self.style,
            alphabet="iW",
            group_size=2,
            max_width_mm=max_width_mm,
            safety_mm=safety_mm,
        )

        self.assertEqual(without_safety, len(two_groups))
        self.assertEqual(with_safety, len(one_group))

    def test_rejects_invalid_measurement_inputs(self) -> None:
        valid = {
            "style": self.style,
            "alphabet": "abc",
            "group_size": 2,
            "max_width_mm": 20.0,
            "safety_mm": 0.0,
        }
        invalid_cases = (
            ({"alphabet": ""}, "alphabet must be a non-empty string"),
            ({"alphabet": "a b"}, "alphabet must not contain whitespace"),
            ({"group_size": 0}, "group_size must be a positive integer"),
            ({"group_size": True}, "group_size must be a positive integer"),
            ({"max_width_mm": 0.0}, "max_width_mm must be finite and positive"),
            ({"max_width_mm": math.inf}, "max_width_mm must be finite and positive"),
            ({"safety_mm": -0.1}, "safety_mm must be finite and non-negative"),
            ({"safety_mm": math.nan}, "safety_mm must be finite and non-negative"),
            ({"safety_mm": 20.0}, "safety_mm must leave a positive usable width"),
        )

        for overrides, message in invalid_cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    measured_grouped_line_length(
                        self.surface,
                        **{**valid, **overrides},
                    )

    def test_rejects_width_that_cannot_fit_one_group(self) -> None:
        one_group_width_mm = self.surface.measure_text_width("WW", self.style)

        with self.assertRaisesRegex(ValueError, "cannot fit one encoded group"):
            measured_grouped_line_length(
                self.surface,
                style=self.style,
                alphabet="iW",
                group_size=2,
                max_width_mm=one_group_width_mm / 2.0,
            )


if __name__ == "__main__":
    unittest.main()
