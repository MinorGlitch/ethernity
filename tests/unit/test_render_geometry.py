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
    """Tests for calc_cells function."""

    def test_basic_calculation(self) -> None:
        """Test basic cell count calculation."""
        # 100mm usable, 20mm cells, 5mm gaps
        # Each cell+gap = 25mm, so 100/25 = 4 cells (with remaining gap not needed)
        result = calc_cells(usable=100, cell=20, gap=5, max_cells=None)
        self.assertEqual(result, 4)

    def test_exact_fit(self) -> None:
        """Test when cells fit exactly."""
        # 3 cells * 30mm + 2 gaps * 5mm = 100mm
        result = calc_cells(usable=100, cell=30, gap=5, max_cells=None)
        # Formula: (100 + 5) // (30 + 5) = 105 // 35 = 3
        self.assertEqual(result, 3)

    def test_max_cells_limits(self) -> None:
        """Test that max_cells limits the result."""
        result = calc_cells(usable=100, cell=10, gap=2, max_cells=3)
        self.assertEqual(result, 3)

    def test_max_cells_not_limiting(self) -> None:
        """Test max_cells when it's larger than calculated."""
        result = calc_cells(usable=50, cell=20, gap=5, max_cells=10)
        # (50 + 5) // (20 + 5) = 55 // 25 = 2
        self.assertEqual(result, 2)

    def test_single_cell(self) -> None:
        """Test when only one cell fits."""
        result = calc_cells(usable=25, cell=20, gap=10, max_cells=None)
        # (25 + 10) // (20 + 10) = 35 // 30 = 1
        self.assertEqual(result, 1)

    def test_zero_gap(self) -> None:
        """Test with zero gap between cells."""
        result = calc_cells(usable=100, cell=25, gap=0, max_cells=None)
        self.assertEqual(result, 4)

    def test_large_cell_small_space(self) -> None:
        """Test when cell is larger than usable space."""
        result = calc_cells(usable=10, cell=20, gap=5, max_cells=None)
        self.assertEqual(result, 0)


class TestExpandGapToFill(unittest.TestCase):
    """Tests for expand_gap_to_fill function."""

    def test_basic_expansion(self) -> None:
        """Test basic gap expansion."""
        # 100mm usable, 3 cols * 20mm cells + 2 gaps * 5mm = 70mm
        # Extra = 30mm, distributed over 2 gaps = 15mm each
        result = expand_gap_to_fill(usable_w=100, cell_w=20, gap=5, cols=3)
        self.assertAlmostEqual(result, 20.0)  # 5 + 30/2 = 20

    def test_single_column(self) -> None:
        """Test with single column (no gap expansion possible)."""
        result = expand_gap_to_fill(usable_w=100, cell_w=20, gap=5, cols=1)
        self.assertEqual(result, 5)

    def test_no_extra_space(self) -> None:
        """Test when content exactly fills space."""
        # 2 cells * 45mm + 1 gap * 10mm = 100mm exactly
        result = expand_gap_to_fill(usable_w=100, cell_w=45, gap=10, cols=2)
        self.assertEqual(result, 10)

    def test_negative_extra_space(self) -> None:
        """Test when content is larger than space (no change)."""
        result = expand_gap_to_fill(usable_w=50, cell_w=30, gap=5, cols=3)
        # 3*30 + 2*5 = 100 > 50, so no expansion
        self.assertEqual(result, 5)

    def test_zero_cols(self) -> None:
        """Test with zero columns."""
        result = expand_gap_to_fill(usable_w=100, cell_w=20, gap=5, cols=0)
        self.assertEqual(result, 5)


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
    """Tests for groups_from_line_length function."""

    def test_basic_groups(self) -> None:
        """Test basic group calculation."""
        # Line length 80, group size 4 => groups separated by spaces
        # 4 chars + 1 space = 5 per group, 80/5 = 16 groups (roughly)
        groups = groups_from_line_length(line_length=80, group_size=4)
        self.assertEqual(groups, 16)  # (80 + 1) // (4 + 1) = 16

    def test_single_group(self) -> None:
        """Test when line length equals group size."""
        groups = groups_from_line_length(line_length=4, group_size=4)
        self.assertEqual(groups, 1)

    def test_smaller_than_group(self) -> None:
        """Test when line length is smaller than group size."""
        groups = groups_from_line_length(line_length=2, group_size=4)
        self.assertEqual(groups, 1)


class TestLineLengthFromGroups(unittest.TestCase):
    """Tests for line_length_from_groups function."""

    def test_basic_line_length(self) -> None:
        """Test basic line length calculation."""
        # 16 groups * (4 + 1) - 1 = 79
        length = line_length_from_groups(groups=16, group_size=4)
        self.assertEqual(length, 79)

    def test_single_group(self) -> None:
        """Test line length for single group."""
        length = line_length_from_groups(groups=1, group_size=4)
        self.assertEqual(length, 4)

    def test_roundtrip(self) -> None:
        """Test that groups_from_line_length and line_length_from_groups are inverse-ish."""
        for original_groups in [1, 5, 10, 20]:
            length = line_length_from_groups(groups=original_groups, group_size=4)
            recovered = groups_from_line_length(line_length=length, group_size=4)
            self.assertEqual(recovered, original_groups)


if __name__ == "__main__":
    unittest.main()
