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

from ethernity.encoding.varint import decode_uvarint, encode_uvarint


class TestVarint(unittest.TestCase):
    def test_roundtrip_values(self) -> None:
        for value in (0, 1, 127, 128, 255, 300, (1 << 64) - 1):
            with self.subTest(value=value):
                encoded = encode_uvarint(value)
                decoded, idx = decode_uvarint(encoded, 0)
                self.assertEqual(decoded, value)
                self.assertEqual(idx, len(encoded))

    def test_encode_rejects_out_of_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            encode_uvarint(-1)
        with self.assertRaisesRegex(ValueError, r"2\^64-1"):
            encode_uvarint(1 << 64)

    def test_decode_rejects_non_canonical(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            decode_uvarint(b"\x80\x00", 0)

    def test_decode_rejects_overflow(self) -> None:
        # 10th byte payload > 1 exceeds unsigned 64-bit range.
        with self.assertRaisesRegex(ValueError, "too large"):
            decode_uvarint((b"\x80" * 9) + b"\x02", 0)

    def test_decode_rejects_truncated(self) -> None:
        with self.assertRaisesRegex(ValueError, "truncated"):
            decode_uvarint(b"\x80", 0)

    def test_decode_rejects_negative_start(self) -> None:
        with self.assertRaisesRegex(ValueError, "start must be non-negative"):
            decode_uvarint(b"\x01", -1)


if __name__ == "__main__":
    unittest.main()
