import unittest

from ethernity.validation import require_bytes, require_length


class TestValidation(unittest.TestCase):
    def test_require_length_accepts_exact(self) -> None:
        require_length(b"\x00\x01", 2, label="payload")

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
