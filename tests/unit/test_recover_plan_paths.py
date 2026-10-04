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

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.encoding.framing import Frame, FrameType
from ethernity.workflows.recovery import inputs as recover_inputs, planning as recover_plan
from ethernity.workflows.recovery.frame_inputs import FrameInputResult
from ethernity.workflows.shared.operation_types import RecoverArgs
from tests.support.environment import home_environment


class TestRecoverPlanPathNormalization(unittest.TestCase):
    def test_frames_from_args_expands_user_paths(self) -> None:
        args = RecoverArgs(fallback_file="~/recovery.txt")
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", home_environment(home), clear=False):
                with mock.patch.object(
                    recover_inputs.frame_inputs,
                    "frames_from_fallback",
                    return_value=FrameInputResult(frames=("frame",)),
                ) as fallback_mock:
                    frames, label, detail = recover_inputs.load_recovery_frames(
                        args,
                        allow_unsigned=False,
                        quiet=True,
                    )
        self.assertEqual(frames, ["frame"])
        self.assertEqual(label, "Recovery text")
        self.assertEqual(detail, str(home / "recovery.txt"))
        fallback_mock.assert_called_once_with(
            str(home / "recovery.txt"),
            allow_invalid_auth=False,
            notice_sink=mock.ANY,
        )

    def test_frames_from_args_scan_filters_out_shard_documents(self) -> None:
        args = RecoverArgs(scan=["~/backup-dir"])
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", home_environment(home), clear=False):
                with mock.patch.object(
                    recover_inputs.frame_inputs,
                    "recovery_frames_from_scan",
                    return_value=FrameInputResult(frames=("main", "auth")),
                ) as scan_mock:
                    frames, label, detail = recover_inputs.load_recovery_frames(
                        args,
                        allow_unsigned=False,
                        quiet=True,
                    )
        self.assertEqual(frames, ["main", "auth"])
        self.assertEqual(label, "Backup PDF or images")
        self.assertEqual(detail, str(home / "backup-dir"))
        scan_mock.assert_called_once_with(
            [str(home / "backup-dir")],
            notice_sink=mock.ANY,
        )

    def test_frames_from_args_root_selection_does_not_change_scan_inputs(self) -> None:
        args = RecoverArgs(scan=["~/backup-dir"], extension_index=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", home_environment(home), clear=False):
                with mock.patch.object(
                    recover_inputs.frame_inputs,
                    "recovery_frames_from_scan",
                    return_value=FrameInputResult(frames=("root-main", "root-auth")),
                ) as scan_mock:
                    frames, label, detail = recover_inputs.load_recovery_frames(
                        args,
                        allow_unsigned=False,
                        quiet=True,
                    )

        self.assertEqual(frames, ["root-main", "root-auth"])
        self.assertEqual(label, "Backup PDF or images")
        self.assertEqual(detail, str(home / "backup-dir"))
        scan_mock.assert_called_once_with(
            [str(home / "backup-dir")],
            notice_sink=mock.ANY,
        )

    def test_frames_from_args_can_mix_scan_with_fallback_text(self) -> None:
        args = RecoverArgs(fallback_file="~/extension.txt", scan=["~/root.pdf"])
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", home_environment(home), clear=False):
                with mock.patch.object(
                    recover_inputs.frame_inputs,
                    "frames_from_fallback",
                    return_value=FrameInputResult(frames=("extension-main", "extension-auth")),
                ) as fallback_mock:
                    with mock.patch.object(
                        recover_inputs.frame_inputs,
                        "recovery_frames_from_scan",
                        return_value=FrameInputResult(frames=("root-main", "root-auth")),
                    ) as scan_mock:
                        frames, label, detail = recover_inputs.load_recovery_frames(
                            args,
                            allow_unsigned=False,
                            quiet=True,
                        )
        self.assertEqual(frames, ["extension-main", "extension-auth", "root-main", "root-auth"])
        self.assertEqual(label, "Recovery inputs")
        self.assertEqual(
            detail,
            f"Recovery text: {home / 'extension.txt'}; Backup PDF or images: {home / 'root.pdf'}",
        )
        fallback_mock.assert_called_once_with(
            str(home / "extension.txt"),
            allow_invalid_auth=False,
            notice_sink=mock.ANY,
        )
        scan_mock.assert_called_once_with([str(home / "root.pdf")], notice_sink=mock.ANY)

    def test_shard_and_auth_paths_expand_user_paths(self) -> None:
        args = RecoverArgs(
            auth_fallback_file="~/auth.txt",
            shard_fallback_file=["~/s1.txt"],
            shard_payloads_file=["~/s2.txt"],
            shard_scan=["~/s3.pdf"],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", home_environment(home), clear=False):
                with mock.patch.object(
                    recover_inputs.frame_inputs,
                    "auth_frames_from_fallback",
                    return_value=FrameInputResult(frames=("auth",)),
                ) as auth_mock:
                    auth_frames = recover_inputs.load_extra_auth_frames(
                        args,
                        allow_unsigned=False,
                        quiet=True,
                    )
                with mock.patch.object(
                    recover_inputs.frame_inputs,
                    "frame_from_fallback",
                    return_value="shard",
                ) as shard_fallback_mock:
                    with mock.patch.object(
                        recover_inputs.frame_inputs,
                        "frames_from_payloads",
                        return_value=["payload-shard"],
                    ) as shard_payload_mock:
                        with mock.patch.object(
                            recover_inputs.frame_inputs,
                            "shard_frames_from_scan",
                            return_value=FrameInputResult(frames=("scan-shard",)),
                        ) as shard_scan_mock:
                            shard_frames, shard_fallback, shard_payloads, shard_scan = (
                                recover_inputs.load_shard_frames(
                                    args,
                                    quiet=True,
                                )
                            )
        self.assertEqual(auth_frames, ["auth"])
        auth_mock.assert_called_once_with(
            str(home / "auth.txt"), allow_invalid_auth=False, notice_sink=mock.ANY
        )
        self.assertEqual(shard_frames, ["shard", "payload-shard", "scan-shard"])
        self.assertEqual(shard_fallback, [str(home / "s1.txt")])
        self.assertEqual(shard_payloads, [str(home / "s2.txt")])
        self.assertEqual(shard_scan, [str(home / "s3.pdf")])
        shard_fallback_mock.assert_called_once_with(str(home / "s1.txt"))
        shard_payload_mock.assert_called_once_with(
            str(home / "s2.txt"),
            label="shard text lines",
        )
        shard_scan_mock.assert_called_once_with(
            [str(home / "s3.pdf")],
            notice_sink=mock.ANY,
        )

    def test_shard_and_auth_loading_preserves_preloaded_frames(self) -> None:
        auth_frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=b"\x11" * 16,
            index=0,
            total=1,
            data=b"auth",
        )
        shard_frame = Frame(
            version=1,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x22" * 16,
            index=0,
            total=1,
            data=b"shard",
        )
        args = RecoverArgs(
            auth_frames=[auth_frame],
            shard_frames=[shard_frame],
        )

        auth_frames = recover_inputs.load_extra_auth_frames(
            args,
            allow_unsigned=False,
            quiet=True,
        )
        shard_frames, shard_fallback, shard_payloads, shard_scan = recover_inputs.load_shard_frames(
            args,
            quiet=True,
        )

        self.assertEqual(auth_frames, [auth_frame])
        self.assertEqual(shard_frames, [shard_frame])
        self.assertEqual(shard_fallback, [])
        self.assertEqual(shard_payloads, [])
        self.assertEqual(shard_scan, [])

    def test_plan_from_args_expands_output_path(self) -> None:
        args = RecoverArgs(output="~/recovered")
        fake_plan = object()
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", home_environment(home), clear=False):
                with mock.patch.object(recover_plan, "validate_recover_args"):
                    with mock.patch.object(recover_plan, "resolve_recover_config"):
                        with mock.patch.object(
                            recover_inputs,
                            "load_recovery_frames",
                            return_value=(["main"], "QR payloads", "input"),
                        ):
                            with mock.patch.object(
                                recover_inputs,
                                "load_extra_auth_frames",
                                return_value=[],
                            ):
                                with mock.patch.object(
                                    recover_inputs,
                                    "load_shard_frames",
                                    return_value=([], [], [], []),
                                ):
                                    with mock.patch.object(
                                        recover_plan,
                                        "build_recovery_plan",
                                        return_value=fake_plan,
                                    ) as build_mock:
                                        plan = recover_plan.plan_from_args(args)
        self.assertIs(plan, fake_plan)
        self.assertEqual(build_mock.call_args.kwargs["output_path"], str(home / "recovered"))


if __name__ == "__main__":
    unittest.main()
