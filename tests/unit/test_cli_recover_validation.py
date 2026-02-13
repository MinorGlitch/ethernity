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

import argparse
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from typer.testing import CliRunner

from ethernity import cli
from ethernity.cli.core.types import RecoverArgs
from ethernity.cli.flows import recover_wizard as recover_wizard_module
from ethernity.cli.flows.recover import run_recover_command
from ethernity.cli.flows.recover_plan import _resolve_passphrase
from ethernity.cli.io.frames import _frames_from_fallback
from ethernity.config.installer import DEFAULT_CONFIG_PATH
from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType, encode_frame
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.render.fallback_text import format_zbase32_lines
from tests.test_support import suppress_output


class TestCliRecoverValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_invalid_mnemonic_checksum_rejected(self) -> None:
        passphrase = " ".join(
            [
                "abandon",
                "abandon",
                "abandon",
                "abandon",
                "abandon",
                "abandon",
                "abandon",
                "abandon",
                "abandon",
                "abandon",
                "abandon",
                "above",
            ]
        )
        with self.assertRaises(ValueError) as ctx:
            _resolve_passphrase(
                passphrase=passphrase,
                shard_frames=[],
                doc_id=b"\x00" * DOC_ID_LEN,
                doc_hash=b"\x00" * 32,
                sign_pub=None,
                allow_unsigned=False,
                args=None,
            )
        self.assertIn("mnemonic", str(ctx.exception).lower())

    def test_conflicting_input_combinations(self) -> None:
        cases = (
            {
                "name": "fallback-with-payloads",
                "fallback_file": "fallback.txt",
                "payloads_file": "frames.txt",
                "scan": [],
            },
            {
                "name": "scan-with-fallback",
                "fallback_file": "fallback.txt",
                "payloads_file": None,
                "scan": ["scan.png"],
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                args = argparse.Namespace(
                    fallback_file=case["fallback_file"],
                    payloads_file=case["payloads_file"],
                    scan=case["scan"],
                    passphrase="pass",
                    shard_fallback_file=[],
                    auth_fallback_file=None,
                    auth_payloads_file=None,
                    shard_payloads_file=[],
                    output=None,
                    allow_unsigned=False,
                    assume_yes=True,
                    quiet=True,
                )
                with self.assertRaises(ValueError):
                    cli.run_recover_command(args)

    def test_labeled_fallback_sections_parse(self) -> None:
        doc_id = b"\x10" * DOC_ID_LEN
        auth_frame = Frame(
            version=1,
            frame_type=FrameType.AUTH,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"auth-payload",
        )
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        auth_lines = format_zbase32_lines(
            encode_zbase32(encode_frame(auth_frame)),
            group_size=4,
            line_length=80,
            line_count=None,
        )
        main_lines = format_zbase32_lines(
            encode_zbase32(encode_frame(main_frame)),
            group_size=4,
            line_length=80,
            line_count=None,
        )
        lines = [
            cli.AUTH_FALLBACK_LABEL,
            *auth_lines,
            "",
            cli.MAIN_FALLBACK_LABEL,
            *main_lines,
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fallback.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            frames = _frames_from_fallback(
                str(path),
                allow_invalid_auth=False,
                quiet=True,
            )
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].frame_type, FrameType.MAIN_DOCUMENT)
        self.assertEqual(frames[0].data, main_frame.data)
        self.assertEqual(frames[1].frame_type, FrameType.AUTH)
        self.assertEqual(frames[1].data, auth_frame.data)

    def test_labeled_fallback_missing_auth_section(self) -> None:
        doc_id = b"\x20" * DOC_ID_LEN
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        main_lines = format_zbase32_lines(
            encode_zbase32(encode_frame(main_frame)),
            group_size=4,
            line_length=80,
            line_count=None,
        )
        lines = [cli.MAIN_FALLBACK_LABEL, *main_lines]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fallback.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            frames = _frames_from_fallback(
                str(path),
                allow_invalid_auth=False,
                quiet=True,
            )
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].frame_type, FrameType.MAIN_DOCUMENT)
        self.assertEqual(frames[0].data, main_frame.data)

    def test_fallback_rejects_line_bound_overflow(self) -> None:
        lines = ["ybndr", "fghej", "kmcpq"]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fallback.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            with mock.patch("ethernity.cli.io.fallback_parser.MAX_FALLBACK_LINES", 2):
                with self.assertRaisesRegex(ValueError, "MAX_FALLBACK_LINES"):
                    _frames_from_fallback(
                        str(path),
                        allow_invalid_auth=False,
                        quiet=True,
                    )

    def test_labeled_fallback_invalid_auth_strict(self) -> None:
        doc_id = b"\x30" * DOC_ID_LEN
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        main_lines = format_zbase32_lines(
            encode_zbase32(encode_frame(main_frame)),
            group_size=4,
            line_length=80,
            line_count=None,
        )
        lines = [
            cli.AUTH_FALLBACK_LABEL,
            "not-a-valid-line!",
            "",
            cli.MAIN_FALLBACK_LABEL,
            *main_lines,
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fallback.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            with suppress_output():
                with self.assertRaises(ValueError):
                    _frames_from_fallback(
                        str(path),
                        allow_invalid_auth=False,
                        quiet=True,
                    )

    def test_labeled_fallback_invalid_auth_allowed(self) -> None:
        doc_id = b"\x40" * DOC_ID_LEN
        main_frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=doc_id,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        main_lines = format_zbase32_lines(
            encode_zbase32(encode_frame(main_frame)),
            group_size=4,
            line_length=80,
            line_count=None,
        )
        lines = [
            cli.AUTH_FALLBACK_LABEL,
            "not-a-valid-line!",
            "",
            cli.MAIN_FALLBACK_LABEL,
            *main_lines,
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fallback.txt"
            path.write_text("\n".join(lines), encoding="utf-8")
            with suppress_output():
                frames = _frames_from_fallback(
                    str(path),
                    allow_invalid_auth=True,
                    quiet=True,
                )
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].frame_type, FrameType.MAIN_DOCUMENT)

    def test_recover_empty_stdin_non_tty_shows_input_guidance(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["recover", "--config", str(DEFAULT_CONFIG_PATH)],
                input="",
            )
        self.assertEqual(result.exit_code, 2)
        self.assertIn("--fallback-file", result.output)
        self.assertIn("--payloads-file", result.output)
        self.assertIn("--scan", result.output)

    def test_recover_non_tty_non_empty_stdin_auto_selects_fallback_mode(self) -> None:
        captured: dict[str, str | None] = {}

        def _capture_args(args: RecoverArgs, *, debug: bool = False) -> int:
            self.assertFalse(debug)
            captured["fallback_file"] = args.fallback_file
            return 0

        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.commands.recover.run_recover_command",
                side_effect=_capture_args,
            ):
                result = self.runner.invoke(cli.app, ["recover"], input="payload")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured.get("fallback_file"), "-")

    def test_recover_rescue_mode_flag_sets_allow_unsigned(self) -> None:
        captured: dict[str, bool] = {}

        def _capture_args(args: RecoverArgs, *, debug: bool = False) -> int:
            self.assertFalse(debug)
            captured["allow_unsigned"] = args.allow_unsigned
            return 0

        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.commands.recover.run_recover_command",
                side_effect=_capture_args,
            ):
                result = self.runner.invoke(
                    cli.app,
                    ["recover", "--fallback-file", "fallback.txt", "--rescue-mode"],
                )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(captured.get("allow_unsigned"))

    def test_recover_skip_auth_check_alias_sets_allow_unsigned(self) -> None:
        captured: dict[str, bool] = {}

        def _capture_args(args: RecoverArgs, *, debug: bool = False) -> int:
            self.assertFalse(debug)
            captured["allow_unsigned"] = args.allow_unsigned
            return 0

        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.commands.recover.run_recover_command",
                side_effect=_capture_args,
            ):
                result = self.runner.invoke(
                    cli.app,
                    ["recover", "--fallback-file", "fallback.txt", "--skip-auth-check"],
                )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(captured.get("allow_unsigned"))

    def test_recover_skip_auth_warning_not_emitted_before_input_validation(self) -> None:
        args = RecoverArgs(allow_unsigned=True, quiet=False)
        with mock.patch("ethernity.cli.flows.recover._warn") as warn_mock:
            with self.assertRaises(ValueError):
                run_recover_command(args)
        warn_mock.assert_not_called()

    def test_recover_skip_auth_warning_emitted_after_successful_plan(self) -> None:
        events: list[str] = []
        fake_plan = SimpleNamespace(allow_unsigned=True)

        def _fake_plan_from_args(_args: RecoverArgs):
            events.append("plan")
            return fake_plan

        def _fake_warn(_message: str, *, quiet: bool) -> None:
            self.assertFalse(quiet)
            events.append("warn")

        def _fake_run_recover_plan(
            _plan,
            *,
            quiet: bool,
            debug: bool = False,
            debug_max_bytes: int = 0,
            debug_reveal_secrets: bool = False,
        ) -> int:
            self.assertFalse(quiet)
            self.assertFalse(debug)
            self.assertEqual(debug_max_bytes, 0)
            self.assertFalse(debug_reveal_secrets)
            events.append("run")
            return 0

        with mock.patch(
            "ethernity.cli.flows.recover.plan_from_args",
            side_effect=_fake_plan_from_args,
        ):
            with mock.patch(
                "ethernity.cli.flows.recover._warn",
                side_effect=_fake_warn,
            ):
                with mock.patch(
                    "ethernity.cli.flows.recover.run_recover_plan",
                    side_effect=_fake_run_recover_plan,
                ):
                    result = run_recover_command(RecoverArgs(allow_unsigned=True, quiet=False))
        self.assertEqual(result, 0)
        self.assertEqual(events, ["plan", "warn", "run"])

    def test_recover_review_cancel_returns_code_1(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x55" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        plan = SimpleNamespace(
            shard_frames=(),
            auth_status="verified",
            allow_unsigned=False,
            input_label="Recovery text",
            input_detail="stdin",
            main_frames=(frame,),
            auth_frames=(),
            doc_id=b"\x55" * DOC_ID_LEN,
        )
        args = RecoverArgs(quiet=False, assume_yes=False)
        with mock.patch(
            "ethernity.cli.flows.recover_wizard.sys.stdin.isatty",
            return_value=True,
        ):
            with mock.patch(
                "ethernity.cli.flows.recover_wizard.sys.stdout.isatty",
                return_value=True,
            ):
                with mock.patch(
                    "ethernity.cli.flows.recover_wizard.resolve_recover_config",
                    return_value=(object(), "base64"),
                ):
                    with mock.patch(
                        "ethernity.cli.flows.recover_wizard._prompt_recovery_input",
                        return_value=([frame], "Recovery text", "stdin"),
                    ):
                        with mock.patch(
                            "ethernity.cli.flows.recover_wizard._load_extra_auth_frames",
                            return_value=[],
                        ):
                            with mock.patch(
                                "ethernity.cli.flows.recover_wizard._prompt_key_material",
                                return_value=("passphrase", [], [], []),
                            ):
                                with mock.patch(
                                    "ethernity.cli.flows.recover_wizard._load_shard_frames",
                                    return_value=[],
                                ):
                                    with mock.patch(
                                        "ethernity.cli.flows.recover_wizard.build_recovery_plan",
                                        return_value=plan,
                                    ):
                                        with mock.patch(
                                            "ethernity.cli.flows.recover_wizard._build_recovery_review_rows",
                                            return_value=[("Inputs", None)],
                                        ):
                                            with mock.patch(
                                                "ethernity.cli.flows.recover_wizard.prompt_yes_no",
                                                return_value=False,
                                            ):
                                                with mock.patch(
                                                    "ethernity.cli.flows.recover_wizard.console.print"
                                                ) as print_mock:
                                                    run_wizard = (
                                                        recover_wizard_module.run_recover_wizard
                                                    )
                                                    result = run_wizard(
                                                        args=args,
                                                        show_header=False,
                                                    )
        self.assertEqual(result, 1)
        self.assertIn(mock.call("Recovery cancelled."), print_mock.mock_calls)


if __name__ == "__main__":
    unittest.main()
