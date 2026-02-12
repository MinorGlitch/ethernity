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

from ethernity.cli.flows.prompts import _ingest_shard_frame, _ShardPasteState
from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    ShardPayload,
    encode_shard_payload,
)
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType


def _build_shard_frame(
    *,
    share_index: int,
    share: bytes,
    key_type: str = KEY_TYPE_PASSPHRASE,
    threshold: int = 2,
    share_count: int = 3,
    doc_hash: bytes = b"\x11" * 32,
    sign_pub: bytes = b"\x22" * 32,
    index: int = 0,
    total: int = 1,
) -> Frame:
    payload = ShardPayload(
        share_index=share_index,
        threshold=threshold,
        share_count=share_count,
        key_type=key_type,
        share=share,
        secret_len=len(share),
        doc_hash=doc_hash,
        sign_pub=sign_pub,
        signature=b"\x33" * 64,
    )
    return Frame(
        version=VERSION,
        frame_type=FrameType.KEY_DOCUMENT,
        doc_id=b"\x44" * DOC_ID_LEN,
        index=index,
        total=total,
        data=encode_shard_payload(payload),
    )


class TestRecoverShardPrompts(unittest.TestCase):
    def test_duplicate_shard_same_payload_is_ignored(self) -> None:
        state = _ShardPasteState(frames=[], seen_shares={})
        frame = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        with mock.patch("ethernity.cli.flows.prompts.console.print") as print_mock:
            with mock.patch("ethernity.cli.flows.prompts.console_err.print"):
                first = _ingest_shard_frame(frame=frame, state=state, label="Shard documents")
                second = _ingest_shard_frame(frame=frame, state=state, label="Shard documents")
        self.assertFalse(first)
        self.assertFalse(second)
        self.assertEqual(len(state.frames), 1)
        self.assertEqual(len(state.seen_shares), 1)
        self.assertIn(
            mock.call("[subtitle]Duplicate shard ignored.[/subtitle]"),
            print_mock.mock_calls,
        )

    def test_duplicate_shard_conflict_is_rejected(self) -> None:
        state = _ShardPasteState(frames=[], seen_shares={})
        first_frame = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        conflicting_frame = _build_shard_frame(share_index=1, share=b"\xbb" * 16)
        with mock.patch("ethernity.cli.flows.prompts.console.print"):
            with mock.patch("ethernity.cli.flows.prompts.console_err.print") as error_print_mock:
                _ingest_shard_frame(frame=first_frame, state=state, label="Shard documents")
                accepted = _ingest_shard_frame(
                    frame=conflicting_frame,
                    state=state,
                    label="Shard documents",
                )
        self.assertFalse(accepted)
        self.assertEqual(len(state.frames), 1)
        self.assertEqual(len(state.seen_shares), 1)
        self.assertIn(
            mock.call("[error]This shard conflicts with one you've already provided.[/error]"),
            error_print_mock.mock_calls,
        )

    def test_threshold_completion_returns_true_when_enough_shards_collected(self) -> None:
        state = _ShardPasteState(frames=[], seen_shares={})
        frame_one = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        frame_two = _build_shard_frame(share_index=2, share=b"\xbb" * 16)
        with mock.patch("ethernity.cli.flows.prompts.console.print") as print_mock:
            with mock.patch("ethernity.cli.flows.prompts.console_err.print"):
                first = _ingest_shard_frame(frame=frame_one, state=state, label="Shard documents")
                second = _ingest_shard_frame(frame=frame_two, state=state, label="Shard documents")
        self.assertFalse(first)
        self.assertTrue(second)
        self.assertEqual(len(state.frames), 2)
        self.assertEqual(len(state.seen_shares), 2)
        self.assertIn(
            mock.call("[success]All required shard documents captured.[/success]"),
            print_mock.mock_calls,
        )

    def test_rejects_non_shard_frame_and_multiframe(self) -> None:
        state = _ShardPasteState(frames=[], seen_shares={})
        wrong_type = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x44" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"x",
        )
        multiframe = _build_shard_frame(share_index=1, share=b"\xaa" * 16, index=1, total=2)
        with mock.patch("ethernity.cli.flows.prompts.console.print"):
            with mock.patch("ethernity.cli.flows.prompts.console_err.print") as error_print_mock:
                self.assertFalse(
                    _ingest_shard_frame(frame=wrong_type, state=state, label="Shard documents")
                )
                self.assertFalse(
                    _ingest_shard_frame(frame=multiframe, state=state, label="Shard documents")
                )
        self.assertEqual(len(state.frames), 0)
        self.assertEqual(len(error_print_mock.mock_calls), 2)

    def test_rejects_decode_error_and_wrong_key_type(self) -> None:
        state = _ShardPasteState(frames=[], seen_shares={})
        invalid = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x44" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"bad-cbor",
        )
        signing_seed_frame = _build_shard_frame(
            share_index=1,
            share=b"\xaa" * 16,
            key_type=KEY_TYPE_SIGNING_SEED,
        )
        with mock.patch("ethernity.cli.flows.prompts.console.print"):
            with mock.patch("ethernity.cli.flows.prompts.console_err.print") as error_print_mock:
                self.assertFalse(
                    _ingest_shard_frame(frame=invalid, state=state, label="Shard documents")
                )
                self.assertFalse(
                    _ingest_shard_frame(
                        frame=signing_seed_frame, state=state, label="Shard documents"
                    )
                )
        self.assertEqual(len(state.frames), 0)
        self.assertEqual(len(error_print_mock.mock_calls), 2)

    def test_rejects_mismatched_shard_metadata(self) -> None:
        state = _ShardPasteState(frames=[], seen_shares={})
        first = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        mismatched = _build_shard_frame(
            share_index=2,
            share=b"\xbb" * 16,
            threshold=3,
            share_count=5,
            doc_hash=b"\x99" * 32,
            sign_pub=b"\x88" * 32,
        )
        with mock.patch("ethernity.cli.flows.prompts.console.print"):
            with mock.patch("ethernity.cli.flows.prompts.console_err.print") as error_print_mock:
                self.assertFalse(
                    _ingest_shard_frame(frame=first, state=state, label="Shard documents")
                )
                self.assertFalse(
                    _ingest_shard_frame(frame=mismatched, state=state, label="Shard documents")
                )
        self.assertEqual(len(state.frames), 1)
        self.assertEqual(len(state.seen_shares), 1)
        self.assertGreaterEqual(len(error_print_mock.mock_calls), 1)


if __name__ == "__main__":
    unittest.main()
