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

from ethernity.extensions import (
    ExtensionMainArtifactName,
    ExtensionShardArtifactName,
    build_extension_main_filename,
    build_extension_shard_filename,
    build_staging_dir_name,
    canonical_extension_dir_name,
    is_canonical_extension_dir_name,
    is_staging_dir_name,
    parse_extension_dir_name,
    parse_extension_main_filename,
    parse_extension_shard_filename,
)


class TestExtensionLayout(unittest.TestCase):
    def test_canonical_extension_dir_name_uses_minimum_width_two(self) -> None:
        self.assertEqual(canonical_extension_dir_name(1), "01")
        self.assertEqual(canonical_extension_dir_name(12), "12")
        self.assertEqual(canonical_extension_dir_name(100), "100")
        self.assertEqual(canonical_extension_dir_name(127), "127")
        with self.assertRaisesRegex(ValueError, "MAX_EXTENSION_INDEX"):
            canonical_extension_dir_name(128)

    def test_parse_extension_dir_name_rejects_non_canonical_values(self) -> None:
        for value in ("001", "00", "0", "abc", ".staging-1-x"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "invalid extension directory name"):
                    parse_extension_dir_name(value)

    def test_is_canonical_extension_dir_name_matches_expected_values(self) -> None:
        self.assertTrue(is_canonical_extension_dir_name("01"))
        self.assertTrue(is_canonical_extension_dir_name("10"))
        self.assertTrue(is_canonical_extension_dir_name("100"))
        self.assertTrue(is_canonical_extension_dir_name("127"))
        self.assertFalse(is_canonical_extension_dir_name("128"))
        self.assertFalse(is_canonical_extension_dir_name("001"))

    def test_build_staging_dir_name(self) -> None:
        self.assertEqual(build_staging_dir_name(2, "abc123"), ".staging-2-abc123")
        self.assertTrue(is_staging_dir_name(".staging-2-abc123"))

    def test_build_staging_dir_name_rejects_invalid_nonce(self) -> None:
        with self.assertRaisesRegex(ValueError, "path separators"):
            build_staging_dir_name(2, "bad/value")

    def test_build_and_parse_extension_main_filename(self) -> None:
        filename = build_extension_main_filename(
            "qr_document",
            2,
            "deadbeefcafebabe",
        )
        self.assertEqual(filename, "qr_document-02-deadbeefcafebabe.pdf")
        self.assertEqual(
            parse_extension_main_filename(filename),
            ExtensionMainArtifactName(
                doc_type="qr_document",
                index=2,
                doc_id_hex="deadbeefcafebabe",
            ),
        )

    def test_parse_extension_main_filename_rejects_uppercase_doc_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid extension main artifact filename"):
            parse_extension_main_filename("qr_document-02-DEADBEEFCAFEBABE.pdf")

    def test_build_and_parse_extension_shard_filename(self) -> None:
        filename = build_extension_shard_filename(
            "signing-key-shard",
            7,
            "deadbeefcafebabe",
            share_index=2,
            share_count=3,
        )
        self.assertEqual(filename, "signing-key-shard-07-deadbeefcafebabe-2-of-3.pdf")
        self.assertEqual(
            parse_extension_shard_filename(filename),
            ExtensionShardArtifactName(
                doc_type="signing-key-shard",
                index=7,
                doc_id_hex="deadbeefcafebabe",
                share_index=2,
                share_count=3,
            ),
        )

    def test_build_extension_shard_filename_rejects_invalid_quorum(self) -> None:
        with self.assertRaisesRegex(ValueError, "less than or equal to share_count"):
            build_extension_shard_filename(
                "shard",
                2,
                "deadbeefcafebabe",
                share_index=4,
                share_count=3,
            )

    def test_extension_shard_filename_rejects_share_values_above_255(self) -> None:
        with self.assertRaisesRegex(ValueError, "MAX_SHARES"):
            build_extension_shard_filename(
                "shard",
                2,
                "deadbeefcafebabe",
                share_index=1,
                share_count=256,
            )
        with self.assertRaisesRegex(ValueError, "MAX_SHARES"):
            parse_extension_shard_filename(
                "shard-02-deadbeefcafebabe-1-of-999999999999999999999999.pdf"
            )
