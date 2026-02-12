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
from unittest import mock

from ethernity.cli.io.fallback_parser import (
    FilterConfig,
    _is_valid_group_structure,
    _is_valid_zbase32_line,
    _parse_groups,
    filter_fallback_lines,
    parse_fallback_frame,
)
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.zbase32 import encode_zbase32


class TestIsValidZbase32Line(unittest.TestCase):
    def test_valid_lines(self) -> None:
        self.assertTrue(_is_valid_zbase32_line("ybndr fghj kmnp"))
        self.assertTrue(_is_valid_zbase32_line("YBNDR FGHJ KMNP"))
        self.assertTrue(_is_valid_zbase32_line("ybndr-fghj-kmnp"))

    def test_empty_line(self) -> None:
        self.assertFalse(_is_valid_zbase32_line(""))
        self.assertFalse(_is_valid_zbase32_line("   "))

    def test_invalid_characters(self) -> None:
        self.assertFalse(_is_valid_zbase32_line("ybndr 0123"))  # digits
        self.assertFalse(_is_valid_zbase32_line("ybndr @#$%"))  # special chars


class TestParseGroups(unittest.TestCase):
    def test_space_separated(self) -> None:
        self.assertEqual(_parse_groups("ybndr fghj kmnp"), ["ybndr", "fghj", "kmnp"])

    def test_dash_separated(self) -> None:
        self.assertEqual(_parse_groups("ybndr-fghj-kmnp"), ["ybndr", "fghj", "kmnp"])

    def test_mixed_separators(self) -> None:
        self.assertEqual(_parse_groups("ybndr-fghj kmnp"), ["ybndr", "fghj", "kmnp"])


class TestIsValidGroupStructure(unittest.TestCase):
    def test_all_full_length_groups(self) -> None:
        config = FilterConfig(max_group_length=4)
        self.assertTrue(_is_valid_group_structure(["ybnr", "fghj", "kmnp"], config))

    def test_short_final_part_allowed(self) -> None:
        config = FilterConfig(max_group_length=4)
        self.assertTrue(_is_valid_group_structure(["ybnr", "fghj", "km"], config))

    def test_short_non_final_part_rejected(self) -> None:
        config = FilterConfig(max_group_length=4)
        self.assertFalse(_is_valid_group_structure(["yb", "fghj", "kmnp"], config))

    def test_multiple_short_parts_rejected(self) -> None:
        config = FilterConfig(max_group_length=4)
        self.assertFalse(_is_valid_group_structure(["yb", "fg", "km"], config))

    def test_group_exceeds_max_length(self) -> None:
        config = FilterConfig(max_group_length=4)
        self.assertFalse(_is_valid_group_structure(["ybndr", "fghj", "kmnp"], config))

    def test_empty_parts_rejected(self) -> None:
        config = FilterConfig(max_group_length=4)
        self.assertFalse(_is_valid_group_structure([], config))


class TestFilterFallbackLines(unittest.TestCase):
    def test_valid_lines_pass(self) -> None:
        lines = ["ybnr fghj kmnp qrst", "ybnr fghj kmnp qrst"]
        filtered, skipped = filter_fallback_lines(lines)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(skipped, 0)

    def test_invalid_characters_filtered(self) -> None:
        lines = ["ybnr fghj kmnp qrst", "invalid @#$ line", "ybnr fghj kmnp qrst"]
        filtered, skipped = filter_fallback_lines(lines)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(skipped, 1)

    def test_empty_lines_ignored(self) -> None:
        lines = ["ybnr fghj kmnp qrst", "", "   ", "ybnr fghj kmnp qrst"]
        filtered, skipped = filter_fallback_lines(lines)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(skipped, 0)

    def test_short_lines_filtered_except_final(self) -> None:
        lines = ["ybnr fghj kmnp qrst", "yb"]  # short final line
        filtered, skipped = filter_fallback_lines(lines)
        self.assertEqual(len(filtered), 2)  # final short line kept
        self.assertEqual(skipped, 0)

    def test_short_line_alone_kept(self) -> None:
        lines = ["yb"]  # short line with no prior content
        filtered, skipped = filter_fallback_lines(lines)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(skipped, 0)

    def test_filter_config_does_not_reject_valid_zbase32_lines(self) -> None:
        lines = ["yb fg", "ybnr fghj kmnp qrst"]  # first line has only 2 groups
        config = FilterConfig(min_groups=3)
        filtered, skipped = filter_fallback_lines(lines, config)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(skipped, 0)

    def test_configurable_max_group_length(self) -> None:
        lines = ["ybndr fghjk kmnpq"]  # 5-char groups
        config = FilterConfig(max_group_length=5, min_groups=3)
        filtered, skipped = filter_fallback_lines(lines, config)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(skipped, 0)

    def test_default_config_used(self) -> None:
        lines = ["ybnr fghj kmnp qrst"]
        filtered, skipped = filter_fallback_lines(lines)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(skipped, 0)

    def test_parse_fallback_frame_accepts_ungrouped_single_line(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x31" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        encoded = encode_zbase32(encode_frame(frame))
        parsed, skipped = parse_fallback_frame([encoded], label="fallback")
        self.assertEqual(parsed.data, b"payload")
        self.assertEqual(skipped, 0)

    def test_parse_fallback_frame_rejects_line_limit_overflow(self) -> None:
        lines = ["ybndr", "fghej", "kmcpq"]
        with mock.patch("ethernity.cli.io.fallback_parser.MAX_FALLBACK_LINES", 2):
            with self.assertRaisesRegex(ValueError, "MAX_FALLBACK_LINES"):
                parse_fallback_frame(lines, label="fallback")

    def test_parse_fallback_frame_rejects_normalized_char_limit_overflow(self) -> None:
        lines = ["ybnd r", "fghe j"]
        with mock.patch("ethernity.cli.io.fallback_parser.MAX_FALLBACK_LINES", 10):
            with mock.patch("ethernity.cli.io.fallback_parser.MAX_FALLBACK_NORMALIZED_CHARS", 9):
                with self.assertRaisesRegex(ValueError, "MAX_FALLBACK_NORMALIZED_CHARS"):
                    parse_fallback_frame(lines, label="fallback")

    def test_parse_fallback_frame_accepts_exact_bound_edges(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x32" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"edge",
        )
        line = encode_zbase32(encode_frame(frame))
        normalized_chars = len(line.replace(" ", "").replace("-", ""))
        with mock.patch("ethernity.cli.io.fallback_parser.MAX_FALLBACK_LINES", 1):
            with mock.patch(
                "ethernity.cli.io.fallback_parser.MAX_FALLBACK_NORMALIZED_CHARS",
                normalized_chars,
            ):
                parsed, skipped = parse_fallback_frame([line], label="fallback")
        self.assertEqual(parsed.data, b"edge")
        self.assertEqual(skipped, 0)


if __name__ == "__main__":
    unittest.main()
