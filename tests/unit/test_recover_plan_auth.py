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

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.cli.features.mint.workflow import _signing_key_shard_frames_from_args
from ethernity.cli.features.recover.planning import (
    _inspect_auth_payload,
    _shard_frames_from_args,
    build_recovery_plan,
    inspect_from_args,
    inspect_recovery_inputs,
    plan_from_args,
)
from ethernity.cli.shared.types import MintArgs, RecoverArgs
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden" / "base64" / "file_no_shard"
V1_1_SHARDED_EMBEDDED_FIXTURE_ROOT = (
    REPO_ROOT / "tests" / "fixtures" / "v1_1" / "golden" / "base64" / "sharded_embedded"
)


class TestInspectAuthPayload(unittest.TestCase):
    @staticmethod
    def _auth_frame(*, doc_id: bytes) -> Frame:
        return Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth",
        )

    def test_doc_id_mismatch_is_ignored_in_allow_unsigned_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x11" * DOC_ID_LEN)
        with mock.patch("ethernity.cli.features.recover.planning._warn") as warn_mock:
            payload, status, blocking_issues = _inspect_auth_payload(
                [frame],
                doc_id=b"\x12" * DOC_ID_LEN,
                doc_hash=b"\x20" * 32,
                allow_unsigned=True,
                require_auth=False,
                quiet=True,
            )
        self.assertIsNone(payload)
        self.assertEqual(status, "ignored")
        self.assertEqual(blocking_issues, ())
        warn_mock.assert_called_once()

    def test_doc_id_mismatch_is_blocking_in_strict_mode(self) -> None:
        frame = self._auth_frame(doc_id=b"\x11" * DOC_ID_LEN)
        payload, status, blocking_issues = _inspect_auth_payload(
            [frame],
            doc_id=b"\x12" * DOC_ID_LEN,
            doc_hash=b"\x20" * 32,
            allow_unsigned=False,
            require_auth=True,
            quiet=True,
        )
        self.assertIsNone(payload)
        self.assertEqual(status, "invalid")
        self.assertEqual(len(blocking_issues), 1)
        self.assertEqual(blocking_issues[0]["code"], "AUTH_PAYLOAD_DOC_ID_MISMATCH")

    def test_inspect_recovery_is_not_ready_when_optional_auth_input_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_payloads_path = Path(tmpdir) / "auth-only.txt"
            auth_line = [
                line
                for line in (V1_FIXTURE_ROOT / "main_payloads.txt")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ][-1]
            auth_payloads_path.write_text(auth_line + "\n", encoding="utf-8")
            args = RecoverArgs(
                payloads_file=str(V1_1_SHARDED_EMBEDDED_FIXTURE_ROOT / "main_payloads.txt"),
                shard_payloads_file=[
                    str(V1_1_SHARDED_EMBEDDED_FIXTURE_ROOT / "shard_payloads_threshold.txt")
                ],
                auth_payloads_file=str(auth_payloads_path),
                quiet=True,
            )

            inspection = inspect_from_args(args)

            self.assertFalse(inspection.unlock.satisfied)
            self.assertIsNone(inspection.unlock.resolved_passphrase)
            self.assertIn(
                "AUTH_PAYLOAD_MULTIPLE",
                {issue["code"] for issue in inspection.blocking_issues},
            )
            with self.assertRaisesRegex(ValueError, "multiple auth payloads provided"):
                plan_from_args(args)

    def test_shard_payload_file_errors_use_qr_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = Path(tmpdir) / "invalid-shard-payloads.txt"
            payload_path.write_text("not-a-valid-shard-payload\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "QR payload"):
                _shard_frames_from_args(
                    RecoverArgs(shard_payloads_file=[str(payload_path)], quiet=True),
                    quiet=True,
                )

    def test_signing_key_shard_payload_file_errors_use_qr_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_path = Path(tmpdir) / "invalid-signing-shard-payloads.txt"
            payload_path.write_text("not-a-valid-shard-payload\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "QR payload"):
                _signing_key_shard_frames_from_args(
                    MintArgs(signing_key_shard_payloads_file=[str(payload_path)], quiet=True),
                    quiet=True,
                )

    def test_build_recovery_plan_requires_auth_even_with_shards_in_strict_mode(self) -> None:
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        shard_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"shard",
        )

        with mock.patch(
            "ethernity.cli.features.recover.planning._resolve_auth_payload",
            return_value=(None, "missing"),
        ) as resolve_auth_mock:
            with mock.patch(
                "ethernity.cli.features.recover.planning._resolve_passphrase",
                return_value="passphrase",
            ):
                build_recovery_plan(
                    frames=[main_frame],
                    extra_auth_frames=[],
                    shard_frames=[shard_frame],
                    passphrase="passphrase",
                    allow_unsigned=False,
                    input_label=None,
                    input_detail=None,
                    shard_fallback_files=[],
                    shard_payloads_file=[],
                    shard_scan=[],
                    output_path=None,
                    args=None,
                    quiet=True,
                )

        self.assertTrue(resolve_auth_mock.call_args.kwargs["require_auth"])

    def test_inspect_recovery_inputs_requires_auth_even_with_shards_in_strict_mode(self) -> None:
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        shard_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"shard",
        )

        with mock.patch(
            "ethernity.cli.features.recover.planning._inspect_auth_payload",
            return_value=(None, "missing", ()),
        ) as inspect_auth_mock:
            with mock.patch(
                "ethernity.cli.features.recover.planning._inspect_unlock_status",
                return_value=mock.Mock(
                    satisfied=False,
                    resolved_passphrase=None,
                    blocking_issues=(),
                ),
            ):
                inspect_recovery_inputs(
                    frames=[main_frame],
                    extra_auth_frames=[],
                    shard_frames=[shard_frame],
                    passphrase=None,
                    allow_unsigned=False,
                    input_label=None,
                    input_detail=None,
                    shard_fallback_files=[],
                    shard_payloads_file=[],
                    shard_scan=[],
                    quiet=True,
                )

        self.assertTrue(inspect_auth_mock.call_args.kwargs["require_auth"])


if __name__ == "__main__":
    unittest.main()
