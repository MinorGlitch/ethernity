# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

import unittest

from ethernity.render.geometry import (
    adjust_rows_for_fallback,
    calc_cells,
    expand_gap_to_fill,
    fallback_lines_per_page,
    fallback_lines_per_page_text_only,
    groups_from_line_length,
    line_length_from_groups,
)


class TestCalcCells(unittest.TestCase):
    def test_calc_cells_cases(self) -> None:
        cases = (
            {
                "name": "basic",
                "usable": 100,
                "cell": 20,
                "gap": 5,
                "max_cells": None,
                "expected": 4,
            },
            {
                "name": "exact-fit",
                "usable": 100,
                "cell": 30,
                "gap": 5,
                "max_cells": None,
                "expected": 3,
            },
            {
                "name": "max-limited",
                "usable": 100,
                "cell": 10,
                "gap": 2,
                "max_cells": 3,
                "expected": 3,
            },
            {
                "name": "max-not-limiting",
                "usable": 50,
                "cell": 20,
                "gap": 5,
                "max_cells": 10,
                "expected": 2,
            },
            {
                "name": "single-cell",
                "usable": 25,
                "cell": 20,
                "gap": 10,
                "max_cells": None,
                "expected": 1,
            },
            {
                "name": "zero-gap",
                "usable": 100,
                "cell": 25,
                "gap": 0,
                "max_cells": None,
                "expected": 4,
            },
            {
                "name": "cell-larger-than-space",
                "usable": 10,
                "cell": 20,
                "gap": 5,
                "max_cells": None,
                "expected": 0,
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                result = calc_cells(
                    usable=case["usable"],
                    cell=case["cell"],
                    gap=case["gap"],
                    max_cells=case["max_cells"],
                )
                self.assertEqual(result, case["expected"])


class TestExpandGapToFill(unittest.TestCase):
    def test_expand_gap_to_fill_cases(self) -> None:
        cases = (
            {
                "name": "basic-expansion",
                "usable_w": 100,
                "cell_w": 20,
                "gap": 5,
                "cols": 3,
                "expected": 20.0,
                "approx": True,
            },
            {
                "name": "single-column",
                "usable_w": 100,
                "cell_w": 20,
                "gap": 5,
                "cols": 1,
                "expected": 5,
                "approx": False,
            },
            {
                "name": "no-extra-space",
                "usable_w": 100,
                "cell_w": 45,
                "gap": 10,
                "cols": 2,
                "expected": 10,
                "approx": False,
            },
            {
                "name": "negative-extra-space",
                "usable_w": 50,
                "cell_w": 30,
                "gap": 5,
                "cols": 3,
                "expected": 5,
                "approx": False,
            },
            {
                "name": "zero-cols",
                "usable_w": 100,
                "cell_w": 20,
                "gap": 5,
                "cols": 0,
                "expected": 5,
                "approx": False,
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                result = expand_gap_to_fill(
                    usable_w=case["usable_w"],
                    cell_w=case["cell_w"],
                    gap=case["gap"],
                    cols=case["cols"],
                )
                if case["approx"]:
                    self.assertAlmostEqual(result, case["expected"])
                else:
                    self.assertEqual(result, case["expected"])


class TestAdjustRowsForFallback(unittest.TestCase):
    """Tests for adjust_rows_for_fallback function."""

    def test_rows_fit(self) -> None:
        """Test when rows fit with enough space for fallback."""
        result = adjust_rows_for_fallback(
            rows=3,
            grid_start_y=50,
            page_h=300,
            margin=10,
            qr_size=30,
            gap=5,
            line_height=5,
            min_lines=5,
        )
        self.assertEqual(result, 3)

    def test_rows_reduced(self) -> None:
        """Test when rows must be reduced for fallback space."""
        result = adjust_rows_for_fallback(
            rows=10,
            grid_start_y=50,
            page_h=200,
            margin=10,
            qr_size=30,
            gap=5,
            line_height=5,
            min_lines=10,
        )
        self.assertLess(result, 10)
        self.assertGreater(result, 0)

    def test_page_too_small_raises(self) -> None:
        """Test that ValueError is raised when page is too small."""
        with self.assertRaises(ValueError) as ctx:
            adjust_rows_for_fallback(
                rows=1,
                grid_start_y=290,
                page_h=300,
                margin=10,
                qr_size=30,
                gap=5,
                line_height=5,
                min_lines=100,
            )
        self.assertIn("too small", str(ctx.exception).lower())


class TestFallbackLinesPerPage(unittest.TestCase):
    """Tests for fallback_lines_per_page function."""

    def test_basic_calculation(self) -> None:
        """Test basic lines calculation."""
        lines = fallback_lines_per_page(
            rows=2,
            grid_start_y=50,
            page_h=300,
            margin=10,
            qr_size=30,
            gap=5,
            line_height=5,
        )
        # Grid height = 2*30 + 1*5 = 65
        # Leftover = 300 - 50 - 65 - 10 = 175
        # Lines = 175 / 5 = 35
        self.assertEqual(lines, 35)

    def test_minimum_one_line(self) -> None:
        """Test that at least one line is returned."""
        lines = fallback_lines_per_page(
            rows=10,
            grid_start_y=50,
            page_h=400,
            margin=10,
            qr_size=30,
            gap=5,
            line_height=100,
        )
        self.assertGreaterEqual(lines, 1)


class TestFallbackLinesPerPageTextOnly(unittest.TestCase):
    """Tests for fallback_lines_per_page_text_only function."""

    def test_basic_calculation(self) -> None:
        """Test basic text-only lines calculation."""
        lines = fallback_lines_per_page_text_only(
            content_start_y=50,
            page_h=300,
            margin=10,
            line_height=5,
        )
        # Leftover = 300 - 50 - 10 = 240
        # Lines = 240 / 5 = 48
        self.assertEqual(lines, 48)

    def test_minimum_one_line(self) -> None:
        """Test that at least one line is returned."""
        lines = fallback_lines_per_page_text_only(
            content_start_y=290,
            page_h=300,
            margin=10,
            line_height=100,
        )
        self.assertGreaterEqual(lines, 1)


class TestGroupsFromLineLength(unittest.TestCase):
    def test_groups_from_line_length_cases(self) -> None:
        cases = (
            {"line_length": 80, "group_size": 4, "expected": 16},
            {"line_length": 4, "group_size": 4, "expected": 1},
            {"line_length": 2, "group_size": 4, "expected": 1},
        )
        for case in cases:
            with self.subTest(case=case):
                groups = groups_from_line_length(
                    line_length=case["line_length"],
                    group_size=case["group_size"],
                )
                self.assertEqual(groups, case["expected"])


class TestLineLengthFromGroups(unittest.TestCase):
    def test_line_length_from_groups_cases(self) -> None:
        cases = (
            {"groups": 16, "group_size": 4, "expected": 79},
            {"groups": 1, "group_size": 4, "expected": 4},
        )
        for case in cases:
            with self.subTest(case=case):
                length = line_length_from_groups(
                    groups=case["groups"],
                    group_size=case["group_size"],
                )
                self.assertEqual(length, case["expected"])

    def test_roundtrip(self) -> None:
        """Test that groups_from_line_length and line_length_from_groups are inverse-ish."""
        for original_groups in [1, 5, 10, 20]:
            length = line_length_from_groups(groups=original_groups, group_size=4)
            recovered = groups_from_line_length(line_length=length, group_size=4)
            self.assertEqual(recovered, original_groups)


if __name__ == "__main__":
    unittest.main()
