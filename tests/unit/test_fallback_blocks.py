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

from ethernity.render.fallback import (
    FallbackBlock,
    FallbackConsumerState,
    FallbackSectionData,
    consume_fallback_blocks,
    position_fallback_blocks,
)


class TestPositionFallbackBlocks(unittest.TestCase):
    def test_fallback_block_height_without_title(self) -> None:
        line_height = 4.0
        blocks = [
            FallbackBlock(
                title=None,
                section_title="",
                lines=["a", "b"],
                gap_lines=0,
                line_offset=0,
            )
        ]
        available = line_height * 2
        position_fallback_blocks(
            blocks,
            start_y=0.0,
            available_height=available,
            line_height=line_height,
        )
        self.assertEqual(blocks[0].height_mm, available)

    def test_fallback_block_height_with_title(self) -> None:
        line_height = 4.0
        blocks = [
            FallbackBlock(
                title="Main",
                section_title="Main",
                lines=["a", "b"],
                gap_lines=0,
                line_offset=0,
            )
        ]
        available = line_height * 3
        position_fallback_blocks(
            blocks,
            start_y=0.0,
            available_height=available,
            line_height=line_height,
        )
        self.assertEqual(blocks[0].height_mm, available)

    def test_multiple_blocks_positioning(self) -> None:
        line_height = 4.0
        blocks = [
            FallbackBlock(
                title="First",
                section_title="First",
                lines=["a", "b"],
                gap_lines=0,
                line_offset=0,
            ),
            FallbackBlock(
                title="Second",
                section_title="Second",
                lines=["c"],
                gap_lines=1,
                line_offset=0,
            ),
        ]
        position_fallback_blocks(
            blocks,
            start_y=10.0,
            available_height=100.0,
            line_height=line_height,
        )
        # First block: title (4) + 2 lines (8) = 12mm, starts at y=10
        self.assertEqual(blocks[0].y_mm, 10.0)
        self.assertEqual(blocks[0].height_mm, 12.0)
        # Second block: gap (4) + title (4) + 1 line (4) = 8mm for content
        # Starts at y = 10 + 12 + 4 (gap) = 26
        self.assertEqual(blocks[1].y_mm, 26.0)


class TestConsumeFallbackBlocks(unittest.TestCase):
    def test_single_section_fits_on_page(self) -> None:
        sections = [FallbackSectionData(title="Test", lines=("a", "b", "c"))]
        state = FallbackConsumerState()
        blocks = consume_fallback_blocks(sections, state, lines_capacity=10)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].title, "Test")
        self.assertEqual(blocks[0].lines, ["a", "b", "c"])
        self.assertEqual(state.section_idx, 1)

    def test_single_section_spans_pages(self) -> None:
        sections = [FallbackSectionData(title="Test", lines=("a", "b", "c", "d", "e"))]
        state = FallbackConsumerState()
        # Only room for title + 2 lines
        blocks = consume_fallback_blocks(sections, state, lines_capacity=3)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].title, "Test")
        self.assertEqual(blocks[0].lines, ["a", "b"])
        self.assertEqual(state.section_idx, 0)
        self.assertEqual(state.line_idx, 2)

        # Continue consuming
        blocks2 = consume_fallback_blocks(sections, state, lines_capacity=3)
        self.assertEqual(len(blocks2), 1)
        self.assertIsNone(blocks2[0].title)  # No title on continuation
        self.assertEqual(blocks2[0].lines, ["c", "d", "e"])
        self.assertEqual(state.section_idx, 1)

    def test_multiple_sections_with_gaps(self) -> None:
        sections = [
            FallbackSectionData(title="First", lines=("a", "b")),
            FallbackSectionData(title="Second", lines=("c", "d")),
        ]
        state = FallbackConsumerState()
        blocks = consume_fallback_blocks(sections, state, lines_capacity=20)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].gap_lines, 0)
        self.assertEqual(blocks[1].gap_lines, 1)

    def test_empty_section_skipped(self) -> None:
        sections = [
            FallbackSectionData(title="Empty", lines=()),
            FallbackSectionData(title="Content", lines=("a",)),
        ]
        state = FallbackConsumerState()
        blocks = consume_fallback_blocks(sections, state, lines_capacity=10)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].title, "Content")

    def test_line_offset_tracking(self) -> None:
        sections = [FallbackSectionData(title="Test", lines=("a", "b", "c", "d"))]
        state = FallbackConsumerState()
        # First page: title + 2 lines
        blocks1 = consume_fallback_blocks(sections, state, lines_capacity=3)
        self.assertEqual(blocks1[0].line_offset, 0)

        # Second page: 2 more lines
        blocks2 = consume_fallback_blocks(sections, state, lines_capacity=2)
        self.assertEqual(blocks2[0].line_offset, 2)


if __name__ == "__main__":
    unittest.main()
