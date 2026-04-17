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

from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.cli.shared.io.recovery_pdf import (
    _extract_pdf_fallback_lines,
    extract_pdf_fallback_line_candidates_from_pdf,
)


class TestRecoveryPdf(unittest.TestCase):
    def test_extract_pdf_fallback_line_candidates_considers_layout_mode(self) -> None:
        class _FakePage:
            def extract_text(self, *args, **kwargs):
                visitor_text = kwargs.get("visitor_text")
                extraction_mode = kwargs.get("extraction_mode", "plain")
                if visitor_text is not None:
                    for piece in ("RECOVERY", "DOCUMENT"):
                        visitor_text(piece, None, None, None, None)
                    return ""
                if extraction_mode == "layout":
                    return (
                        "AUTH FRAME\n"
                        "01. efey noqg 8wo1 858f z1io yyc7 yg1g ghdi cjcn "
                        "bhew xddr ebp3 f7d3 it74\n"
                        "MAIN FRAME\n"
                        "01. efey ntgg 8wo1 858f z1io yyqg ytos q3jp cizg "
                        "ghu3 qb4g 155q f3zz r33x\n"
                    )
                return "RECOVERY\nDOCUMENT\n"

        class _FakeReader:
            pages = [_FakePage()]

        candidates = extract_pdf_fallback_line_candidates_from_pdf(_FakeReader())

        self.assertEqual(
            candidates,
            [
                [
                    AUTH_FALLBACK_LABEL,
                    "efey noqg 8wo1 858f z1io yyc7 yg1g ghdi cjcn bhew xddr ebp3 f7d3 it74",
                    MAIN_FALLBACK_LABEL,
                    "efey ntgg 8wo1 858f z1io yyqg ytos q3jp cizg ghu3 qb4g 155q f3zz r33x",
                ]
            ],
        )

    def test_extract_pdf_fallback_lines_handles_split_pdf_text_pieces(self) -> None:
        extracted = _extract_pdf_fallback_lines(
            [
                "AUTH FRAME",
                "01.",
                " efey noqg 8wo1 858f z1io yyc7 yg1g ghdi cjcn bhew xddr ebp3 f7d3 it74",
                "02.",
                " o5ak se8w qtsg rnjf c861 81wj wkdk shhi cp3s 134a edte 5x5n tupb 79qa",
                "MAIN FRAME",
                "01.",
                " efey ntgg 8wo1 858f z1io yyqg ytos q3jp cizg ghu3 qb4g 155q f3zz r33x",
                "02.",
                " qaao wmj6 rb3s ghu3 qb4n y7uq gf8r si43 j73u gi5j pf1i w71e g3ds 474b",
            ]
        )

        self.assertEqual(
            extracted,
            [
                AUTH_FALLBACK_LABEL,
                "efey noqg 8wo1 858f z1io yyc7 yg1g ghdi cjcn bhew xddr ebp3 f7d3 it74",
                "o5ak se8w qtsg rnjf c861 81wj wkdk shhi cp3s 134a edte 5x5n tupb 79qa",
                MAIN_FALLBACK_LABEL,
                "efey ntgg 8wo1 858f z1io yyqg ytos q3jp cizg ghu3 qb4g 155q f3zz r33x",
                "qaao wmj6 rb3s ghu3 qb4n y7uq gf8r si43 j73u gi5j pf1i w71e g3ds 474b",
            ],
        )

    def test_extract_pdf_fallback_lines_ignores_numbered_instructions_before_sections(self) -> None:
        extracted = _extract_pdf_fallback_lines(
            [
                "INSTRUCTIONS",
                "1.",
                "Keep it separate from the QR document.",
                "2.",
                "Fallback includes AUTH + MAIN sections; keep the labels when transcribing.",
                "AUTH FRAME",
                "01.",
                " efey noqg 8wo1 858f z1io yyc7 yg1g ghdi cjcn bhew xddr ebp3 f7d3 it74",
                "MAIN FRAME",
                "01.",
                " efey ntgg 8wo1 858f z1io yyqg ytos q3jp cizg ghu3 qb4g 155q f3zz r33x",
            ]
        )

        self.assertEqual(
            extracted,
            [
                AUTH_FALLBACK_LABEL,
                "efey noqg 8wo1 858f z1io yyc7 yg1g ghdi cjcn bhew xddr ebp3 f7d3 it74",
                MAIN_FALLBACK_LABEL,
                "efey ntgg 8wo1 858f z1io yyqg ytos q3jp cizg ghu3 qb4g 155q f3zz r33x",
            ],
        )

    def test_extract_pdf_fallback_lines_ignores_known_page_chrome_inside_sections(self) -> None:
        extracted = _extract_pdf_fallback_lines(
            [
                "MAIN FRAME",
                "01.",
                " efey ntgg 8wo1 858f z1io yyqg ytos q3jp cizg ghu3 qb4g 155q f3zz r33x",
                "BACKUP SET",
                "02.",
                " qaao wmj6 rb3s ghu3 qb4n y7uq gf8r si43 j73u gi5j pf1i w71e g3ds 474b",
                "DOCUMENT",
            ]
        )

        self.assertEqual(
            extracted,
            [
                MAIN_FALLBACK_LABEL,
                "efey ntgg 8wo1 858f z1io yyqg ytos q3jp cizg ghu3 qb4g 155q f3zz r33x",
                "qaao wmj6 rb3s ghu3 qb4n y7uq gf8r si43 j73u gi5j pf1i w71e g3ds 474b",
            ],
        )

    def test_extract_pdf_fallback_lines_rejects_invalid_split_payload_fragment(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the z-base-32 alphabet"):
            _extract_pdf_fallback_lines(
                [
                    "Key Frame",
                    "1. ybndr fghj kmnp qrst",
                    "2.",
                    "%%%INVALID%%%",
                    "2. ybndr fghj kmnp qrst",
                ]
            )


if __name__ == "__main__":
    unittest.main()
