import unittest
from unittest import mock

from ethernity.crypto import AgeCliError, decrypt_bytes, encrypt_bytes_with_passphrase
from ethernity.crypto import age_runtime


class TestAgeCli(unittest.TestCase):
    def test_autogen_passphrase(self) -> None:
        data = b"payload"
        with mock.patch(
            "ethernity.crypto.age_runtime.generate_passphrase", return_value="test-passphrase"
        ):
            ciphertext, passphrase = encrypt_bytes_with_passphrase(data, passphrase=None)
        self.assertEqual(passphrase, "test-passphrase")
        plaintext = decrypt_bytes(ciphertext, passphrase="test-passphrase")
        self.assertEqual(plaintext, data)

    def test_encrypt_decrypt_roundtrip(self) -> None:
        data = b"payload"
        ciphertext, passphrase = encrypt_bytes_with_passphrase(data, passphrase="secret")
        self.assertEqual(passphrase, "secret")
        plaintext = decrypt_bytes(ciphertext, passphrase="secret")
        self.assertEqual(plaintext, data)

    def test_decrypt_wrong_passphrase_raises(self) -> None:
        data = b"payload"
        ciphertext, _ = encrypt_bytes_with_passphrase(data, passphrase="secret")
        with self.assertRaises(AgeCliError):
            decrypt_bytes(ciphertext, passphrase="other")

    def test_encrypt_wraps_pyrage_error(self) -> None:
        data = b"payload"
        with mock.patch.object(
            age_runtime.pyrage_passphrase, "encrypt", side_effect=ValueError("boom")
        ):
            with self.assertRaises(AgeCliError) as ctx:
                encrypt_bytes_with_passphrase(data, passphrase="secret")
        self.assertIn("boom", str(ctx.exception))

    def test_decrypt_wraps_pyrage_error(self) -> None:
        with mock.patch.object(
            age_runtime.pyrage_passphrase, "decrypt", side_effect=ValueError("boom")
        ):
            with self.assertRaises(AgeCliError) as ctx:
                decrypt_bytes(b"ciphertext", passphrase="secret")
        self.assertIn("boom", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
