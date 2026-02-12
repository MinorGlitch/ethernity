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

import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.cli.flows.recover_input import (
    _PayloadCollectionState,
    collect_fallback_frames,
    collect_payload_frames,
    parse_recovery_lines,
    prompt_recovery_input_interactive,
    prompt_text_or_payloads_stdin,
)
from ethernity.cli.io.frames import _frame_from_payload_text, _frames_from_scan, _read_text_lines
from ethernity.core.bounds import MAX_QR_PAYLOAD_CHARS
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.zbase32 import encode_zbase32

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "recovery_parse_vectors.json"


def _base64_payload_for_main_data(size: int) -> str:
    frame = Frame(
        version=VERSION,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=b"\x44" * DOC_ID_LEN,
        index=0,
        total=1,
        data=b"x" * size,
    )
    return base64.b64encode(encode_frame(frame)).decode("ascii").rstrip("=")


def _find_payload_with_length(target: int) -> str:
    for size in range(1, 20_000):
        payload = _base64_payload_for_main_data(size)
        if len(payload) == target:
            return payload
    raise AssertionError(f"unable to build payload with target length {target}")


class TestRecoverInput(unittest.TestCase):
    def test_recovery_parse_vectors(self) -> None:
        fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
        for case in fixture["recovery_cases"]:
            with self.subTest(case=case["name"]):
                lines = case["input"].splitlines()
                if "expect_error_contains" in case:
                    with self.assertRaisesRegex(ValueError, case["expect_error_contains"]):
                        parse_recovery_lines(
                            lines,
                            allow_unsigned=bool(case["allow_unsigned"]),
                            quiet=True,
                            source=case["name"],
                        )
                    continue

                frames, label = parse_recovery_lines(
                    lines,
                    allow_unsigned=bool(case["allow_unsigned"]),
                    quiet=True,
                    source=case["name"],
                )
                self.assertEqual(label, case["expect_label"])
                frame_types = [FrameType(frame.frame_type).name for frame in frames]
                self.assertEqual(frame_types, case["expect_frame_types"])

    def test_payload_collection_rejects_doc_id_mismatch(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=True, quiet=True)
        first = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x10" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"first",
        )
        second = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"second",
        )
        self.assertTrue(state.ingest(first))
        self.assertFalse(state.ingest(second))
        self.assertEqual(len(state.frames), 1)

    def test_payload_collection_requires_auth_when_unsigned_disabled(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=False, quiet=True)
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x20" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"main",
        )
        auth_frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x20" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"auth",
        )
        self.assertFalse(state.ingest(main_frame))
        self.assertTrue(state.ingest(auth_frame))
        self.assertEqual(len(state.frames), 2)

    def test_parse_recovery_lines_accepts_ungrouped_fallback(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x41" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"main-data",
        )
        line = encode_zbase32(encode_frame(frame))
        frames, label = parse_recovery_lines(
            [line],
            allow_unsigned=True,
            quiet=True,
            source="unit-test",
        )
        self.assertEqual(label, "Recovery text")
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].frame_type, FrameType.MAIN_DOCUMENT)
        self.assertEqual(frames[0].data, b"main-data")

    def test_parse_recovery_lines_rejects_hex_payload(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x42" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"hex-main-data",
        )
        line = encode_frame(frame).hex()
        with self.assertRaisesRegex(ValueError, "unable to parse recovery text"):
            parse_recovery_lines(
                [line],
                allow_unsigned=True,
                quiet=True,
                source="unit-test",
            )

    def test_parse_recovery_lines_rejects_base64url_payload(self) -> None:
        line: str | None = None
        for value in range(256):
            frame = Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x43" * DOC_ID_LEN,
                index=0,
                total=1,
                data=bytes([value]) * 16,
            )
            candidate = base64.urlsafe_b64encode(encode_frame(frame)).decode("ascii").rstrip("=")
            if "-" in candidate or "_" in candidate:
                line = candidate
                break
        self.assertIsNotNone(line)

        with self.assertRaisesRegex(ValueError, "unable to parse recovery text"):
            parse_recovery_lines(
                [line or ""],
                allow_unsigned=True,
                quiet=True,
                source="unit-test",
            )

    def test_parse_recovery_lines_rejects_padded_base64_payload(self) -> None:
        line: str | None = None
        for size in range(1, 128):
            frame = Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x45" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"x" * size,
            )
            candidate = base64.b64encode(encode_frame(frame)).decode("ascii")
            if "=" in candidate:
                line = candidate
                break
        self.assertIsNotNone(line)

        with self.assertRaisesRegex(ValueError, "unable to parse recovery text"):
            parse_recovery_lines(
                [line or ""],
                allow_unsigned=True,
                quiet=True,
                source="unit-test",
            )

    def test_frame_from_payload_text_accepts_qr_payload_char_limit(self) -> None:
        payload_text = _find_payload_with_length(MAX_QR_PAYLOAD_CHARS)
        frame = _frame_from_payload_text(payload_text)
        self.assertEqual(frame.frame_type, FrameType.MAIN_DOCUMENT)

    def test_frame_from_payload_text_rejects_qr_payload_char_limit_overflow(self) -> None:
        payload_text = "A" * (MAX_QR_PAYLOAD_CHARS + 1)
        with self.assertRaisesRegex(ValueError, "MAX_QR_PAYLOAD_CHARS"):
            _frame_from_payload_text(payload_text)

    def test_frame_from_payload_text_rejects_hex_text_input(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x44" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"hex-main-data",
        )
        with self.assertRaises(ValueError):
            _frame_from_payload_text(encode_frame(frame).hex())

    def test_frame_from_payload_text_qr_payload_whitespace_handling(self) -> None:
        payload_text = _find_payload_with_length(MAX_QR_PAYLOAD_CHARS)
        spaced_payload = " \n".join(
            payload_text[i : i + 64] for i in range(0, len(payload_text), 64)
        )
        frame = _frame_from_payload_text(spaced_payload)
        self.assertEqual(frame.frame_type, FrameType.MAIN_DOCUMENT)

    def test_frames_from_scan_rejects_qr_payload_char_limit_overflow(self) -> None:
        oversized_payload = "A" * (MAX_QR_PAYLOAD_CHARS + 1)
        with mock.patch(
            "ethernity.cli.io.frames.scan_qr_payloads",
            return_value=[oversized_payload],
        ):
            with self.assertRaisesRegex(ValueError, "MAX_QR_PAYLOAD_CHARS"):
                _frames_from_scan(["scan.png"])

    def test_read_text_lines_rejects_recovery_text_file_size_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "recovery.txt"
            path.write_text("x" * 11, encoding="utf-8")
            with mock.patch("ethernity.cli.io.frames.MAX_RECOVERY_TEXT_BYTES", 10):
                with self.assertRaisesRegex(ValueError, "MAX_RECOVERY_TEXT_BYTES"):
                    _read_text_lines(str(path))

    def test_read_text_lines_rejects_recovery_text_stdin_size_overflow(self) -> None:
        with mock.patch("ethernity.cli.io.frames.MAX_RECOVERY_TEXT_BYTES", 10):
            with mock.patch("ethernity.cli.io.frames.sys.stdin", new=io.StringIO("x" * 11)):
                with self.assertRaisesRegex(ValueError, "MAX_RECOVERY_TEXT_BYTES"):
                    _read_text_lines("-")

    def test_read_text_lines_accepts_recovery_text_exact_size_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "recovery.txt"
            path.write_text("x" * 10, encoding="utf-8")
            with mock.patch("ethernity.cli.io.frames.MAX_RECOVERY_TEXT_BYTES", 10):
                lines = _read_text_lines(str(path))
        self.assertEqual(lines, ["x" * 10])

    def test_payload_collection_next_prompt_transitions(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=False, quiet=True)
        self.assertEqual(state.next_prompt(), "QR payload")
        state.main_total = 2
        state.main_indices = {0}
        self.assertEqual(state.next_prompt(), "QR payload (2 remaining)")
        state.main_indices = {0, 1}
        self.assertEqual(state.next_prompt(), "Auth QR payload (1 remaining)")

    def test_payload_collection_rejects_total_mismatch(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=True, quiet=True)
        first = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x51" * DOC_ID_LEN,
            index=0,
            total=2,
            data=b"a",
        )
        second = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x51" * DOC_ID_LEN,
            index=1,
            total=3,
            data=b"b",
        )
        self.assertFalse(state.ingest(first))
        self.assertFalse(state.ingest(second))

    def test_payload_collection_rejects_conflicting_duplicate(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=True, quiet=True)
        first = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x52" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"first",
        )
        second = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x52" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"second",
        )
        self.assertTrue(state.ingest(first))
        self.assertFalse(state.ingest(second))

    def test_payload_collection_ignores_identical_duplicate_in_verbose_mode(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=True, quiet=False)
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x53" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"same",
        )
        with mock.patch("ethernity.cli.flows.recover_input.console.print") as print_mock:
            self.assertTrue(state.ingest(frame))
            self.assertFalse(state.ingest(frame))
        self.assertTrue(
            any("Duplicate payload ignored." in str(call) for call in print_mock.call_args_list)
        )

    def test_payload_collection_rejects_non_main_or_auth_frames(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=True, quiet=True)
        shard = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x54" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"shard",
        )
        self.assertFalse(state.ingest(shard))

    def test_payload_collection_waiting_message_when_no_main_seen(self) -> None:
        state = _PayloadCollectionState(allow_unsigned=False, quiet=False)
        with mock.patch("ethernity.cli.flows.recover_input.console.print") as print_mock:
            self.assertFalse(state._is_complete())
        self.assertTrue(
            any("Waiting for a MAIN frame" in str(call) for call in print_mock.call_args_list)
        )

    def test_prompt_text_or_payloads_stdin_uses_fallback_when_mode_unknown(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x55" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        with mock.patch(
            "ethernity.cli.flows.recover_input.prompt_required", return_value="bad input"
        ):
            with mock.patch(
                "ethernity.cli.flows.recover_input._detect_recovery_input_mode",
                side_effect=ValueError("bad"),
            ):
                with mock.patch(
                    "ethernity.cli.flows.recover_input.collect_fallback_frames",
                    return_value=[frame],
                ) as collect_mock:
                    frames, label = prompt_text_or_payloads_stdin(
                        allow_unsigned=True,
                        quiet=True,
                    )
        self.assertEqual(label, "Recovery text")
        self.assertEqual(frames, [frame])
        collect_mock.assert_called_once()

    def test_prompt_text_or_payloads_stdin_uses_payload_flow(self) -> None:
        first_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x56" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        with mock.patch(
            "ethernity.cli.flows.recover_input.prompt_required", return_value="payload"
        ):
            with mock.patch(
                "ethernity.cli.flows.recover_input._detect_recovery_input_mode",
                return_value="payload",
            ):
                with mock.patch(
                    "ethernity.cli.flows.recover_input._frame_from_payload_text",
                    return_value=first_frame,
                ):
                    with mock.patch(
                        "ethernity.cli.flows.recover_input.collect_payload_frames",
                        return_value=[first_frame],
                    ) as collect_mock:
                        frames, label = prompt_text_or_payloads_stdin(
                            allow_unsigned=True,
                            quiet=True,
                        )
        self.assertEqual(label, "QR payloads")
        self.assertEqual(frames, [first_frame])
        collect_mock.assert_called_once()

    def test_collect_fallback_frames_retries_after_invalid_initial_lines(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x57" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        with mock.patch(
            "ethernity.cli.flows.recover_input._frames_from_fallback_lines",
            side_effect=[ValueError("bad"), [frame]],
        ):
            with mock.patch(
                "ethernity.cli.flows.recover_input.prompt_multiline",
                return_value=["ybndr fghj"],
            ):
                with mock.patch(
                    "ethernity.cli.flows.recover_input.status",
                    return_value=contextlib.nullcontext(),
                ):
                    frames = collect_fallback_frames(
                        allow_unsigned=True,
                        quiet=True,
                        initial_lines=["not-fallback"],
                    )
        self.assertEqual(frames, [frame])

    def test_collect_payload_frames_retries_invalid_payload_then_succeeds(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x58" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        with mock.patch(
            "ethernity.cli.flows.recover_input.prompt_required",
            side_effect=["bad", "good"],
        ):
            with mock.patch(
                "ethernity.cli.flows.recover_input._frame_from_payload_text",
                side_effect=[ValueError("bad"), frame],
            ):
                frames = collect_payload_frames(allow_unsigned=True, quiet=True)
        self.assertEqual(frames, [frame])

    def test_collect_payload_frames_waits_for_auth_when_unsigned_not_allowed(self) -> None:
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x59" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"main",
        )
        auth_frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x59" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"auth",
        )
        with mock.patch("ethernity.cli.flows.recover_input.prompt_required", return_value="auth"):
            with mock.patch(
                "ethernity.cli.flows.recover_input._frame_from_payload_text",
                return_value=auth_frame,
            ):
                frames = collect_payload_frames(
                    allow_unsigned=False,
                    quiet=True,
                    first_frame=main_frame,
                )
        self.assertEqual(len(frames), 2)
        self.assertEqual(
            {frame.frame_type for frame in frames}, {FrameType.MAIN_DOCUMENT, FrameType.AUTH}
        )

    def test_prompt_recovery_input_interactive_uses_text_stdin_path(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x60" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        with mock.patch("ethernity.cli.flows.recover_input.prompt_choice", return_value="text"):
            with mock.patch(
                "ethernity.cli.flows.recover_input.prompt_path_with_picker", return_value="-"
            ):
                with mock.patch(
                    "ethernity.cli.flows.recover_input.prompt_text_or_payloads_stdin",
                    return_value=([frame], "Recovery text"),
                ):
                    frames, label, detail = prompt_recovery_input_interactive(
                        allow_unsigned=True,
                        quiet=True,
                    )
        self.assertEqual(label, "Recovery text")
        self.assertEqual(detail, "stdin")
        self.assertEqual(frames, [frame])

    def test_prompt_recovery_input_interactive_uses_scan_path(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x61" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        with mock.patch("ethernity.cli.flows.recover_input.prompt_choice", return_value="scan"):
            with mock.patch(
                "ethernity.cli.flows.recover_input.prompt_path_with_picker",
                return_value="scan.png",
            ):
                with mock.patch(
                    "ethernity.cli.flows.recover_input._frames_from_scan",
                    return_value=[frame],
                ):
                    with mock.patch(
                        "ethernity.cli.flows.recover_input.status",
                        return_value=contextlib.nullcontext(),
                    ):
                        frames, label, detail = prompt_recovery_input_interactive(
                            allow_unsigned=True,
                            quiet=True,
                        )
        self.assertEqual(label, "Scan")
        self.assertEqual(detail, "scan.png")
        self.assertEqual(frames, [frame])

    def test_prompt_recovery_input_interactive_retries_after_parse_error(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x62" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        with mock.patch(
            "ethernity.cli.flows.recover_input.prompt_choice",
            side_effect=["text", "scan"],
        ):
            with mock.patch(
                "ethernity.cli.flows.recover_input.prompt_path_with_picker",
                side_effect=["recovery.txt", "scan.png"],
            ):
                with mock.patch(
                    "ethernity.cli.flows.recover_input._read_text_lines",
                    side_effect=[ValueError("bad"), ["line"]],
                ):
                    with mock.patch(
                        "ethernity.cli.flows.recover_input._frames_from_scan",
                        return_value=[frame],
                    ):
                        with mock.patch(
                            "ethernity.cli.flows.recover_input.status",
                            return_value=contextlib.nullcontext(),
                        ):
                            frames, label, detail = prompt_recovery_input_interactive(
                                allow_unsigned=True,
                                quiet=True,
                            )
        self.assertEqual(label, "Scan")
        self.assertEqual(detail, "scan.png")
        self.assertEqual(frames, [frame])


if __name__ == "__main__":
    unittest.main()
