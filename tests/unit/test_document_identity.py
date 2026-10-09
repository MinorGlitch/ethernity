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

from ethernity.crypto.document_identity import (
    DOC_HASH_LEN,
    doc_hash_from_ciphertext,
    doc_id_and_hash_from_ciphertext,
    doc_id_from_doc_hash,
    normalize_doc_hash_hex,
    parse_doc_hash_hex,
)
from ethernity.encoding.framing import DOC_ID_LEN


class TestDocumentIdentity(unittest.TestCase):
    def test_derives_normative_hash_and_document_id(self) -> None:
        expected_hash = bytes.fromhex(
            "14e1acccbe57ed5ba853ba820d0a9d59b279a0405d34a367aa7af45caa8be3c3"
        )

        doc_id, doc_hash = doc_id_and_hash_from_ciphertext(b"ciphertext")

        self.assertEqual(doc_hash, expected_hash)
        self.assertEqual(doc_hash_from_ciphertext(b"ciphertext"), expected_hash)
        self.assertEqual(doc_id, expected_hash[:DOC_ID_LEN])
        self.assertEqual(doc_id_from_doc_hash(expected_hash), expected_hash[:DOC_ID_LEN])

    def test_rejects_document_hashes_with_the_wrong_length(self) -> None:
        for length in (DOC_HASH_LEN - 1, DOC_HASH_LEN + 1):
            with self.subTest(length=length):
                with self.assertRaisesRegex(ValueError, "doc_hash must be 32 bytes"):
                    doc_id_from_doc_hash(b"x" * length)

    def test_normalizes_hexadecimal_document_hashes(self) -> None:
        value = "AB" * DOC_HASH_LEN

        self.assertEqual(normalize_doc_hash_hex(f" {value} "), value.lower())

    def test_rejects_invalid_hexadecimal_document_hashes(self) -> None:
        for value in ("ab", "gg" * DOC_HASH_LEN):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "must be a 32-byte lowercase hex value"):
                    normalize_doc_hash_hex(value, option="extension doc hash")

    def test_parses_hexadecimal_document_hashes_with_option_specific_errors(self) -> None:
        value = "AB" * DOC_HASH_LEN
        self.assertEqual(
            parse_doc_hash_hex(f" {value} ", option="--extension-doc-hash"),
            bytes.fromhex(value),
        )

        with self.assertRaisesRegex(ValueError, "must be lowercase hex"):
            parse_doc_hash_hex("gg" * DOC_HASH_LEN, option="--extension-doc-hash")
        with self.assertRaisesRegex(ValueError, "must be a 32-byte hex value"):
            parse_doc_hash_hex("ab", option="--extension-doc-hash")


if __name__ == "__main__":
    unittest.main()
