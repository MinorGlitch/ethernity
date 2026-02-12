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

from ethernity.cli.keys.recover_keys import _passphrase_from_shard_frames
from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    MAX_SHARES,
    SHARD_VERSION,
    ShardPayload,
    decode_shard_payload,
    encode_shard_payload,
    recover_passphrase,
    recover_signing_seed,
    split_passphrase,
    split_signing_seed,
)
from ethernity.crypto.signing import generate_signing_keypair, sign_shard
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType


class TestSharding(unittest.TestCase):
    def test_shard_payload_encodes_to_map(self) -> None:
        doc_hash = hashlib.blake2b(b"payload", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_shard(
            doc_hash,
            shard_version=SHARD_VERSION,
            key_type=KEY_TYPE_PASSPHRASE,
            threshold=2,
            share_count=3,
            share_index=1,
            secret_len=16,
            share=b"\x01" * 16,
            sign_pub=sign_pub,
            sign_priv=sign_priv,
        )
        payload = ShardPayload(
            share_index=1,
            threshold=2,
            share_count=3,
            key_type=KEY_TYPE_PASSPHRASE,
            share=b"\x01" * 16,
            secret_len=16,
            doc_hash=doc_hash,
            sign_pub=sign_pub,
            signature=signature,
        )
        encoded = encode_shard_payload(payload)
        decoded = cbor2.loads(encoded)
        self.assertIsInstance(decoded, dict)
        self.assertEqual(decoded["version"], SHARD_VERSION)
        self.assertIn("type", decoded)
        self.assertIn("share_count", decoded)
        self.assertIn("hash", decoded)
        self.assertIn("pub", decoded)
        self.assertIn("sig", decoded)

    def test_shard_payload_encoding_is_deterministic(self) -> None:
        doc_hash = hashlib.blake2b(b"payload", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_shard(
            doc_hash,
            shard_version=SHARD_VERSION,
            key_type=KEY_TYPE_PASSPHRASE,
            threshold=2,
            share_count=3,
            share_index=1,
            secret_len=16,
            share=b"\x01" * 16,
            sign_pub=sign_pub,
            sign_priv=sign_priv,
        )
        payload = ShardPayload(
            share_index=1,
            threshold=2,
            share_count=3,
            key_type=KEY_TYPE_PASSPHRASE,
            share=b"\x01" * 16,
            secret_len=16,
            doc_hash=doc_hash,
            sign_pub=sign_pub,
            signature=signature,
        )
        first = encode_shard_payload(payload)
        second = encode_shard_payload(payload)
        self.assertEqual(first, second)

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
        recovered = _passphrase_from_shard_frames(
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

    def test_split_and_recover_signing_seed(self) -> None:
        seed = b"\x5a" * 32
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        shares = split_signing_seed(
            seed,
            threshold=2,
            shares=3,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        recovered = recover_signing_seed([shares[0], shares[2]])
        self.assertEqual(recovered, seed)

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
            share_index=shares[1].share_index,
            threshold=shares[1].threshold,
            share_count=shares[1].share_count + 1,
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
        signature = sign_shard(
            doc_hash,
            shard_version=SHARD_VERSION,
            key_type=KEY_TYPE_PASSPHRASE,
            threshold=2,
            share_count=3,
            share_index=1,
            secret_len=16,
            share=b"\x01" * 16,
            sign_pub=sign_pub,
            sign_priv=sign_priv,
        )
        payload = ShardPayload(
            share_index=1,
            threshold=2,
            share_count=3,
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

    def test_decode_shard_payload_ignores_unknown_keys(self) -> None:
        doc_hash = hashlib.blake2b(b"payload", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        share = b"\x01" * 16
        signature = sign_shard(
            doc_hash,
            shard_version=SHARD_VERSION,
            key_type=KEY_TYPE_PASSPHRASE,
            threshold=2,
            share_count=3,
            share_index=1,
            secret_len=16,
            share=share,
            sign_pub=sign_pub,
            sign_priv=sign_priv,
        )
        expected = ShardPayload(
            share_index=1,
            threshold=2,
            share_count=3,
            key_type=KEY_TYPE_PASSPHRASE,
            share=share,
            secret_len=16,
            doc_hash=doc_hash,
            sign_pub=sign_pub,
            signature=signature,
        )
        payload = {
            "version": SHARD_VERSION,
            "type": expected.key_type,
            "threshold": expected.threshold,
            "share_count": expected.share_count,
            "share_index": expected.share_index,
            "length": expected.secret_len,
            "share": expected.share,
            "hash": expected.doc_hash,
            "pub": expected.sign_pub,
            "sig": expected.signature,
            "extra": 123,
        }
        decoded = decode_shard_payload(cbor2.dumps(payload, canonical=True))
        self.assertEqual(decoded, expected)

    def test_decode_rejects_threshold_or_index_exceeds_total(self) -> None:
        cases = (
            {
                "name": "threshold-exceeds-total",
                "payload": ShardPayload(
                    share_index=1,
                    threshold=3,
                    share_count=2,
                    key_type=KEY_TYPE_PASSPHRASE,
                    share=b"\x01" * 16,
                    secret_len=16,
                    doc_hash=b"\x00" * 32,
                    sign_pub=b"\x00" * 32,
                    signature=b"\x00" * 64,
                ),
            },
            {
                "name": "index-exceeds-total",
                "payload": ShardPayload(
                    share_index=3,
                    threshold=1,
                    share_count=2,
                    key_type=KEY_TYPE_PASSPHRASE,
                    share=b"\x01" * 16,
                    secret_len=16,
                    doc_hash=b"\x00" * 32,
                    sign_pub=b"\x00" * 32,
                    signature=b"\x00" * 64,
                ),
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                with self.assertRaises(ValueError):
                    decode_shard_payload(encode_shard_payload(case["payload"]))

    def test_signing_seed_payload_roundtrip(self) -> None:
        doc_hash = hashlib.blake2b(b"payload", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        signature = sign_shard(
            doc_hash,
            shard_version=SHARD_VERSION,
            key_type=KEY_TYPE_SIGNING_SEED,
            threshold=2,
            share_count=3,
            share_index=1,
            secret_len=16,
            share=b"\x02" * 16,
            sign_pub=sign_pub,
            sign_priv=sign_priv,
        )
        payload = ShardPayload(
            share_index=1,
            threshold=2,
            share_count=3,
            key_type=KEY_TYPE_SIGNING_SEED,
            share=b"\x02" * 16,
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
            _passphrase_from_shard_frames(
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
            _passphrase_from_shard_frames(
                [frame],
                expected_doc_id=b"\x44" * DOC_ID_LEN,
                expected_doc_hash=doc_hash,
                expected_sign_pub=sign_pub,
                allow_unsigned=False,
            )

    def test_decode_rejects_total_over_255(self) -> None:
        payload = {
            "version": SHARD_VERSION,
            "type": KEY_TYPE_PASSPHRASE,
            "threshold": 2,
            "share_count": MAX_SHARES + 1,
            "share_index": 1,
            "length": 1,
            "share": b"\x01",
            "hash": b"\x00" * 32,
            "pub": b"\x00" * 32,
            "sig": b"\x00" * 64,
        }
        with self.assertRaises(ValueError) as ctx:
            decode_shard_payload(cbor2.dumps(payload, canonical=True))
        self.assertIn("share_count", str(ctx.exception).lower())

    def test_decode_rejects_invalid_share_length_shapes(self) -> None:
        base_payload = {
            "version": SHARD_VERSION,
            "type": KEY_TYPE_PASSPHRASE,
            "threshold": 1,
            "share_count": 1,
            "share_index": 1,
            "length": 1,
            "share": b"\x01" * 16,
            "hash": b"\x00" * 32,
            "pub": b"\x00" * 32,
            "sig": b"\x00" * 64,
        }
        cases = (
            {
                "name": "share-not-block-multiple",
                "override": {"share": b"\x01" * 15},
            },
            {
                "name": "length-exceeds-share",
                "override": {"length": 17},
            },
            {
                "name": "share-length-inconsistent-with-length",
                "override": {"share": b"\x01" * 32},
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                payload = dict(base_payload)
                payload.update(case["override"])
                with self.assertRaises(ValueError):
                    decode_shard_payload(cbor2.dumps(payload, canonical=True))

    def test_split_rejects_shares_over_255(self) -> None:
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        with self.assertRaises(ValueError):
            split_passphrase(
                "passphrase",
                threshold=2,
                shares=MAX_SHARES + 1,
                doc_hash=doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )


if __name__ == "__main__":
    unittest.main()
