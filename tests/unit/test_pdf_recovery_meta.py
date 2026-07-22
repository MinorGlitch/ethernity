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

from ethernity.render.recovery_meta import (
    PASSPHRASE_PRINT_MODE_JSON,
    PASSPHRASE_PRINT_MODE_LITERAL,
    RecoveryMeta,
    build_recovery_meta,
    decode_printed_passphrase,
    recovery_meta_lines_extra,
)


class TestPdfRecoveryMeta(unittest.TestCase):
    def test_build_recovery_meta_wraps_signing_pub_lines(self) -> None:
        meta = build_recovery_meta(
            passphrase="alpha beta gamma delta epsilon zeta eta theta iota",
            quorum_threshold=3,
            quorum_shares=5,
            signing_pub=bytes.fromhex(
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
            ),
        )

        self.assertEqual(meta.quorum_value, "3 of 5")
        self.assertEqual(len(meta.signing_pub_lines), 2)
        self.assertTrue(all(len(line) <= 40 for line in meta.signing_pub_lines))
        self.assertEqual(len(" ".join(meta.signing_pub_lines).split()), 16)

    def test_recovery_meta_lines_extra_uses_minimum_signing_rows(self) -> None:
        meta = RecoveryMeta(
            passphrase=None,
            passphrase_lines=(),
            quorum_value="3 of 5",
            signing_pub_lines=("abcd ef01",),
        )

        self.assertEqual(recovery_meta_lines_extra(meta), 3)

    def test_recovery_meta_lines_extra_adds_signing_label_row(self) -> None:
        meta = RecoveryMeta(
            passphrase=None,
            passphrase_lines=(),
            quorum_value="3 of 5",
            signing_pub_lines=("line one", "line two"),
        )

        self.assertEqual(recovery_meta_lines_extra(meta), 4)

    def test_recovery_meta_lines_extra_counts_passphrase_when_unwrapped(self) -> None:
        meta = RecoveryMeta(
            passphrase="singleword",
            passphrase_lines=(),
            quorum_value=None,
            signing_pub_lines=(),
        )

        self.assertEqual(recovery_meta_lines_extra(meta), 1)

    def test_build_recovery_meta_requires_complete_quorum_pair(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "quorum_threshold and quorum_shares must be provided together",
        ):
            build_recovery_meta(
                passphrase=None,
                quorum_threshold=2,
                quorum_shares=None,
                signing_pub=None,
            )

    def test_canonical_words_keep_literal_grouping(self) -> None:
        passphrase = " ".join(f"word{index:02d}" for index in range(24))

        meta = build_recovery_meta(
            passphrase=passphrase,
            quorum_threshold=None,
            quorum_shares=None,
            signing_pub=None,
        )

        self.assertEqual(meta.passphrase_print_mode, PASSPHRASE_PRINT_MODE_LITERAL)
        self.assertEqual(len(meta.passphrase_lines), 4)
        self.assertEqual(
            decode_printed_passphrase(
                meta.passphrase_lines,
                print_mode=meta.passphrase_print_mode,
            ),
            passphrase,
        )

    def test_significant_whitespace_and_unicode_use_lossless_ascii_json(self) -> None:
        for passphrase in (
            "alpha  beta",
            "alpha\tbeta\ngamma",
            " p\u00e4ssphrase ",
            "emoji \U0001f510 passphrase",
        ):
            with self.subTest(passphrase=passphrase):
                meta = build_recovery_meta(
                    passphrase=passphrase,
                    quorum_threshold=None,
                    quorum_shares=None,
                    signing_pub=None,
                )

                self.assertEqual(meta.passphrase_print_mode, PASSPHRASE_PRINT_MODE_JSON)
                self.assertTrue(all(line.isascii() for line in meta.passphrase_lines))
                self.assertEqual(
                    decode_printed_passphrase(
                        meta.passphrase_lines,
                        print_mode=meta.passphrase_print_mode,
                    ),
                    passphrase,
                )

    def test_json_part_decoder_rejects_out_of_order_or_incomplete_numbering(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete or out of order"):
            decode_printed_passphrase(
                ('02/02 "beta"', '01/02 "alpha"'),
                print_mode="json-parts",
            )
        for lines in (
            (),
            ('01/03 "alpha"', '02/03 "beta"'),
            ('01/02 "alpha"', '01/02 "beta"'),
        ):
            with self.subTest(lines=lines):
                with self.assertRaises(ValueError):
                    decode_printed_passphrase(lines, print_mode="json-parts")


if __name__ == "__main__":
    unittest.main()
