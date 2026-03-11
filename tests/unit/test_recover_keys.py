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

from __future__ import annotations

import hashlib
import unittest
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.keys.recover_keys import (
    _passphrase_from_shard_frames,
    _resolve_auth_payload,
    _signing_seed_from_shard_frames,
)
from ethernity.crypto.sharding import (
    LEGACY_SHARD_VERSION,
    ShardPayload,
    encode_shard_payload,
    split_passphrase,
)
from ethernity.crypto.signing import SHARD_SET_ID_LEN, generate_signing_keypair, sign_shard
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType

TEST_SHARD_SET_ID = b"s" * SHARD_SET_ID_LEN


class TestResolveAuthPayload(unittest.TestCase):
    @staticmethod
    def _auth_frame(*, doc_id: bytes, index: int = 0, total: int = 1) -> Frame:
        return Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=index,
            total=total,
            data=b"auth",
        )

    def test_missing_auth_requires_auth(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing auth payload"):
            _resolve_auth_payload(
                [],
                doc_id=b"\x10" * DOC_ID_LEN,
                doc_hash=b"\x20" * 32,
                allow_unsigned=False,
                require_auth=True,
                quiet=True,
            )

    def test_missing_auth_returns_skipped_when_allow_unsigned(self) -> None:
        with mock.patch("ethernity.cli.keys.recover_keys._warn") as warn_mock:
            payload, status = _resolve_auth_payload(
                [],
                doc_id=b"\x10" * DOC_ID_LEN,
                doc_hash=b"\x20" * 32,
                allow_unsigned=True,
                require_auth=False,
                quiet=True,
            )
        self.assertIsNone(payload)
        self.assertEqual(status, "skipped")
        warn_mock.assert_called_once()

    def test_missing_auth_returns_missing_when_strict_optional(self) -> None:
        payload, status = _resolve_auth_payload(
            [],
            doc_id=b"\x10" * DOC_ID_LEN,
            doc_hash=b"\x20" * 32,
            allow_unsigned=False,
            require_auth=False,
            quiet=True,
        )
        self.assertIsNone(payload)
        self.assertEqual(status, "missing")

    def test_multiple_auth_frames_rejected(self) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN)
        with self.assertRaisesRegex(ValueError, "multiple auth payloads"):
            _resolve_auth_payload(
                [frame, frame],
                doc_id=b"\x10" * DOC_ID_LEN,
                doc_hash=b"\x20" * 32,
                allow_unsigned=False,
                require_auth=True,
                quiet=True,
            )

    def test_auth_doc_id_mismatch_rejected(self) -> None:
        frame = self._auth_frame(doc_id=b"\x11" * DOC_ID_LEN)
        with self.assertRaisesRegex(ValueError, "doc_id does not match"):
            _resolve_auth_payload(
                [frame],
                doc_id=b"\x12" * DOC_ID_LEN,
                doc_hash=b"\x20" * 32,
                allow_unsigned=False,
                require_auth=True,
                quiet=True,
            )

    def test_auth_multiframe_metadata_rejected(self) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN, index=1, total=2)
        with self.assertRaisesRegex(ValueError, "single-frame payload"):
            _resolve_auth_payload(
                [frame],
                doc_id=b"\x10" * DOC_ID_LEN,
                doc_hash=b"\x20" * 32,
                allow_unsigned=False,
                require_auth=True,
                quiet=True,
            )

    def test_invalid_auth_payload_can_be_ignored_in_allow_unsigned_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN)
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_auth_payload",
            side_effect=ValueError("invalid cbor"),
        ):
            with mock.patch("ethernity.cli.keys.recover_keys._warn") as warn_mock:
                payload, status = _resolve_auth_payload(
                    [frame],
                    doc_id=b"\x10" * DOC_ID_LEN,
                    doc_hash=b"\x20" * 32,
                    allow_unsigned=True,
                    require_auth=False,
                    quiet=True,
                )
        self.assertIsNone(payload)
        self.assertEqual(status, "invalid")
        warn_mock.assert_called_once()

    def test_invalid_auth_payload_raises_in_strict_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN)
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_auth_payload",
            side_effect=ValueError("invalid cbor"),
        ):
            with self.assertRaisesRegex(ValueError, "invalid cbor"):
                _resolve_auth_payload(
                    [frame],
                    doc_id=b"\x10" * DOC_ID_LEN,
                    doc_hash=b"\x20" * 32,
                    allow_unsigned=False,
                    require_auth=True,
                    quiet=True,
                )

    def test_doc_hash_mismatch_can_be_ignored_in_allow_unsigned_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN)
        payload_obj = SimpleNamespace(
            doc_hash=b"\x99" * 32, sign_pub=b"p" * 32, signature=b"s" * 64
        )
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_auth_payload", return_value=payload_obj
        ):
            with mock.patch("ethernity.cli.keys.recover_keys._warn") as warn_mock:
                payload, status = _resolve_auth_payload(
                    [frame],
                    doc_id=b"\x10" * DOC_ID_LEN,
                    doc_hash=b"\x20" * 32,
                    allow_unsigned=True,
                    require_auth=False,
                    quiet=True,
                )
        self.assertIsNone(payload)
        self.assertEqual(status, "ignored")
        warn_mock.assert_called_once()

    def test_doc_hash_mismatch_raises_in_strict_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN)
        payload_obj = SimpleNamespace(
            doc_hash=b"\x99" * 32, sign_pub=b"p" * 32, signature=b"s" * 64
        )
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_auth_payload", return_value=payload_obj
        ):
            with self.assertRaisesRegex(ValueError, "doc_hash does not match"):
                _resolve_auth_payload(
                    [frame],
                    doc_id=b"\x10" * DOC_ID_LEN,
                    doc_hash=b"\x20" * 32,
                    allow_unsigned=False,
                    require_auth=True,
                    quiet=True,
                )

    @mock.patch("ethernity.cli.keys.recover_keys.hmac.compare_digest", return_value=False)
    def test_doc_hash_mismatch_uses_compare_digest(
        self,
        compare_digest: mock.MagicMock,
    ) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN)
        payload_obj = SimpleNamespace(
            doc_hash=b"\x99" * 32, sign_pub=b"p" * 32, signature=b"s" * 64
        )
        expected = b"\x20" * 32
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_auth_payload", return_value=payload_obj
        ):
            with self.assertRaisesRegex(ValueError, "doc_hash does not match"):
                _resolve_auth_payload(
                    [frame],
                    doc_id=b"\x10" * DOC_ID_LEN,
                    doc_hash=expected,
                    allow_unsigned=False,
                    require_auth=True,
                    quiet=True,
                )
        compare_digest.assert_called_once_with(payload_obj.doc_hash, expected)

    def test_invalid_signature_can_be_ignored_in_allow_unsigned_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN)
        payload_obj = SimpleNamespace(
            doc_hash=b"\x20" * 32, sign_pub=b"p" * 32, signature=b"s" * 64
        )
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_auth_payload", return_value=payload_obj
        ):
            with mock.patch("ethernity.cli.keys.recover_keys.verify_auth", return_value=False):
                with mock.patch("ethernity.cli.keys.recover_keys._warn") as warn_mock:
                    payload, status = _resolve_auth_payload(
                        [frame],
                        doc_id=b"\x10" * DOC_ID_LEN,
                        doc_hash=b"\x20" * 32,
                        allow_unsigned=True,
                        require_auth=False,
                        quiet=True,
                    )
        self.assertIsNone(payload)
        self.assertEqual(status, "ignored")
        warn_mock.assert_called_once()

    def test_invalid_signature_raises_in_strict_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN)
        payload_obj = SimpleNamespace(
            doc_hash=b"\x20" * 32, sign_pub=b"p" * 32, signature=b"s" * 64
        )
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_auth_payload", return_value=payload_obj
        ):
            with mock.patch("ethernity.cli.keys.recover_keys.verify_auth", return_value=False):
                with self.assertRaisesRegex(ValueError, "invalid auth signature"):
                    _resolve_auth_payload(
                        [frame],
                        doc_id=b"\x10" * DOC_ID_LEN,
                        doc_hash=b"\x20" * 32,
                        allow_unsigned=False,
                        require_auth=True,
                        quiet=True,
                    )

    def test_verified_auth_payload_returns_payload(self) -> None:
        frame = self._auth_frame(doc_id=b"\x10" * DOC_ID_LEN)
        payload_obj = SimpleNamespace(
            doc_hash=b"\x20" * 32, sign_pub=b"p" * 32, signature=b"s" * 64
        )
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_auth_payload", return_value=payload_obj
        ):
            with mock.patch("ethernity.cli.keys.recover_keys.verify_auth", return_value=True):
                payload, status = _resolve_auth_payload(
                    [frame],
                    doc_id=b"\x10" * DOC_ID_LEN,
                    doc_hash=b"\x20" * 32,
                    allow_unsigned=False,
                    require_auth=True,
                    quiet=True,
                )
        self.assertIs(payload, payload_obj)
        self.assertEqual(status, "verified")


class TestPassphraseFromShardFrames(unittest.TestCase):
    @staticmethod
    def _shard_frame(*, doc_id: bytes, index: int = 0, total: int = 1) -> Frame:
        return Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=doc_id,
            index=index,
            total=total,
            data=b"shard",
        )

    @staticmethod
    def _payload(
        *,
        share_index: int,
        threshold: int = 2,
        share_count: int = 3,
        share: bytes | None = None,
        doc_hash: bytes | None = None,
        sign_pub: bytes | None = None,
    ) -> ShardPayload:
        return ShardPayload(
            share_index=share_index,
            threshold=threshold,
            share_count=share_count,
            key_type="passphrase",
            share=share or (bytes([share_index]) * 16),
            secret_len=16,
            doc_hash=doc_hash or (b"\x20" * 32),
            sign_pub=sign_pub or (b"p" * 32),
            signature=b"s" * 64,
            shard_set_id=TEST_SHARD_SET_ID,
        )

    def test_rejects_non_key_frames(self) -> None:
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x30" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"data",
        )
        with self.assertRaisesRegex(ValueError, "KEY_DOCUMENT"):
            _passphrase_from_shard_frames(
                [main_frame],
                expected_doc_id=None,
                expected_doc_hash=None,
                expected_sign_pub=None,
                allow_unsigned=True,
            )

    def test_rejects_doc_id_mismatch(self) -> None:
        frame = self._shard_frame(doc_id=b"\x31" * DOC_ID_LEN)
        with self.assertRaisesRegex(ValueError, "doc_id does not match"):
            _passphrase_from_shard_frames(
                [frame],
                expected_doc_id=b"\x32" * DOC_ID_LEN,
                expected_doc_hash=None,
                expected_sign_pub=None,
                allow_unsigned=True,
            )

    def test_rejects_non_single_shard_frames(self) -> None:
        frame = self._shard_frame(doc_id=b"\x33" * DOC_ID_LEN, index=1, total=2)
        with self.assertRaisesRegex(ValueError, "single-frame"):
            _passphrase_from_shard_frames(
                [frame],
                expected_doc_id=b"\x33" * DOC_ID_LEN,
                expected_doc_hash=None,
                expected_sign_pub=None,
                allow_unsigned=True,
            )

    def test_rejects_doc_hash_mismatch(self) -> None:
        frames = [
            self._shard_frame(doc_id=b"\x34" * DOC_ID_LEN),
            self._shard_frame(doc_id=b"\x34" * DOC_ID_LEN),
        ]
        payloads = [
            self._payload(share_index=1, doc_hash=b"\x20" * 32),
            self._payload(share_index=2, doc_hash=b"\x21" * 32),
        ]
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", side_effect=payloads
        ):
            with self.assertRaisesRegex(ValueError, "doc_hash does not match"):
                _passphrase_from_shard_frames(
                    frames,
                    expected_doc_id=b"\x34" * DOC_ID_LEN,
                    expected_doc_hash=None,
                    expected_sign_pub=None,
                    allow_unsigned=True,
                )

    def test_rejects_sign_pub_mismatch(self) -> None:
        frames = [
            self._shard_frame(doc_id=b"\x35" * DOC_ID_LEN),
            self._shard_frame(doc_id=b"\x35" * DOC_ID_LEN),
        ]
        payloads = [
            self._payload(share_index=1, sign_pub=b"p" * 32),
            self._payload(share_index=2, sign_pub=b"q" * 32),
        ]
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", side_effect=payloads
        ):
            with self.assertRaisesRegex(ValueError, "signing key does not match"):
                _passphrase_from_shard_frames(
                    frames,
                    expected_doc_id=b"\x35" * DOC_ID_LEN,
                    expected_doc_hash=None,
                    expected_sign_pub=None,
                    allow_unsigned=True,
                )

    def test_rejects_invalid_shard_signature_in_strict_mode(self) -> None:
        frame = self._shard_frame(doc_id=b"\x36" * DOC_ID_LEN)
        payload = self._payload(share_index=1)
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", return_value=payload
        ):
            with mock.patch("ethernity.cli.keys.recover_keys.verify_shard", return_value=False):
                with self.assertRaisesRegex(ValueError, "invalid shard signature"):
                    _passphrase_from_shard_frames(
                        [frame],
                        expected_doc_id=b"\x36" * DOC_ID_LEN,
                        expected_doc_hash=None,
                        expected_sign_pub=None,
                        allow_unsigned=False,
                    )

    def test_rejects_duplicate_share_index_with_conflicting_data(self) -> None:
        frames = [
            self._shard_frame(doc_id=b"\x37" * DOC_ID_LEN),
            self._shard_frame(doc_id=b"\x37" * DOC_ID_LEN),
        ]
        payloads = [
            self._payload(share_index=1, share=b"A" * 16),
            self._payload(share_index=1, share=b"B" * 16),
        ]
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", side_effect=payloads
        ):
            with self.assertRaisesRegex(ValueError, "duplicate shard index with mismatched data"):
                _passphrase_from_shard_frames(
                    frames,
                    expected_doc_id=b"\x37" * DOC_ID_LEN,
                    expected_doc_hash=None,
                    expected_sign_pub=None,
                    allow_unsigned=True,
                )

    def test_rejects_duplicate_share_index_with_mismatched_signature(self) -> None:
        frames = [
            self._shard_frame(doc_id=b"\x37" * DOC_ID_LEN),
            self._shard_frame(doc_id=b"\x37" * DOC_ID_LEN),
        ]
        payloads = [
            self._payload(share_index=1, share=b"A" * 16),
            ShardPayload(
                share_index=1,
                threshold=2,
                share_count=3,
                key_type="passphrase",
                share=b"A" * 16,
                secret_len=16,
                doc_hash=b"\x20" * 32,
                sign_pub=b"p" * 32,
                signature=b"t" * 64,
                shard_set_id=TEST_SHARD_SET_ID,
            ),
        ]
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", side_effect=payloads
        ):
            with self.assertRaisesRegex(ValueError, "duplicate shard index with mismatched data"):
                _passphrase_from_shard_frames(
                    frames,
                    expected_doc_id=b"\x37" * DOC_ID_LEN,
                    expected_doc_hash=None,
                    expected_sign_pub=None,
                    allow_unsigned=True,
                )

    def test_rejects_mismatched_thresholds(self) -> None:
        frames = [
            self._shard_frame(doc_id=b"\x38" * DOC_ID_LEN),
            self._shard_frame(doc_id=b"\x38" * DOC_ID_LEN),
        ]
        payloads = [
            self._payload(share_index=1, threshold=2),
            self._payload(share_index=2, threshold=3),
        ]
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", side_effect=payloads
        ):
            with self.assertRaisesRegex(ValueError, "thresholds do not match"):
                _passphrase_from_shard_frames(
                    frames,
                    expected_doc_id=b"\x38" * DOC_ID_LEN,
                    expected_doc_hash=None,
                    expected_sign_pub=None,
                    allow_unsigned=True,
                )

    def test_rejects_mismatched_share_counts(self) -> None:
        frames = [
            self._shard_frame(doc_id=b"\x39" * DOC_ID_LEN),
            self._shard_frame(doc_id=b"\x39" * DOC_ID_LEN),
        ]
        payloads = [
            self._payload(share_index=1, share_count=3),
            self._payload(share_index=2, share_count=4),
        ]
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", side_effect=payloads
        ):
            with self.assertRaisesRegex(ValueError, "share counts do not match"):
                _passphrase_from_shard_frames(
                    frames,
                    expected_doc_id=b"\x39" * DOC_ID_LEN,
                    expected_doc_hash=None,
                    expected_sign_pub=None,
                    allow_unsigned=True,
                )

    def test_rejects_when_not_enough_shares(self) -> None:
        frame = self._shard_frame(doc_id=b"\x3a" * DOC_ID_LEN)
        payload = self._payload(share_index=1, threshold=2)
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", return_value=payload
        ):
            with self.assertRaisesRegex(ValueError, "need at least 2 shard"):
                _passphrase_from_shard_frames(
                    [frame],
                    expected_doc_id=b"\x3a" * DOC_ID_LEN,
                    expected_doc_hash=None,
                    expected_sign_pub=None,
                    allow_unsigned=True,
                )

    def test_recovers_legacy_v1_passphrase_with_signature_verification(self) -> None:
        passphrase = "legacy-passphrase"
        doc_id = b"\x3c" * DOC_ID_LEN
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
        legacy_shares = []
        for share in shares:
            legacy_shares.append(
                ShardPayload(
                    share_index=share.share_index,
                    threshold=share.threshold,
                    share_count=share.share_count,
                    key_type=share.key_type,
                    share=share.share,
                    secret_len=share.secret_len,
                    doc_hash=share.doc_hash,
                    sign_pub=share.sign_pub,
                    signature=sign_shard(
                        share.doc_hash,
                        shard_version=LEGACY_SHARD_VERSION,
                        key_type=share.key_type,
                        threshold=share.threshold,
                        share_count=share.share_count,
                        share_index=share.share_index,
                        secret_len=share.secret_len,
                        share=share.share,
                        sign_pub=share.sign_pub,
                        sign_priv=sign_priv,
                    ),
                    version=LEGACY_SHARD_VERSION,
                )
            )
        frames = [
            Frame(
                version=VERSION,
                frame_type=FrameType.KEY_DOCUMENT,
                doc_id=doc_id,
                index=0,
                total=1,
                data=encode_shard_payload(legacy_shares[0]),
            ),
            Frame(
                version=VERSION,
                frame_type=FrameType.KEY_DOCUMENT,
                doc_id=doc_id,
                index=0,
                total=1,
                data=encode_shard_payload(legacy_shares[2]),
            ),
        ]

        recovered = _passphrase_from_shard_frames(
            frames,
            expected_doc_id=doc_id,
            expected_doc_hash=doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=False,
        )

        self.assertEqual(recovered, passphrase)

    def test_rejects_v2_shards_with_mismatched_set_ids_at_threshold(self) -> None:
        passphrase = "set-id-check"
        doc_id = b"\x3d" * DOC_ID_LEN
        doc_hash = hashlib.blake2b(b"ciphertext", digest_size=32).digest()
        sign_priv, sign_pub = generate_signing_keypair()
        first_set = split_passphrase(
            passphrase,
            threshold=2,
            shares=4,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        second_set = split_passphrase(
            passphrase,
            threshold=2,
            shares=4,
            doc_hash=doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
        frames = [
            Frame(
                version=VERSION,
                frame_type=FrameType.KEY_DOCUMENT,
                doc_id=doc_id,
                index=0,
                total=1,
                data=encode_shard_payload(first_set[0]),
            ),
            Frame(
                version=VERSION,
                frame_type=FrameType.KEY_DOCUMENT,
                doc_id=doc_id,
                index=0,
                total=1,
                data=encode_shard_payload(second_set[1]),
            ),
        ]

        with self.assertRaisesRegex(ValueError, "not mutually compatible"):
            _passphrase_from_shard_frames(
                frames,
                expected_doc_id=doc_id,
                expected_doc_hash=doc_hash,
                expected_sign_pub=sign_pub,
                allow_unsigned=False,
            )

    def test_recovers_passphrase_and_dedupes_identical_duplicate(self) -> None:
        frames = [
            self._shard_frame(doc_id=b"\x3b" * DOC_ID_LEN),
            self._shard_frame(doc_id=b"\x3b" * DOC_ID_LEN),
            self._shard_frame(doc_id=b"\x3b" * DOC_ID_LEN),
        ]
        payloads = [
            self._payload(share_index=1, share=b"A" * 16),
            self._payload(share_index=1, share=b"A" * 16),
            self._payload(share_index=2, share=b"B" * 16),
        ]
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", side_effect=payloads
        ):
            with mock.patch(
                "ethernity.cli.keys.recover_keys.recover_passphrase", return_value="ok"
            ) as rec:
                result = _passphrase_from_shard_frames(
                    frames,
                    expected_doc_id=b"\x3b" * DOC_ID_LEN,
                    expected_doc_hash=None,
                    expected_sign_pub=None,
                    allow_unsigned=True,
                )
        self.assertEqual(result, "ok")
        self.assertEqual(rec.call_count, 1)
        called_shares = rec.call_args[0][0]
        self.assertEqual(len(called_shares), 2)
        self.assertEqual({share.share_index for share in called_shares}, {1, 2})

    def test_rejects_when_no_shard_payloads_provided(self) -> None:
        with self.assertRaisesRegex(ValueError, "no shard payloads"):
            _passphrase_from_shard_frames(
                [],
                expected_doc_id=None,
                expected_doc_hash=None,
                expected_sign_pub=None,
                allow_unsigned=True,
            )


class TestSigningSeedFromShardFrames(unittest.TestCase):
    @staticmethod
    def _shard_frame(*, doc_id: bytes) -> Frame:
        return Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"shard",
        )

    def test_rejects_passphrase_shards_for_signing_seed_recovery(self) -> None:
        payload = ShardPayload(
            share_index=1,
            threshold=1,
            share_count=1,
            key_type="passphrase",
            share=b"A" * 16,
            secret_len=16,
            doc_hash=b"\x20" * 32,
            sign_pub=b"p" * 32,
            signature=b"s" * 64,
            shard_set_id=TEST_SHARD_SET_ID,
        )
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", return_value=payload
        ):
            with self.assertRaisesRegex(ValueError, "signing key shards"):
                _signing_seed_from_shard_frames(
                    [self._shard_frame(doc_id=b"\x41" * DOC_ID_LEN)],
                    expected_doc_id=b"\x41" * DOC_ID_LEN,
                    expected_doc_hash=None,
                    expected_sign_pub=None,
                    allow_unsigned=False,
                )

    def test_recovers_signing_seed(self) -> None:
        payload = ShardPayload(
            share_index=1,
            threshold=1,
            share_count=1,
            key_type="signing-seed",
            share=b"A" * 32,
            secret_len=32,
            doc_hash=b"\x20" * 32,
            sign_pub=b"p" * 32,
            signature=b"s" * 64,
            shard_set_id=TEST_SHARD_SET_ID,
        )
        with mock.patch(
            "ethernity.cli.keys.recover_keys.decode_shard_payload", return_value=payload
        ):
            with mock.patch("ethernity.cli.keys.recover_keys.verify_shard", return_value=True):
                with mock.patch(
                    "ethernity.cli.keys.recover_keys.recover_signing_seed",
                    return_value=b"z" * 32,
                ) as recover:
                    result = _signing_seed_from_shard_frames(
                        [self._shard_frame(doc_id=b"\x42" * DOC_ID_LEN)],
                        expected_doc_id=b"\x42" * DOC_ID_LEN,
                        expected_doc_hash=None,
                        expected_sign_pub=None,
                        allow_unsigned=False,
                    )
        self.assertEqual(result, b"z" * 32)
        recover.assert_called_once()


if __name__ == "__main__":
    unittest.main()
