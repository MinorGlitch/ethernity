import unittest
from unittest import mock

from ethernity.render.text import (
    body_line_height,
    font_line_height,
    header_height,
    is_fallback_label_line,
    label_line_height_text,
    lines_height,
    page_format,
    text_block_width,
    wrap_lines_to_width,
)


class MockTextBlockSpec:
    """Mock TextBlockSpec for testing."""

    def __init__(
        self,
        *,
        indent_mm: float = 0,
        label: str | None = None,
        label_layout: str = "row",
        label_column_mm: float = 30,
        label_gap_mm: float = 5,
        font_size: float = 10,
        line_height_mm: float | None = None,
        label_size: float | None = None,
        label_line_height_mm: float | None = None,
        lines: list[str] | None = None,
    ) -> None:
        self.indent_mm = indent_mm
        self.label = label
        self.label_layout = label_layout
        self.label_column_mm = label_column_mm
        self.label_gap_mm = label_gap_mm
        self.font_size = font_size
        self.line_height_mm = line_height_mm
        self.label_size = label_size
        self.label_line_height_mm = label_line_height_mm
        self.lines = lines or []


class MockPageSpec:
    """Mock PageSpec for testing."""

    def __init__(
        self,
        *,
        size: str = "A4",
        width_mm: float | None = None,
        height_mm: float | None = None,
    ) -> None:
        self.size = size
        self.width_mm = width_mm
        self.height_mm = height_mm


class MockHeaderSpec:
    """Mock HeaderSpec for testing."""

    def __init__(
        self,
        *,
        title: str | None = None,
        subtitle: str | None = None,
        doc_id_label: str | None = None,
        doc_id: str | None = None,
        page_label: str | None = None,
        divider_enabled: bool = False,
        divider_gap_mm: float = 2,
        divider_thickness_mm: float = 0.5,
        layout: str = "stacked",
        title_size: float = 16,
        subtitle_size: float = 12,
        meta_size: float = 10,
    ) -> None:
        self.title = title
        self.subtitle = subtitle
        self.doc_id_label = doc_id_label
        self.doc_id = doc_id
        self.page_label = page_label
        self.divider_enabled = divider_enabled
        self.divider_gap_mm = divider_gap_mm
        self.divider_thickness_mm = divider_thickness_mm
        self.layout = layout
        self.title_size = title_size
        self.subtitle_size = subtitle_size
        self.meta_size = meta_size


class TestPageFormat(unittest.TestCase):
    """Tests for page_format function."""

    def test_named_size(self) -> None:
        """Test named page size."""
        cfg = MockPageSpec(size="A4")
        result = page_format(cfg)
        self.assertEqual(result, "A4")

    def test_custom_dimensions(self) -> None:
        """Test custom width and height."""
        cfg = MockPageSpec(width_mm=200, height_mm=300)
        result = page_format(cfg)
        self.assertEqual(result, (200.0, 300.0))

    def test_partial_dimensions_uses_named(self) -> None:
        """Test that partial dimensions fall back to named size."""
        cfg = MockPageSpec(size="Letter", width_mm=200, height_mm=None)
        result = page_format(cfg)
        self.assertEqual(result, "Letter")


class TestFontLineHeight(unittest.TestCase):
    """Tests for font_line_height function."""

    def test_default_multiplier(self) -> None:
        """Test with default multiplier."""
        result = font_line_height(10)
        # 10 * 0.3527777778 * 1.2 = 4.233...
        self.assertAlmostEqual(result, 4.2333, places=3)

    def test_custom_multiplier(self) -> None:
        """Test with custom multiplier."""
        result = font_line_height(10, multiplier=1.5)
        # 10 * 0.3527777778 * 1.5 = 5.2916...
        self.assertAlmostEqual(result, 5.2916, places=3)

    def test_various_sizes(self) -> None:
        """Test with various font sizes."""
        for size in [8, 10, 12, 14, 16]:
            result = font_line_height(size)
            self.assertGreater(result, 0)
            self.assertLess(result, size)  # Should be less than pt size in mm


class TestBodyLineHeight(unittest.TestCase):
    """Tests for body_line_height function."""

    def test_explicit_line_height(self) -> None:
        """Test with explicit line height."""
        cfg = MockTextBlockSpec(line_height_mm=6.0)
        result = body_line_height(cfg)
        self.assertEqual(result, 6.0)

    def test_computed_from_font_size(self) -> None:
        """Test computed from font size."""
        cfg = MockTextBlockSpec(font_size=12, line_height_mm=None)
        result = body_line_height(cfg)
        expected = font_line_height(12)
        self.assertAlmostEqual(result, expected, places=3)


class TestLabelLineHeightText(unittest.TestCase):
    """Tests for label_line_height_text function."""

    def test_explicit_label_height(self) -> None:
        """Test with explicit label line height."""
        cfg = MockTextBlockSpec(label_line_height_mm=5.0)
        result = label_line_height_text(cfg)
        self.assertEqual(result, 5.0)

    def test_from_label_size(self) -> None:
        """Test computed from label size."""
        cfg = MockTextBlockSpec(label_size=14, label_line_height_mm=None)
        result = label_line_height_text(cfg)
        expected = font_line_height(14)
        self.assertAlmostEqual(result, expected, places=3)

    def test_falls_back_to_font_size(self) -> None:
        """Test fallback to font size when no label size."""
        cfg = MockTextBlockSpec(font_size=10, label_size=None, label_line_height_mm=None)
        result = label_line_height_text(cfg)
        expected = font_line_height(10)
        self.assertAlmostEqual(result, expected, places=3)


class TestTextBlockWidth(unittest.TestCase):
    """Tests for text_block_width function."""

    def test_no_indent_no_label(self) -> None:
        """Test with no indent and no label."""
        cfg = MockTextBlockSpec(indent_mm=0, label=None)
        result = text_block_width(cfg, usable_w=100)
        self.assertEqual(result, 100)

    def test_with_indent(self) -> None:
        """Test with indent."""
        cfg = MockTextBlockSpec(indent_mm=10, label=None)
        result = text_block_width(cfg, usable_w=100)
        self.assertEqual(result, 90)

    def test_with_column_label(self) -> None:
        """Test with column layout label."""
        cfg = MockTextBlockSpec(
            indent_mm=5,
            label="Label",
            label_layout="column",
            label_column_mm=30,
            label_gap_mm=5,
        )
        result = text_block_width(cfg, usable_w=100)
        # 100 - 5 - 30 - 5 = 60
        self.assertEqual(result, 60)

    def test_with_row_label(self) -> None:
        """Test with row layout label (doesn't reduce width)."""
        cfg = MockTextBlockSpec(
            indent_mm=5,
            label="Label",
            label_layout="row",
            label_column_mm=30,
            label_gap_mm=5,
        )
        result = text_block_width(cfg, usable_w=100)
        # Row layout doesn't reduce width: 100 - 5 = 95
        self.assertEqual(result, 95)

    def test_minimum_width(self) -> None:
        """Test that minimum width is 1.0."""
        cfg = MockTextBlockSpec(indent_mm=200, label=None)
        result = text_block_width(cfg, usable_w=100)
        self.assertEqual(result, 1.0)


class TestIsFallbackLabelLine(unittest.TestCase):
    """Tests for is_fallback_label_line function."""

    def test_valid_label_line(self) -> None:
        """Test valid fallback label line."""
        self.assertTrue(is_fallback_label_line("=== MAIN ==="))
        self.assertTrue(is_fallback_label_line("=== AUTH ==="))
        self.assertTrue(is_fallback_label_line("  === LABEL ===  "))

    def test_invalid_label_lines(self) -> None:
        """Test invalid fallback label lines."""
        self.assertFalse(is_fallback_label_line("======"))  # 6 chars, at threshold
        self.assertFalse(is_fallback_label_line("regular text"))
        self.assertFalse(is_fallback_label_line("=== no end"))
        self.assertFalse(is_fallback_label_line("no start ==="))
        self.assertFalse(is_fallback_label_line(""))

    def test_boundary_label_line(self) -> None:
        """Test label line at boundary (7 chars with === on both ends)."""
        # "=== ===" is 7 chars, starts with === and ends with ===
        # This is technically valid per the function implementation
        self.assertTrue(is_fallback_label_line("=== ==="))


class TestHeaderHeight(unittest.TestCase):
    """Tests for header_height function."""

    def test_empty_header(self) -> None:
        """Test empty header returns minimum."""
        cfg = MockHeaderSpec()
        result = header_height(cfg, minimum=10)
        self.assertEqual(result, 10)

    def test_title_only(self) -> None:
        """Test header with title only."""
        cfg = MockHeaderSpec(title="Test Title", title_size=16)
        result = header_height(cfg, minimum=0)
        self.assertGreater(result, 0)

    def test_with_divider(self) -> None:
        """Test header with divider adds height."""
        cfg_no_div = MockHeaderSpec(title="Test", divider_enabled=False)
        cfg_with_div = MockHeaderSpec(
            title="Test",
            divider_enabled=True,
            divider_gap_mm=3,
            divider_thickness_mm=0.5,
        )
        h_no_div = header_height(cfg_no_div, minimum=0)
        h_with_div = header_height(cfg_with_div, minimum=0)
        self.assertGreater(h_with_div, h_no_div)
        self.assertAlmostEqual(h_with_div - h_no_div, 3.5, places=1)

    def test_split_layout(self) -> None:
        """Test split layout uses max of left/right."""
        cfg = MockHeaderSpec(
            title="Title",
            subtitle="Subtitle",
            doc_id_label="ID:",
            doc_id="ABC123",
            layout="split",
        )
        result = header_height(cfg, minimum=0)
        self.assertGreater(result, 0)

    def test_stacked_layout(self) -> None:
        """Test stacked layout adds heights."""
        cfg = MockHeaderSpec(
            title="Title",
            subtitle="Subtitle",
            doc_id_label="ID:",
            doc_id="ABC123",
            layout="stacked",
        )
        result = header_height(cfg, minimum=0)
        self.assertGreater(result, 0)


class TestLinesHeight(unittest.TestCase):
    """Tests for lines_height function."""

    def test_no_lines_no_label(self) -> None:
        """Test with no lines and no label."""
        cfg = MockTextBlockSpec(lines=[], label=None)
        result = lines_height(cfg, [])
        self.assertEqual(result, 0.0)

    def test_lines_no_label(self) -> None:
        """Test with lines but no label."""
        cfg = MockTextBlockSpec(lines=[], label=None, font_size=10)
        lines = ["line1", "line2", "line3"]
        result = lines_height(cfg, lines)
        expected = 3 * body_line_height(cfg)
        self.assertAlmostEqual(result, expected, places=3)

    def test_label_only(self) -> None:
        """Test with label but no lines."""
        cfg = MockTextBlockSpec(lines=[], label="Label", font_size=10)
        result = lines_height(cfg, [])
        expected = label_line_height_text(cfg)
        self.assertAlmostEqual(result, expected, places=3)

    def test_column_layout(self) -> None:
        """Test column layout uses max height."""
        cfg = MockTextBlockSpec(
            lines=[],
            label="Label",
            label_layout="column",
            font_size=10,
        )
        lines = ["line1", "line2"]
        result = lines_height(cfg, lines)
        body_h = 2 * body_line_height(cfg)
        label_h = label_line_height_text(cfg)
        expected = max(body_h, label_h)
        self.assertAlmostEqual(result, expected, places=3)

    def test_row_layout(self) -> None:
        """Test row layout adds heights."""
        cfg = MockTextBlockSpec(
            lines=[],
            label="Label",
            label_layout="row",
            label_gap_mm=5,
            font_size=10,
        )
        lines = ["line1", "line2"]
        result = lines_height(cfg, lines)
        body_h = 2 * body_line_height(cfg)
        label_h = label_line_height_text(cfg)
        expected = label_h + 5 + body_h
        self.assertAlmostEqual(result, expected, places=3)


class TestWrapLinesToWidth(unittest.TestCase):
    """Tests for wrap_lines_to_width function."""

    def test_empty_input(self) -> None:
        """Test with empty input."""
        pdf = mock.MagicMock()
        result = wrap_lines_to_width(pdf, [], max_width=100)
        self.assertEqual(result, [])

    def test_empty_line_preserved(self) -> None:
        """Test that empty lines are preserved."""
        pdf = mock.MagicMock()
        pdf.get_string_width.return_value = 10
        result = wrap_lines_to_width(pdf, ["text", "", "more"], max_width=100)
        self.assertIn("", result)

    def test_short_lines_unchanged(self) -> None:
        """Test that short lines are not wrapped."""
        pdf = mock.MagicMock()
        pdf.get_string_width.return_value = 10  # All strings fit
        lines = ["short", "text"]
        result = wrap_lines_to_width(pdf, lines, max_width=100)
        self.assertEqual(result, ["short", "text"])

    def test_wrapping_at_spaces(self) -> None:
        """Test that wrapping occurs at spaces."""
        pdf = mock.MagicMock()

        def mock_width(s):
            return len(s) * 5  # 5mm per character

        pdf.get_string_width.side_effect = mock_width

        lines = ["word1 word2 word3"]
        result = wrap_lines_to_width(pdf, lines, max_width=35)
        # "word1 word2" = 55mm > 35mm, so should wrap
        self.assertGreater(len(result), 1)

    def test_long_word_breaks(self) -> None:
        """Test that very long words are broken."""
        pdf = mock.MagicMock()

        def mock_width(s):
            return len(s) * 10  # 10mm per character

        pdf.get_string_width.side_effect = mock_width

        lines = ["superlongword"]
        result = wrap_lines_to_width(pdf, lines, max_width=50)
        # Word is 130mm, must be broken into chunks
        self.assertGreater(len(result), 1)


if __name__ == "__main__":
    unittest.main()
