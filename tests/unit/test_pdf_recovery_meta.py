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

from ethernity.render.pdf_render import (
    RecoveryMeta,
    _parse_recovery_key_lines,
    _recovery_meta_lines_extra,
)


class TestPdfRecoveryMeta(unittest.TestCase):
    def test_parse_recovery_key_lines_wraps_signing_pub_lines(self) -> None:
        key_lines = [
            "Passphrase:",
            "alpha beta gamma delta epsilon zeta eta theta iota",
            "Recover with 3 of 5 shard documents.",
            "Signing public key (hex):",
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "Signing private key stored in separate shard documents.",
        ]

        meta = _parse_recovery_key_lines(key_lines)

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

        self.assertEqual(_recovery_meta_lines_extra(meta), 3)

    def test_recovery_meta_lines_extra_adds_signing_label_row(self) -> None:
        meta = RecoveryMeta(
            passphrase=None,
            passphrase_lines=(),
            quorum_value="3 of 5",
            signing_pub_lines=("line one", "line two"),
        )

        self.assertEqual(_recovery_meta_lines_extra(meta), 4)

    def test_recovery_meta_lines_extra_counts_passphrase_when_unwrapped(self) -> None:
        meta = RecoveryMeta(
            passphrase="singleword",
            passphrase_lines=(),
            quorum_value=None,
            signing_pub_lines=(),
        )

        self.assertEqual(_recovery_meta_lines_extra(meta), 1)


if __name__ == "__main__":
    unittest.main()
