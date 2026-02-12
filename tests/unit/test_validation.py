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

from ethernity.core.validation import require_bytes, require_length


class TestValidation(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
