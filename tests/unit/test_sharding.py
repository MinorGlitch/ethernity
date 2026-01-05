import hashlib
import unittest

from ethernity import cli
from ethernity.framing import DOC_ID_LEN, Frame, FrameType, VERSION
from ethernity.sharding import (
    KEY_TYPE_PASSPHRASE,
    ShardPayload,
    decode_shard_payload,
    encode_shard_payload,
    recover_passphrase,
    split_passphrase,
)
from ethernity.signing import generate_signing_keypair, sign_shard


class TestSharding(unittest.TestCase):
    def test_split_and_recover_passphrase(self) -> None:
        passphrase = "correct-horse-battery-staple"
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        shares = split_passphrase(
            passphrase,
            threshold=2,
            shares=3,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        recovered = cli._passphrase_from_shard_frames(
            [
                Frame(
                    version=VERSION,
                    frame_type=FrameType.KEY_DOCUMENT,
                    doc_id=b"\x11" * DOC_ID_LEN,
                    index=0,
                    total=1,
                    data=encode_shard_payload(shares[0]),
                ),
                Frame(
                    version=VERSION,
                    frame_type=FrameType.KEY_DOCUMENT,
                    doc_id=b"\x11" * DOC_ID_LEN,
                    index=0,
                    total=1,
                    data=encode_shard_payload(shares[2]),
                ),
            ],
            expected_doc_id=b"\x11" * DOC_ID_LEN,
            expected_doc_hash=doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=False,
        )
        self.assertEqual(recovered, passphrase)

    def test_recover_passphrase_requires_threshold(self) -> None:
        passphrase = "needs-two"
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        shares = split_passphrase(
            passphrase,
            threshold=2,
            shares=3,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        with self.assertRaises(ValueError):
            recover_passphrase([shares[0]])

    def test_recover_passphrase_rejects_duplicate_indices(self) -> None:
        passphrase = "duplicate-check"
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        shares = split_passphrase(
            passphrase,
            threshold=2,
            shares=3,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        with self.assertRaises(ValueError):
            recover_passphrase([shares[0], shares[0]])

    def test_recover_passphrase_rejects_share_count_mismatch(self) -> None:
        passphrase = "share-count-check"
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        shares = split_passphrase(
            passphrase,
            threshold=2,
            shares=3,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        bad_payload = ShardPayload(
            index=shares[1].index,
            threshold=shares[1].threshold,
            shares=shares[1].shares + 1,
            key_type=shares[1].key_type,
            share=shares[1].share,
            secret_len=shares[1].secret_len,
            doc_hash=shares[1].doc_hash,
            sign_pub=shares[1].sign_pub,
            signature=shares[1].signature,
        )
        with self.assertRaises(ValueError):
            recover_passphrase([shares[0], bad_payload])

    def test_shard_payload_roundtrip(self) -> None:
        doc_hash = hashlib.blake2b(b"payload", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_shard(doc_hash, shard_index=1, share=b"\x01" * 16, sign_priv=sign_priv)
        payload = ShardPayload(
            index=1,
            threshold=2,
            shares=3,
            key_type=KEY_TYPE_PASSPHRASE,
            share=b"\x01" * 16,
            secret_len=16,
            doc_hash=doc_hash,
            sign_pub=sign_pub,
            signature=signature,
        )
        encoded = encode_shard_payload(payload)
        decoded = decode_shard_payload(encoded)
        self.assertEqual(decoded, payload)

    def test_insufficient_shards(self) -> None:
        passphrase = "needs-two"
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        shares = split_passphrase(
            passphrase,
            threshold=2,
            shares=3,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x22" * DOC_ID_LEN,
            index=0,
            total=1,
            data=encode_shard_payload(shares[0]),
        )
        with self.assertRaises(ValueError):
            cli._passphrase_from_shard_frames(
                [frame],
                expected_doc_id=b"\x22" * DOC_ID_LEN,
                expected_doc_hash=doc_hash,
                expected_sign_pub=sign_pub,
                allow_unsigned=False,
            )

    def test_shard_doc_id_mismatch(self) -> None:
        passphrase = "doc-id-check"
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        shares = split_passphrase(
            passphrase,
            threshold=2,
            shares=3,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x33" * DOC_ID_LEN,
            index=0,
            total=1,
            data=encode_shard_payload(shares[0]),
        )
        with self.assertRaises(ValueError):
            cli._passphrase_from_shard_frames(
                [frame],
                expected_doc_id=b"\x44" * DOC_ID_LEN,
                expected_doc_hash=doc_hash,
                expected_sign_pub=sign_pub,
                allow_unsigned=False,
            )


if __name__ == "__main__":
    unittest.main()
