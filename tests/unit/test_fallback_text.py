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

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render.fallback_text import fallback_lines_from_sections, fallback_section_title
from ethernity.render.types import FallbackSection


def _frame(frame_type: FrameType, data: bytes) -> Frame:
    return Frame(
        version=1,
        frame_type=frame_type,
        doc_id=b"\x11" * DOC_ID_LEN,
        index=0,
        total=1,
        data=data,
    )


class TestFallbackText(unittest.TestCase):
    def test_fallback_section_title_normalizes_non_empty_labels(self) -> None:
        self.assertEqual(fallback_section_title("  AUTH FRAME  "), "AUTH FRAME")
        self.assertIsNone(fallback_section_title("  "))
        self.assertIsNone(fallback_section_title(None))

    def test_fallback_lines_preserve_section_labels_and_separator(self) -> None:
        lines = fallback_lines_from_sections(
            (
                FallbackSection(label="AUTH FRAME", frame=_frame(FrameType.AUTH, b"auth")),
                FallbackSection(
                    label="MAIN FRAME",
                    frame=_frame(FrameType.MAIN_DOCUMENT, b"main"),
                ),
            ),
            group_size=4,
            line_length=64,
        )

        self.assertEqual(lines[0], "AUTH FRAME")
        self.assertIn("", lines)
        self.assertEqual(lines[lines.index("") + 1], "MAIN FRAME")


if __name__ == "__main__":
    unittest.main()
