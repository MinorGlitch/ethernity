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
    def test_base64_roundtrip(self) -> None:
        data = b"\x00\xffpayload"
        encoded = encode_qr_payload(data, "base64")
        self.assertIsInstance(encoded, str)
        decoded = decode_qr_payload(encoded, "base64")
        self.assertEqual(decoded, data)
        decoded_bytes = decode_qr_payload(encoded.encode("ascii"), "base64")
        self.assertEqual(decoded_bytes, data)

    def test_base64url_roundtrip(self) -> None:
        data = b"\x00\xffpayload"
        encoded = encode_qr_payload(data, "base64url")
        self.assertIsInstance(encoded, str)
        decoded = decode_qr_payload(encoded, "base64url")
        self.assertEqual(decoded, data)
        decoded_bytes = decode_qr_payload(encoded.encode("ascii"), "base64url")
        self.assertEqual(decoded_bytes, data)

    def test_normalize(self) -> None:
        self.assertEqual(normalize_qr_payload_encoding("b64"), "base64")
        self.assertEqual(normalize_qr_payload_encoding("b64url"), "base64url")
        with self.assertRaises(ValueError):
            normalize_qr_payload_encoding("base45")
        with self.assertRaises(ValueError):
            normalize_qr_payload_encoding("binary")


if __name__ == "__main__":
    unittest.main()
