import hashlib
import unittest

from ethernity.signing import (
    decode_auth_payload,
    encode_auth_payload,
    generate_signing_keypair,
    sign_auth,
    sign_shard,
    verify_auth,
    verify_shard,
)


class TestSigning(unittest.TestCase):
    def test_auth_sign_verify(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_auth(doc_hash, sign_priv=sign_priv)
        self.assertTrue(verify_auth(doc_hash, sign_pub=sign_pub, signature=signature))
        bad_hash = hashlib.blake2b(b"other", digest_size=32).digest()
        self.assertFalse(verify_auth(bad_hash, sign_pub=sign_pub, signature=signature))

    def test_shard_sign_verify(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        share = b"share-bytes"
        signature = sign_shard(doc_hash, shard_index=1, share=share, sign_priv=sign_priv)
        self.assertTrue(
            verify_shard(doc_hash, shard_index=1, share=share, sign_pub=sign_pub, signature=signature)
        )
        self.assertFalse(
            verify_shard(doc_hash, shard_index=2, share=share, sign_pub=sign_pub, signature=signature)
        )

    def test_auth_payload_roundtrip(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_auth(doc_hash, sign_priv=sign_priv)
        encoded = encode_auth_payload(doc_hash, sign_pub=sign_pub, signature=signature)
        decoded = decode_auth_payload(encoded)
        self.assertEqual(decoded.doc_hash, doc_hash)
        self.assertEqual(decoded.sign_pub, sign_pub)
        self.assertEqual(decoded.signature, signature)


if __name__ == "__main__":
    unittest.main()
