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

import hashlib
import unittest

import cbor2

from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE, SHARD_VERSION
from ethernity.crypto.signing import (
    AUTH_VERSION,
    decode_auth_payload,
    encode_auth_payload,
    generate_signing_keypair,
    sign_auth,
    sign_shard,
    verify_auth,
    verify_shard,
)


class TestSigning(unittest.TestCase):
    def test_auth_payload_encodes_to_map(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=sign_priv)
        encoded = encode_auth_payload(doc_hash, sign_pub=sign_pub, signature=signature)
        decoded = cbor2.loads(encoded)
        self.assertIsInstance(decoded, dict)
        self.assertEqual(decoded["version"], AUTH_VERSION)
        self.assertIn("hash", decoded)
        self.assertIn("pub", decoded)
        self.assertIn("sig", decoded)

    def test_auth_payload_encoding_is_deterministic(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=sign_priv)
        first = encode_auth_payload(doc_hash, sign_pub=sign_pub, signature=signature)
        second = encode_auth_payload(doc_hash, sign_pub=sign_pub, signature=signature)
        self.assertEqual(first, second)

    def test_auth_sign_verify(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=sign_priv)
        self.assertTrue(verify_auth(doc_hash, sign_pub=sign_pub, signature=signature))
        bad_hash = hashlib.blake2b(b"other", digest_size=32).digest()
        self.assertFalse(verify_auth(bad_hash, sign_pub=sign_pub, signature=signature))

    def test_shard_sign_verify(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        share = b"share-bytes"
        signature = sign_shard(
            doc_hash,
            shard_version=SHARD_VERSION,
            key_type=KEY_TYPE_PASSPHRASE,
            threshold=2,
            share_count=3,
            share_index=1,
            secret_len=9,
            share=share,
            sign_pub=sign_pub,
            sign_priv=sign_priv,
        )
        self.assertTrue(
            verify_shard(
                doc_hash,
                shard_version=SHARD_VERSION,
                key_type=KEY_TYPE_PASSPHRASE,
                threshold=2,
                share_count=3,
                share_index=1,
                secret_len=9,
                share=share,
                sign_pub=sign_pub,
                signature=signature,
            )
        )
        self.assertFalse(
            verify_shard(
                doc_hash,
                shard_version=SHARD_VERSION,
                key_type=KEY_TYPE_PASSPHRASE,
                threshold=2,
                share_count=3,
                share_index=2,
                secret_len=9,
                share=share,
                sign_pub=sign_pub,
                signature=signature,
            )
        )

    def test_auth_payload_roundtrip(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=sign_priv)
        encoded = encode_auth_payload(doc_hash, sign_pub=sign_pub, signature=signature)
        decoded = decode_auth_payload(encoded)
        self.assertEqual(decoded.doc_hash, doc_hash)
        self.assertEqual(decoded.sign_pub, sign_pub)
        self.assertEqual(decoded.signature, signature)

    def test_decode_auth_payload_ignores_unknown_keys(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=sign_priv)
        payload = {
            "version": AUTH_VERSION,
            "hash": doc_hash,
            "pub": sign_pub,
            "sig": signature,
            "extra": b"ignored",
        }
        decoded = decode_auth_payload(cbor2.dumps(payload, canonical=True))
        self.assertEqual(decoded.doc_hash, doc_hash)
        self.assertEqual(decoded.sign_pub, sign_pub)
        self.assertEqual(decoded.signature, signature)


if __name__ == "__main__":
    unittest.main()
