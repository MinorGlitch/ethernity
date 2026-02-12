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

import contextlib
import unittest
from unittest import mock

from ethernity.cli.flows import prompts
from ethernity.cli.flows.prompts import _ShardPasteState
from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE, ShardPayload, encode_shard_payload
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType


def _build_shard_frame(
    *,
    share_index: int,
    share: bytes,
    threshold: int = 2,
    share_count: int = 3,
) -> Frame:
    payload = ShardPayload(
        share_index=share_index,
        threshold=threshold,
        share_count=share_count,
        key_type=KEY_TYPE_PASSPHRASE,
        share=share,
        secret_len=len(share),
        doc_hash=b"\x11" * 32,
        sign_pub=b"\x22" * 32,
        signature=b"\x33" * 64,
    )
    return Frame(
        version=VERSION,
        frame_type=FrameType.KEY_DOCUMENT,
        doc_id=b"\x44" * DOC_ID_LEN,
        index=0,
        total=1,
        data=encode_shard_payload(payload),
    )


class TestCliFlowPrompts(unittest.TestCase):
    def test_format_shard_errors(self) -> None:
        self.assertIn(
            "No shard data found",
            prompts._format_shard_input_error(ValueError("No valid shard data found in files")),
        )
        self.assertEqual(
            prompts._format_shard_input_error(ValueError("bad payload")),
            "bad payload",
        )
        self.assertIn(
            "bad payload",
            prompts._format_shard_payload_error(ValueError("bad payload")),
        )

    def test_is_scan_path_suffix_matrix(self) -> None:
        self.assertTrue(prompts._is_scan_path("file.pdf"))
        self.assertTrue(prompts._is_scan_path("photo.JPEG"))
        self.assertFalse(prompts._is_scan_path("notes.txt"))
        self.assertFalse(prompts._is_scan_path("payload.bin"))

    def test_frames_from_shard_text_or_payload_lines_paths(self) -> None:
        frame = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        with mock.patch.object(prompts, "_frame_from_fallback_lines", return_value=frame):
            frames = prompts._frames_from_shard_text_or_payload_lines(["line"], source="stdin")
        self.assertEqual(frames, [frame])

        with (
            mock.patch.object(
                prompts, "_frame_from_fallback_lines", side_effect=ValueError("fallback bad")
            ),
            mock.patch.object(prompts, "_frames_from_payload_lines", return_value=[frame]),
        ):
            frames = prompts._frames_from_shard_text_or_payload_lines(["line"], source="stdin")
        self.assertEqual(frames, [frame])

        with (
            mock.patch.object(
                prompts, "_frame_from_fallback_lines", side_effect=ValueError("fallback bad")
            ),
            mock.patch.object(
                prompts, "_frames_from_payload_lines", side_effect=ValueError("payload bad")
            ),
            mock.patch.object(prompts, "format_fallback_error", return_value="fallback detail"),
        ):
            with self.assertRaisesRegex(
                ValueError,
                (
                    "unable to parse shard recovery text or QR payloads from stdin: "
                    "fallback detail; payload bad"
                ),
            ):
                prompts._frames_from_shard_text_or_payload_lines(["line"], source="stdin")

    def test_frames_from_shard_text_or_payload_files_paths(self) -> None:
        frame_one = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        frame_two = _build_shard_frame(share_index=2, share=b"\xbb" * 16)
        with (
            mock.patch.object(prompts, "_frames_from_scan", return_value=[frame_one]),
            mock.patch.object(prompts, "_read_text_lines", return_value=["line"]),
            mock.patch.object(
                prompts, "_frames_from_shard_text_or_payload_lines", return_value=[frame_two]
            ),
        ):
            frames = prompts._frames_from_shard_text_or_payload_files(["scan.pdf", "payload.txt"])
        self.assertEqual(frames, [frame_one, frame_two])

        with (
            mock.patch.object(prompts, "_frames_from_scan", return_value=[]),
            mock.patch.object(prompts, "_read_text_lines", return_value=["line"]),
            mock.patch.object(prompts, "_frames_from_shard_text_or_payload_lines", return_value=[]),
        ):
            with self.assertRaisesRegex(ValueError, "No valid shard data found"):
                prompts._frames_from_shard_text_or_payload_files(["payload.txt"])

    def test_prompt_shard_payload_paste_paths(self) -> None:
        frame_one = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        frame_two = _build_shard_frame(share_index=2, share=b"\xbb" * 16)

        done_state = _ShardPasteState(
            frames=[frame_one],
            seen_shares={1: b"\xaa" * 16},
            expected_threshold=1,
        )
        with mock.patch.object(prompts, "prompt_required") as prompt_required:
            self.assertEqual(prompts._prompt_shard_payload_paste(state=done_state), [frame_one])
        prompt_required.assert_not_called()

        state = _ShardPasteState(frames=[], seen_shares={})
        with mock.patch.object(prompts, "prompt_required") as prompt_required:
            frames = prompts._prompt_shard_payload_paste(
                initial_frames=[frame_one, frame_two],
                state=state,
            )
        self.assertEqual(len(frames), 2)
        prompt_required.assert_not_called()

        with (
            mock.patch.object(
                prompts, "prompt_required", side_effect=["bad", "good"]
            ) as prompt_required,
            mock.patch.object(
                prompts,
                "_frame_from_payload_text",
                side_effect=[ValueError("bad"), frame_one],
            ),
            mock.patch.object(prompts, "_ingest_shard_frame", return_value=True) as ingest,
            mock.patch.object(prompts.console_err, "print") as err_print,
            mock.patch.object(prompts.console, "print") as info_print,
        ):
            state = _ShardPasteState(frames=[], seen_shares={}, expected_threshold=1)
            frames = prompts._prompt_shard_payload_paste(state=state)
        self.assertEqual(frames, [])
        self.assertEqual(
            prompt_required.call_args_list[0].args[0], "Shard QR payload (1 remaining)"
        )
        self.assertTrue(
            any(
                "Paste one shard QR payload per line" in str(call)
                for call in info_print.call_args_list
            )
        )
        err_print.assert_called_once()
        ingest.assert_called_once()

    def test_prompt_shard_fallback_until_complete_paths(self) -> None:
        frame = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        with (
            mock.patch.object(prompts, "_frame_from_fallback_lines", return_value=frame),
            mock.patch.object(prompts, "prompt_required") as prompt_required,
        ):
            result = prompts._prompt_shard_fallback_until_complete(
                help_text=None,
                initial_lines=["line"],
            )
        self.assertEqual(result, frame)
        prompt_required.assert_not_called()

        with (
            mock.patch.object(
                prompts,
                "_frame_from_fallback_lines",
                side_effect=[ValueError("bad"), ValueError("bad"), frame],
            ),
            mock.patch.object(
                prompts, "prompt_required", side_effect=["a\nb", "c"]
            ) as prompt_required,
            mock.patch.object(
                prompts, "format_fallback_error", return_value="fallback parse error"
            ),
            mock.patch.object(prompts.console_err, "print") as err_print,
        ):
            result = prompts._prompt_shard_fallback_until_complete(
                help_text="hint",
                initial_lines=["seed"],
                prompt_label="Paste shard recovery text",
            )
        self.assertEqual(result, frame)
        self.assertEqual(prompt_required.call_count, 2)
        self.assertEqual(err_print.call_count, 2)

    def test_prompt_shard_fallback_paste_paths(self) -> None:
        frame_one = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        frame_two = _build_shard_frame(share_index=2, share=b"\xbb" * 16)

        done_state = _ShardPasteState(
            frames=[frame_one],
            seen_shares={1: b"\xaa" * 16},
            expected_threshold=1,
        )
        with mock.patch.object(prompts, "_prompt_shard_fallback_until_complete") as prompt_more:
            self.assertEqual(prompts._prompt_shard_fallback_paste(state=done_state), [frame_one])
        prompt_more.assert_not_called()

        state = _ShardPasteState(frames=[], seen_shares={})
        with (
            mock.patch.object(
                prompts,
                "_prompt_shard_fallback_until_complete",
                side_effect=[frame_one, frame_two],
            ),
            mock.patch.object(prompts.console, "print") as info_print,
        ):
            with mock.patch.object(prompts.console_err, "print"):
                frames = prompts._prompt_shard_fallback_paste(state=state)
        self.assertEqual(len(frames), 2)
        self.assertTrue(
            any(
                "Paste shard recovery text in batches" in str(call)
                for call in info_print.call_args_list
            )
        )

    def test_prompt_shard_text_or_payloads_stdin_paths(self) -> None:
        frame_one = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        frame_two = _build_shard_frame(share_index=2, share=b"\xbb" * 16)

        with (
            mock.patch.object(prompts, "prompt_required", return_value="fallback-text"),
            mock.patch.object(
                prompts, "_frame_from_payload_text", side_effect=ValueError("bad payload")
            ),
            mock.patch.object(
                prompts, "_prompt_shard_fallback_paste", return_value=[frame_one]
            ) as fallback,
        ):
            frames = prompts._prompt_shard_text_or_payloads_stdin()
        self.assertEqual(frames, [frame_one])
        fallback.assert_called_once()

        with (
            mock.patch.object(prompts, "prompt_required", return_value="payload"),
            mock.patch.object(prompts, "_frame_from_payload_text", return_value=frame_one),
            mock.patch.object(
                prompts, "_prompt_shard_payload_paste", return_value=[frame_one]
            ) as payload_paste,
        ):
            frames = prompts._prompt_shard_text_or_payloads_stdin()
        self.assertEqual(frames, [frame_one])
        self.assertEqual(payload_paste.call_args.kwargs["initial_frames"], [frame_one])

        with (
            mock.patch.object(prompts, "prompt_required", return_value="one\ntwo"),
            mock.patch.object(prompts, "_frame_from_payload_text", return_value=frame_one),
            mock.patch.object(
                prompts, "_frames_from_payload_lines", return_value=[frame_one, frame_two]
            ),
            mock.patch.object(
                prompts, "_prompt_shard_payload_paste", return_value=[frame_one, frame_two]
            ) as paste,
        ):
            frames = prompts._prompt_shard_text_or_payloads_stdin()
        self.assertEqual(frames, [frame_one, frame_two])
        self.assertEqual(paste.call_args.kwargs["initial_frames"], [frame_one, frame_two])

        with (
            mock.patch.object(prompts, "prompt_required", return_value="one\ntwo"),
            mock.patch.object(prompts, "_frame_from_payload_text", return_value=frame_one),
            mock.patch.object(
                prompts, "_frames_from_payload_lines", side_effect=ValueError("invalid batch")
            ),
            mock.patch.object(
                prompts, "_prompt_shard_payload_paste", return_value=[frame_one]
            ) as paste,
            mock.patch.object(prompts.console_err, "print") as err_print,
        ):
            frames = prompts._prompt_shard_text_or_payloads_stdin()
        self.assertEqual(frames, [frame_one])
        self.assertEqual(paste.call_args.kwargs["initial_frames"], [frame_one])
        err_print.assert_called_once()

    def test_prompt_shard_inputs_paths(self) -> None:
        frame_one = _build_shard_frame(share_index=1, share=b"\xaa" * 16)
        frame_two = _build_shard_frame(share_index=2, share=b"\xbb" * 16)

        with (
            mock.patch.object(prompts, "prompt_paths_with_picker", return_value=["-"]),
            mock.patch.object(
                prompts, "_prompt_shard_text_or_payloads_stdin", return_value=[frame_one]
            ),
        ):
            _scan, _text, frames = prompts._prompt_shard_inputs(quiet=True)
        self.assertEqual(frames, [frame_one])

        with (
            mock.patch.object(
                prompts,
                "prompt_paths_with_picker",
                side_effect=[["shards.txt"], ["shards.txt"]],
            ),
            mock.patch.object(
                prompts,
                "_frames_from_shard_text_or_payload_files",
                side_effect=[ValueError("bad input"), [frame_one, frame_two]],
            ),
            mock.patch.object(prompts, "status", return_value=contextlib.nullcontext(None)),
            mock.patch.object(prompts, "_format_shard_input_error", return_value="friendly error"),
            mock.patch.object(prompts.console_err, "print") as err_print,
        ):
            _scan, _text, frames = prompts._prompt_shard_inputs(quiet=True)
        self.assertEqual(len(frames), 2)
        err_print.assert_called_once()


if __name__ == "__main__":
    unittest.main()
