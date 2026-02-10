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

from ethernity.encoding.qr_payloads import (
    decode_qr_payload,
    encode_qr_payload,
    normalize_qr_payload_encoding,
)


class TestQrPayloads(unittest.TestCase):
    def test_roundtrip_encodings(self) -> None:
        data = b"\x00\xffpayload"
        for encoding in ("base64", "base64url"):
            with self.subTest(encoding=encoding):
                encoded = encode_qr_payload(data, encoding)
                self.assertIsInstance(encoded, str)
                decoded = decode_qr_payload(encoded, encoding)
                self.assertEqual(decoded, data)
                decoded_bytes = decode_qr_payload(encoded.encode("ascii"), encoding)
                self.assertEqual(decoded_bytes, data)

    def test_normalize(self) -> None:
        self.assertEqual(normalize_qr_payload_encoding("b64"), "base64")
        self.assertEqual(normalize_qr_payload_encoding("b64url"), "base64url")
        for invalid in ("base45", "binary"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_qr_payload_encoding(invalid)


if __name__ == "__main__":
    unittest.main()
