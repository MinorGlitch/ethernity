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

import unittest
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.keys.recover_keys import _passphrase_from_shard_frames, _resolve_auth_payload
from ethernity.crypto.sharding import ShardPayload
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType


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


if __name__ == "__main__":
    unittest.main()
