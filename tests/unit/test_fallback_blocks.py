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

from ethernity.render.fallback import position_fallback_blocks


class TestFallbackBlocks(unittest.TestCase):
    def test_fallback_block_height_without_title(self) -> None:
        line_height = 4.0
        blocks = [{"title": None, "lines": ["a", "b"], "gap_lines": 0}]
        available = line_height * 2
        position_fallback_blocks(
            blocks,
            start_y=0.0,
            available_height=available,
            line_height=line_height,
        )
        self.assertEqual(blocks[0]["height_mm"], available)

    def test_fallback_block_height_with_title(self) -> None:
        line_height = 4.0
        blocks = [{"title": "Main", "lines": ["a", "b"], "gap_lines": 0}]
        available = line_height * 3
        position_fallback_blocks(
            blocks,
            start_y=0.0,
            available_height=available,
            line_height=line_height,
        )
        self.assertEqual(blocks[0]["height_mm"], available)


if __name__ == "__main__":
    unittest.main()
