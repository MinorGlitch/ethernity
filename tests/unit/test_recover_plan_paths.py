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

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.cli.features.recover import planning as recover_plan
from ethernity.cli.shared.types import RecoverArgs


def _home_env(home: Path) -> dict[str, str]:
    env = {"HOME": str(home), "USERPROFILE": str(home)}
    drive, tail = os.path.splitdrive(str(home))
    if drive:
        env["HOMEDRIVE"] = drive
        env["HOMEPATH"] = tail or "\\"
    return env


class TestRecoverPlanPathNormalization(unittest.TestCase):
    def test_frames_from_args_expands_user_paths(self) -> None:
        args = RecoverArgs(fallback_file="~/recovery.txt")
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", _home_env(home), clear=False):
                with mock.patch.object(
                    recover_plan,
                    "_frames_from_fallback",
                    return_value=["frame"],
                ) as fallback_mock:
                    frames, label, detail = recover_plan._frames_from_args(
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
            quiet=True,
        )

    def test_frames_from_args_scan_filters_out_shard_documents(self) -> None:
        args = RecoverArgs(scan=["~/backup-dir"])
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", _home_env(home), clear=False):
                with mock.patch.object(
                    recover_plan,
                    "_recovery_frames_from_scan",
                    return_value=["main", "auth"],
                ) as scan_mock:
                    frames, label, detail = recover_plan._frames_from_args(
                        args,
                        allow_unsigned=False,
                        quiet=True,
                    )
        self.assertEqual(frames, ["main", "auth"])
        self.assertEqual(label, "Scan")
        self.assertEqual(detail, str(home / "backup-dir"))
        scan_mock.assert_called_once_with([str(home / "backup-dir")], quiet=True)

    def test_shard_and_auth_path_helpers_expand_user_paths(self) -> None:
        args = RecoverArgs(
            auth_fallback_file="~/auth.txt",
            shard_fallback_file=["~/s1.txt"],
            shard_payloads_file=["~/s2.txt"],
            shard_scan=["~/s3.pdf"],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", _home_env(home), clear=False):
                with mock.patch.object(
                    recover_plan,
                    "_auth_frames_from_fallback",
                    return_value=["auth"],
                ) as auth_mock:
                    auth_frames = recover_plan._extra_auth_frames_from_args(
                        args,
                        allow_unsigned=False,
                        quiet=True,
                    )
                with mock.patch.object(
                    recover_plan,
                    "_frames_from_shard_inputs",
                    return_value=["shard"],
                ) as shard_mock:
                    with mock.patch.object(
                        recover_plan,
                        "_shard_frames_from_scan",
                        return_value=["scan-shard"],
                    ) as shard_scan_mock:
                        shard_frames, shard_fallback, shard_payloads, shard_scan = (
                            recover_plan._shard_frames_from_args(
                                args,
                                quiet=True,
                            )
                        )
        self.assertEqual(auth_frames, ["auth"])
        auth_mock.assert_called_once_with(
            str(home / "auth.txt"), allow_invalid_auth=False, quiet=True
        )
        self.assertEqual(shard_frames, ["shard", "scan-shard"])
        self.assertEqual(shard_fallback, [str(home / "s1.txt")])
        self.assertEqual(shard_payloads, [str(home / "s2.txt")])
        self.assertEqual(shard_scan, [str(home / "s3.pdf")])
        shard_mock.assert_called_once_with(
            [str(home / "s1.txt")],
            [str(home / "s2.txt")],
            quiet=True,
        )
        shard_scan_mock.assert_called_once_with([str(home / "s3.pdf")], quiet=True)

    def test_plan_from_args_expands_output_path(self) -> None:
        args = RecoverArgs(output="~/recovered")
        fake_plan = object()
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", _home_env(home), clear=False):
                with mock.patch.object(recover_plan, "validate_recover_args"):
                    with mock.patch.object(recover_plan, "resolve_recover_config"):
                        with mock.patch.object(
                            recover_plan,
                            "_frames_from_args",
                            return_value=(["main"], "QR payloads", "input"),
                        ):
                            with mock.patch.object(
                                recover_plan,
                                "_extra_auth_frames_from_args",
                                return_value=[],
                            ):
                                with mock.patch.object(
                                    recover_plan,
                                    "_shard_frames_from_args",
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
