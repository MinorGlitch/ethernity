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

from ethernity.crypto import passphrases
from ethernity.crypto.passphrases import (
    looks_like_bip39_mnemonic,
    normalize_bip39_mnemonic,
    validate_mnemonic_checksum_if_bip39,
)


class TestPassphrases(unittest.TestCase):
    def test_load_wordlist_uses_single_segment_resource_joins(self) -> None:
        testcase = self

        class _FakeTraversable:
            def __init__(self, children: dict[str, "_FakeTraversable"] | None = None) -> None:
                self._children = children or {}

            def joinpath(self, child: str) -> "_FakeTraversable":
                return self._children[child]

            def read_text(self, *, encoding: str) -> str:
                testcase.assertEqual(encoding, "utf-8")
                return "abandon\nabout\n"

        wordlist_file = _FakeTraversable()
        crypto_dir = _FakeTraversable({"bip39_wordlist.txt": wordlist_file})
        resources_root = _FakeTraversable({"crypto": crypto_dir})

        with mock.patch.object(
            passphrases.importlib.resources,
            "files",
            return_value=resources_root,
        ):
            self.assertEqual(passphrases._load_wordlist(), ["abandon", "about"])

    def test_validate_mnemonic_checksum_accepts_valid_mnemonic(self) -> None:
        phrase = " ".join(["abandon"] * 11 + ["about"])
        self.assertTrue(looks_like_bip39_mnemonic(phrase))
        validate_mnemonic_checksum_if_bip39(phrase)

    def test_validate_mnemonic_checksum_rejects_invalid_checksum(self) -> None:
        phrase = " ".join(["abandon"] * 11 + ["above"])
        self.assertTrue(looks_like_bip39_mnemonic(phrase))
        with self.assertRaises(ValueError):
            validate_mnemonic_checksum_if_bip39(phrase)

    def test_validate_mnemonic_checksum_skips_non_mnemonic(self) -> None:
        phrase = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
        self.assertFalse(looks_like_bip39_mnemonic(phrase))
        validate_mnemonic_checksum_if_bip39(phrase)

    def test_normalize_bip39_mnemonic_collapses_whitespace(self) -> None:
        phrase = (
            "  abandon   abandon abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon about  "
        )
        self.assertEqual(
            normalize_bip39_mnemonic(phrase),
            (
                "abandon abandon abandon abandon abandon abandon abandon abandon "
                "abandon abandon abandon about"
            ),
        )


if __name__ == "__main__":
    unittest.main()
