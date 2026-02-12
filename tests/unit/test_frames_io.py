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

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.cli.io.frames import (
    _auth_frames_from_payloads,
    _decode_payload,
    _dedupe_auth_frames,
    _dedupe_frames,
    _detect_recovery_input_mode,
    _frame_from_fallback_lines,
    _frame_from_payload_text,
    _frames_from_payload_lines,
    _frames_from_scan,
    _read_text_lines,
    _split_main_and_auth_frames,
)
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType, encode_frame
from ethernity.encoding.qr_payloads import encode_qr_payload
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.qr.scan import QrScanError


class TestFramesIo(unittest.TestCase):
    @staticmethod
    def _frame(
        *,
        frame_type: FrameType = FrameType.MAIN_DOCUMENT,
        doc_id: bytes | None = None,
        index: int = 0,
        total: int = 1,
        data: bytes = b"payload",
    ) -> Frame:
        return Frame(
            version=1,
            frame_type=frame_type,
            doc_id=doc_id or (b"\x11" * DOC_ID_LEN),
            index=index,
            total=total,
            data=data,
        )

    def test_read_text_lines_reports_file_not_found(self) -> None:
        with self.assertRaisesRegex(ValueError, "file not found"):
            _read_text_lines("/no/such/file/recovery.txt")

    def test_read_text_lines_reports_utf8_decode_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input.txt"
            path.write_bytes(b"\xff\xfe\xfd")
            with self.assertRaisesRegex(ValueError, "not UTF-8 text"):
                _read_text_lines(str(path))

    def test_read_text_lines_reports_os_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input.txt"
            path.write_text("ok", encoding="utf-8")
            with mock.patch("builtins.open", side_effect=OSError("blocked")):
                with self.assertRaisesRegex(ValueError, "unable to read file"):
                    _read_text_lines(str(path))

    def test_frame_from_fallback_lines_warns_about_skipped_lines(self) -> None:
        frame = self._frame()
        with mock.patch(
            "ethernity.cli.io.frames._parse_fallback_frame",
            return_value=(frame, 2),
        ):
            with mock.patch("ethernity.cli.io.frames._warn") as warn_mock:
                parsed = _frame_from_fallback_lines(["a", "b"], label="fallback")
        self.assertEqual(parsed, frame)
        warn_mock.assert_called_once()

    def test_detect_recovery_input_mode_prefers_marked_fallback(self) -> None:
        payload = encode_qr_payload(encode_frame(self._frame()))
        mode = _detect_recovery_input_mode(["AUTH FRAME", payload])
        self.assertEqual(mode, "fallback_marked")

    def test_detect_recovery_input_mode_detects_payload(self) -> None:
        payload = encode_qr_payload(encode_frame(self._frame()))
        mode = _detect_recovery_input_mode([payload])
        self.assertEqual(mode, "payload")

    def test_detect_recovery_input_mode_detects_fallback(self) -> None:
        line = encode_zbase32(encode_frame(self._frame()))
        mode = _detect_recovery_input_mode([line])
        self.assertEqual(mode, "fallback")

    def test_detect_recovery_input_mode_rejects_mixed_invalid_lines(self) -> None:
        with self.assertRaisesRegex(ValueError, "neither a valid QR payload list"):
            _detect_recovery_input_mode(["%%%", "***"])

    def test_frames_from_payload_lines_reports_invalid_line_index(self) -> None:
        payload = encode_qr_payload(encode_frame(self._frame()))
        with self.assertRaisesRegex(ValueError, "line 2"):
            _frames_from_payload_lines([payload, "%%%"], source="stdin")

    def test_frames_from_payload_lines_rejects_empty_content(self) -> None:
        with self.assertRaisesRegex(ValueError, "no QR payloads found"):
            _frames_from_payload_lines(["", "   "], source="stdin")

    def test_auth_frames_from_payloads_rejects_non_auth_frames(self) -> None:
        payload = encode_qr_payload(encode_frame(self._frame(frame_type=FrameType.MAIN_DOCUMENT)))
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "payloads.txt"
            path.write_text(payload + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "AUTH payloads only"):
                _auth_frames_from_payloads(str(path))

    def test_frames_from_scan_reports_scan_failures(self) -> None:
        with mock.patch(
            "ethernity.cli.io.frames.scan_qr_payloads",
            side_effect=QrScanError("boom"),
        ):
            with self.assertRaisesRegex(ValueError, "scan failed"):
                _frames_from_scan(["scan.png"])

    def test_frames_from_scan_reports_no_payloads(self) -> None:
        with mock.patch("ethernity.cli.io.frames.scan_qr_payloads", return_value=[]):
            with self.assertRaisesRegex(ValueError, "no QR payloads found"):
                _frames_from_scan(["scan.png"])

    def test_frames_from_scan_reports_all_invalid_payloads(self) -> None:
        with mock.patch(
            "ethernity.cli.io.frames.scan_qr_payloads",
            return_value=["bad-1", "bad-2"],
        ):
            with mock.patch(
                "ethernity.cli.io.frames._frame_from_payload_text",
                side_effect=[ValueError("bad one"), ValueError("bad two")],
            ):
                with self.assertRaisesRegex(ValueError, r"invalid QR payloads \(2\)"):
                    _frames_from_scan(["scan.png"])

    def test_dedupe_frames_accepts_identical_duplicates(self) -> None:
        frame = self._frame()
        deduped = _dedupe_frames([frame, frame])
        self.assertEqual(deduped, [frame])

    def test_dedupe_frames_rejects_conflicting_duplicates(self) -> None:
        frame_a = self._frame(data=b"A")
        frame_b = self._frame(data=b"B")
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            _dedupe_frames([frame_a, frame_b])

    def test_dedupe_auth_frames_rejects_non_auth(self) -> None:
        with self.assertRaisesRegex(ValueError, "AUTH type"):
            _dedupe_auth_frames([self._frame(frame_type=FrameType.MAIN_DOCUMENT)])

    def test_split_main_and_auth_requires_main(self) -> None:
        auth = self._frame(frame_type=FrameType.AUTH)
        with self.assertRaisesRegex(ValueError, "no main document payloads"):
            _split_main_and_auth_frames([auth])

    def test_split_main_and_auth_rejects_unexpected_frame_type(self) -> None:
        main = self._frame(frame_type=FrameType.MAIN_DOCUMENT)
        shard = self._frame(frame_type=FrameType.KEY_DOCUMENT)
        with self.assertRaisesRegex(ValueError, "unexpected frame type"):
            _split_main_and_auth_frames([main, shard])

    def test_decode_payload_rejects_non_ascii_bytes(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be ASCII"):
            _decode_payload("π".encode("utf-8"))

    def test_decode_payload_enforces_char_limit(self) -> None:
        with mock.patch("ethernity.cli.io.frames.MAX_QR_PAYLOAD_CHARS", 4):
            with self.assertRaisesRegex(ValueError, "MAX_QR_PAYLOAD_CHARS"):
                _decode_payload("AAAAAA")

    def test_frame_from_payload_text_round_trips_valid_payload(self) -> None:
        frame = self._frame(frame_type=FrameType.AUTH, doc_id=b"\x22" * DOC_ID_LEN, data=b"auth")
        payload = encode_qr_payload(encode_frame(frame))
        parsed = _frame_from_payload_text(payload)
        self.assertEqual(parsed.frame_type, FrameType.AUTH)
        self.assertEqual(parsed.doc_id, frame.doc_id)

    def test_read_text_lines_reads_stdin(self) -> None:
        with mock.patch("ethernity.cli.io.frames.sys.stdin", new=io.StringIO("a\nb\n")):
            lines = _read_text_lines("-")
        self.assertEqual(lines, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
