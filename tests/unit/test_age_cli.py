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
from unittest import mock

from ethernity.crypto import AgeError, age_runtime, decrypt_bytes, encrypt_bytes_with_passphrase


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

    def test_valid_bip39_input_is_canonicalized_once_for_encryption_and_recovery(self) -> None:
        data = b"payload"
        spaced = "  " + "  ".join(["abandon"] * 11 + ["about"]) + "  "
        canonical = " ".join(["abandon"] * 11 + ["about"])

        ciphertext, passphrase = encrypt_bytes_with_passphrase(data, passphrase=spaced)

        self.assertEqual(passphrase, canonical)
        self.assertEqual(decrypt_bytes(ciphertext, passphrase=spaced), data)

    def test_invalid_checksum_wordlist_phrase_remains_an_exact_custom_secret(self) -> None:
        data = b"payload"
        exact = "  " + "  ".join(["abandon"] * 11 + ["above"]) + "  "

        ciphertext, passphrase = encrypt_bytes_with_passphrase(data, passphrase=exact)

        self.assertEqual(passphrase, exact)
        self.assertEqual(decrypt_bytes(ciphertext, passphrase=exact), data)

    def test_recovery_tries_exact_legacy_secret_before_canonical_fallback(self) -> None:
        data = b"legacy"
        exact = "  " + "  ".join(["abandon"] * 11 + ["about"]) + "  "
        ciphertext = age_runtime._encrypt_with_pyrage(data, exact)

        with mock.patch.object(
            age_runtime,
            "_decrypt_with_pyrage",
            wraps=age_runtime._decrypt_with_pyrage,
        ) as decrypt_exact:
            plaintext = decrypt_bytes(ciphertext, passphrase=exact)

        self.assertEqual(plaintext, data)
        self.assertEqual(decrypt_exact.call_count, 1)
        self.assertEqual(decrypt_exact.call_args.args[1], exact)

    def test_recovery_does_not_try_canonical_candidate_for_malformed_ciphertext(self) -> None:
        exact = "  " + "  ".join(["abandon"] * 11 + ["about"]) + "  "

        with mock.patch.object(
            age_runtime,
            "_decrypt_with_pyrage",
            side_effect=AgeError(backend="pyrage", detail="failed to fill whole buffer"),
        ) as decrypt_candidate:
            with self.assertRaisesRegex(ValueError, "decryption failed"):
                decrypt_bytes(b"malformed", passphrase=exact)

        decrypt_candidate.assert_called_once_with(b"malformed", exact)

    def test_decrypt_wrong_passphrase_raises(self) -> None:
        data = b"payload"
        ciphertext, _ = encrypt_bytes_with_passphrase(data, passphrase="secret")
        with self.assertRaises(ValueError):
            decrypt_bytes(ciphertext, passphrase="other")

    def test_decrypt_wrong_passphrase_debug_includes_details(self) -> None:
        data = b"payload"
        ciphertext, _ = encrypt_bytes_with_passphrase(data, passphrase="secret")
        with self.assertRaises(AgeError):
            decrypt_bytes(ciphertext, passphrase="other", debug=True)

    def test_encrypt_wraps_pyrage_error(self) -> None:
        data = b"payload"
        with mock.patch.object(
            age_runtime.pyrage_passphrase, "encrypt", side_effect=ValueError("boom")
        ):
            with self.assertRaises(AgeError) as ctx:
                encrypt_bytes_with_passphrase(data, passphrase="secret")
        self.assertIn("boom", str(ctx.exception))

    def test_decrypt_wraps_pyrage_error(self) -> None:
        with mock.patch.object(
            age_runtime.pyrage_passphrase, "decrypt", side_effect=ValueError("boom")
        ):
            with self.assertRaises(AgeError) as ctx:
                decrypt_bytes(b"ciphertext", passphrase="secret", debug=True)
        self.assertIn("boom", str(ctx.exception))

    def test_decrypt_non_debug_is_generic(self) -> None:
        with mock.patch.object(
            age_runtime.pyrage_passphrase, "decrypt", side_effect=ValueError("boom")
        ):
            with self.assertRaises(ValueError) as ctx:
                decrypt_bytes(b"ciphertext", passphrase="secret")
        self.assertIn("decryption failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
