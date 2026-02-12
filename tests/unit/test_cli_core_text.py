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

from ethernity.cli.core import text as text_module


class TestCliCoreText(unittest.TestCase):
    def test_append_hint(self) -> None:
        self.assertEqual(text_module.append_hint("Done.", "Try again"), "Done. Try again")
        self.assertEqual(text_module.append_hint("Done", "Try again"), "Done. Try again")
        self.assertEqual(text_module.append_hint("Done", ""), "Done")

    def test_format_qr_input_error_invalid_payload(self) -> None:
        result = text_module.format_qr_input_error(
            "crc mismatch while decoding",
            bad_payload_hint="Bad payload",
        )
        self.assertEqual(result, "Bad payload")

    def test_format_qr_input_error_no_qr_payload(self) -> None:
        explicit = text_module.format_qr_input_error(
            "no qr payloads found",
            bad_payload_hint="Bad payload",
            no_qr_hint="Nothing scanned",
        )
        fallback = text_module.format_qr_input_error(
            "no qr payloads found",
            bad_payload_hint="Bad payload",
        )
        self.assertEqual(explicit, "Nothing scanned")
        self.assertEqual(fallback, "Bad payload")

    def test_format_qr_input_error_scan_failed_with_hint(self) -> None:
        result = text_module.format_qr_input_error(
            "scan failed",
            bad_payload_hint="Bad payload",
            scan_failed_hint="check image quality",
        )
        self.assertEqual(result, "scan failed. check image quality")

    def test_format_qr_input_error_file_issue_with_hint(self) -> None:
        result = text_module.format_qr_input_error(
            "file not found",
            bad_payload_hint="Bad payload",
            file_hint="verify file path",
        )
        self.assertEqual(result, "file not found. verify file path")

    def test_format_qr_input_error_default_hint(self) -> None:
        result = text_module.format_qr_input_error(
            "unexpected problem",
            bad_payload_hint="Bad payload",
            default_hint="retry",
        )
        self.assertEqual(result, "unexpected problem. retry")

    def test_format_qr_input_error_fallback_message(self) -> None:
        result = text_module.format_qr_input_error(
            "unchanged message",
            bad_payload_hint="Bad payload",
        )
        self.assertEqual(result, "unchanged message")


if __name__ == "__main__":
    unittest.main()
