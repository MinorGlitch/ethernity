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

from ethernity.core.bounds import MAX_PATH_BYTES
from ethernity.core.validation import (
    normalize_manifest_path,
    normalize_path,
    require_bytes,
    require_dict,
    require_int_range,
    require_keys,
    require_length,
    require_list,
    require_non_empty_bytes,
    require_non_negative_int,
    require_positive_int,
    require_version,
)


class TestValidation(unittest.TestCase):
    def test_require_list_accepts_list_and_tuple(self) -> None:
        self.assertEqual(require_list([1, 2], 1, label="items"), [1, 2])
        self.assertEqual(require_list((1, 2), 1, label="items"), (1, 2))

    def test_require_list_rejects_non_list_or_too_short(self) -> None:
        with self.assertRaisesRegex(ValueError, "items must be a list"):
            require_list("bad", 1, label="items")
        with self.assertRaisesRegex(ValueError, "items must be a list"):
            require_list([], 1, label="items")

    def test_require_dict_accepts_and_rejects(self) -> None:
        self.assertEqual(require_dict({"a": 1}, label="mapping"), {"a": 1})
        with self.assertRaisesRegex(ValueError, "mapping must be a dict"):
            require_dict([], label="mapping")

    def test_require_keys_validates_missing_keys(self) -> None:
        require_keys({"a": 1, "b": 2}, ("a", "b"), label="payload")
        with self.assertRaisesRegex(ValueError, "payload c is required"):
            require_keys({"a": 1}, ("a", "c"), label="payload")

    def test_require_length_accepts_exact(self) -> None:
        self.assertIsNone(require_length(b"\x00\x01", 2, label="payload"))

    def test_require_length_rejects_mismatch(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            require_length(b"\x00", 2, label="payload")
        self.assertIn("payload must be 2 bytes", str(ctx.exception))

    def test_require_bytes_accepts_bytes_and_bytearray(self) -> None:
        self.assertEqual(require_bytes(b"\x01\x02", 2, label="token"), b"\x01\x02")
        self.assertEqual(require_bytes(bytearray(b"\x03\x04"), 2, label="token"), b"\x03\x04")

    def test_require_bytes_rejects_non_bytes(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            require_bytes("text", 2, label="token")
        self.assertIn("token must be bytes", str(ctx.exception))

    def test_require_bytes_rejects_length_mismatch(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            require_bytes(b"\x01", 2, label="token")
        self.assertIn("token must be 2 bytes", str(ctx.exception))

    def test_prefix_in_error_message(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            require_length(b"\x00", 2, label="doc_hash", prefix="shard ")
        self.assertIn("shard doc_hash must be 2 bytes", str(ctx.exception))

    def test_normalize_path_rejects_non_string(self) -> None:
        with self.assertRaisesRegex(ValueError, "path must be a string"):
            normalize_path(123)

    def test_normalize_path_rejects_invalid_utf8(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid UTF-8"):
            normalize_path("\ud800")

    def test_normalize_manifest_path_rejects_absolute(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            normalize_manifest_path("/abs/file.txt", label="manifest file path")
        self.assertIn("relative", str(ctx.exception))

    def test_normalize_manifest_path_rejects_backslashes(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            normalize_manifest_path(r"dir\file.txt", label="manifest file path")
        self.assertIn("POSIX separators", str(ctx.exception))

    def test_normalize_manifest_path_accepts_relative_posix(self) -> None:
        self.assertEqual(
            normalize_manifest_path("dir/sub/file.txt", label="manifest file path"),
            "dir/sub/file.txt",
        )

    def test_normalize_manifest_path_rejects_dot_segments(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            normalize_manifest_path("dir/./file.txt", label="manifest file path")
        self.assertIn("'.' or '..'", str(ctx.exception))

    def test_normalize_manifest_path_rejects_dotdot_segments(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            normalize_manifest_path("dir/../file.txt", label="manifest file path")
        self.assertIn("'.' or '..'", str(ctx.exception))

    def test_normalize_manifest_path_rejects_empty_segments(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            normalize_manifest_path("dir//file.txt", label="manifest file path")
        self.assertIn("empty path segments", str(ctx.exception))

    def test_normalize_manifest_path_accepts_exact_utf8_byte_limit(self) -> None:
        exact = "a" * MAX_PATH_BYTES
        self.assertEqual(
            normalize_manifest_path(exact, label="manifest file path"),
            exact,
        )

    def test_normalize_manifest_path_rejects_utf8_byte_limit_overflow(self) -> None:
        too_long = "a" * (MAX_PATH_BYTES + 1)
        with self.assertRaises(ValueError) as ctx:
            normalize_manifest_path(too_long, label="manifest file path")
        self.assertIn("MAX_PATH_BYTES", str(ctx.exception))

    def test_require_positive_int_validation(self) -> None:
        self.assertEqual(require_positive_int(2, label="count"), 2)
        with self.assertRaisesRegex(ValueError, "count must be a positive int"):
            require_positive_int(0, label="count")

    def test_require_non_negative_int_validation(self) -> None:
        self.assertEqual(require_non_negative_int(0, label="offset"), 0)
        with self.assertRaisesRegex(ValueError, "offset must be a non-negative int"):
            require_non_negative_int(-1, label="offset")

    def test_require_int_range_validation(self) -> None:
        self.assertEqual(require_int_range(5, min_val=1, max_val=5, label="index"), 5)
        with self.assertRaisesRegex(ValueError, "index must be between 1 and 5"):
            require_int_range(6, min_val=1, max_val=5, label="index")

    def test_require_non_empty_bytes_validation(self) -> None:
        self.assertEqual(require_non_empty_bytes(b"x", label="blob"), b"x")
        with self.assertRaisesRegex(ValueError, "blob must be non-empty bytes"):
            require_non_empty_bytes(b"", label="blob")

    def test_require_version_validation(self) -> None:
        require_version(1, 1, label="format")
        with self.assertRaisesRegex(ValueError, "unsupported format version: 2"):
            require_version(2, 1, label="format")


if __name__ == "__main__":
    unittest.main()
