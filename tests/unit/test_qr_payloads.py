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

    def test_normalize(self) -> None:
        self.assertEqual(normalize_qr_payload_encoding("b64"), "base64")
        with self.assertRaises(ValueError):
            normalize_qr_payload_encoding("base45")
        with self.assertRaises(ValueError):
            normalize_qr_payload_encoding("binary")


if __name__ == "__main__":
    unittest.main()
