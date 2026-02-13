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

import contextlib
import unittest
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.core.types import RecoverArgs
from ethernity.cli.flows import recover_wizard as wizard
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType


def _frame(frame_type: FrameType, *, doc_id: bytes | None = None, data: bytes = b"x") -> Frame:
    return Frame(
        version=VERSION,
        frame_type=frame_type,
        doc_id=doc_id or (b"\x11" * DOC_ID_LEN),
        index=0,
        total=1,
        data=data,
    )


class TestPromptRecoveryInput(unittest.TestCase):
    @mock.patch("ethernity.cli.flows.recover_wizard.collect_fallback_frames")
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdin.isatty", return_value=True)
    def test_fallback_stdin_interactive_collects_lines(
        self,
        _stdin_tty: mock.MagicMock,
        collect_fallback_frames: mock.MagicMock,
    ) -> None:
        main = _frame(FrameType.MAIN_DOCUMENT)
        collect_fallback_frames.return_value = [main]

        frames, label, detail = wizard._prompt_recovery_input(
            RecoverArgs(fallback_file="-"),
            allow_unsigned=False,
            quiet=True,
        )

        self.assertEqual(frames, [main])
        self.assertEqual(label, "Recovery text")
        self.assertEqual(detail, "stdin")
        collect_fallback_frames.assert_called_once_with(
            allow_unsigned=False,
            quiet=True,
            initial_lines=None,
        )

    @mock.patch("ethernity.cli.flows.recover_wizard._frames_from_fallback")
    @mock.patch(
        "ethernity.cli.flows.recover_wizard.status", return_value=contextlib.nullcontext(None)
    )
    def test_fallback_file_reads_frames(
        self,
        _status: mock.MagicMock,
        frames_from_fallback: mock.MagicMock,
    ) -> None:
        main = _frame(FrameType.MAIN_DOCUMENT)
        frames_from_fallback.return_value = [main]

        frames, label, detail = wizard._prompt_recovery_input(
            RecoverArgs(fallback_file="recovery.txt"),
            allow_unsigned=True,
            quiet=False,
        )

        self.assertEqual(frames, [main])
        self.assertEqual((label, detail), ("Recovery text", "recovery.txt"))
        frames_from_fallback.assert_called_once_with(
            "recovery.txt",
            allow_invalid_auth=True,
            quiet=False,
        )

    @mock.patch(
        "ethernity.cli.flows.recover_wizard._frames_from_fallback",
        side_effect=ValueError("bad magic"),
    )
    @mock.patch(
        "ethernity.cli.flows.recover_wizard.status", return_value=contextlib.nullcontext(None)
    )
    def test_fallback_file_wraps_parse_errors(
        self,
        _status: mock.MagicMock,
        _frames_from_fallback: mock.MagicMock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "Recovery text is incomplete or invalid"):
            wizard._prompt_recovery_input(
                RecoverArgs(fallback_file="recovery.txt"),
                allow_unsigned=False,
                quiet=True,
            )

    @mock.patch("ethernity.cli.flows.recover_wizard.collect_payload_frames")
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdin.isatty", return_value=True)
    def test_payload_stdin_interactive_collects_payloads(
        self,
        _stdin_tty: mock.MagicMock,
        collect_payload_frames: mock.MagicMock,
    ) -> None:
        main = _frame(FrameType.MAIN_DOCUMENT)
        collect_payload_frames.return_value = [main]

        frames, label, detail = wizard._prompt_recovery_input(
            RecoverArgs(payloads_file="-"),
            allow_unsigned=True,
            quiet=False,
        )

        self.assertEqual(frames, [main])
        self.assertEqual((label, detail), ("QR payloads", "stdin"))
        collect_payload_frames.assert_called_once_with(allow_unsigned=True, quiet=False)

    @mock.patch("ethernity.cli.flows.recover_wizard._frames_from_payloads")
    @mock.patch(
        "ethernity.cli.flows.recover_wizard.status", return_value=contextlib.nullcontext(None)
    )
    def test_payload_file_reads_frames(
        self,
        _status: mock.MagicMock,
        frames_from_payloads: mock.MagicMock,
    ) -> None:
        main = _frame(FrameType.MAIN_DOCUMENT)
        frames_from_payloads.return_value = [main]

        frames, label, detail = wizard._prompt_recovery_input(
            RecoverArgs(payloads_file="payloads.txt"),
            allow_unsigned=False,
            quiet=False,
        )

        self.assertEqual(frames, [main])
        self.assertEqual((label, detail), ("QR payloads", "payloads.txt"))
        frames_from_payloads.assert_called_once_with("payloads.txt", label="frame")

    @mock.patch("ethernity.cli.flows.recover_wizard._frames_from_scan")
    @mock.patch(
        "ethernity.cli.flows.recover_wizard.status", return_value=contextlib.nullcontext(None)
    )
    def test_scan_path_reads_frames(
        self,
        _status: mock.MagicMock,
        frames_from_scan: mock.MagicMock,
    ) -> None:
        main = _frame(FrameType.MAIN_DOCUMENT)
        frames_from_scan.return_value = [main]

        frames, label, detail = wizard._prompt_recovery_input(
            RecoverArgs(scan=["a.png", "b.png"]),
            allow_unsigned=False,
            quiet=False,
        )

        self.assertEqual(frames, [main])
        self.assertEqual((label, detail), ("Scan", "a.png, b.png"))
        frames_from_scan.assert_called_once_with(["a.png", "b.png"])

    @mock.patch("ethernity.cli.flows.recover_wizard.prompt_recovery_input_interactive")
    def test_interactive_prompt_fallback_when_no_input_flags(
        self,
        prompt_recovery_input_interactive: mock.MagicMock,
    ) -> None:
        main = _frame(FrameType.MAIN_DOCUMENT)
        prompt_recovery_input_interactive.return_value = ([main], "Recovery text", "stdin")

        frames, label, detail = wizard._prompt_recovery_input(
            RecoverArgs(),
            allow_unsigned=True,
            quiet=True,
        )

        self.assertEqual(frames, [main])
        self.assertEqual((label, detail), ("Recovery text", "stdin"))
        prompt_recovery_input_interactive.assert_called_once_with(allow_unsigned=True, quiet=True)


class TestPromptKeyMaterial(unittest.TestCase):
    def test_pre_supplied_passphrase_is_preserved(self) -> None:
        result = wizard._prompt_key_material(
            RecoverArgs(passphrase="secret"),
            quiet=True,
        )
        self.assertEqual(result, ("secret", [], [], []))

    @mock.patch(
        "ethernity.cli.flows.recover_wizard.prompt_required_secret", return_value="entered-pass"
    )
    @mock.patch("ethernity.cli.flows.recover_wizard.prompt_choice", return_value="passphrase")
    def test_prompt_choice_passphrase_branch(
        self,
        prompt_choice: mock.MagicMock,
        prompt_required_secret: mock.MagicMock,
    ) -> None:
        result = wizard._prompt_key_material(RecoverArgs(), quiet=False)
        self.assertEqual(result, ("entered-pass", [], [], []))
        prompt_choice.assert_called_once()
        prompt_required_secret.assert_called_once()

    @mock.patch("ethernity.cli.flows.recover_wizard._prompt_shard_inputs")
    @mock.patch("ethernity.cli.flows.recover_wizard.prompt_choice", return_value="shards")
    def test_prompt_choice_shards_branch(
        self,
        prompt_choice: mock.MagicMock,
        prompt_shard_inputs: mock.MagicMock,
    ) -> None:
        shard = _frame(FrameType.KEY_DOCUMENT)
        prompt_shard_inputs.return_value = (["shards.txt"], ["shards.payload"], [shard])

        result = wizard._prompt_key_material(RecoverArgs(), quiet=True)

        self.assertEqual(result, (None, ["shards.txt"], ["shards.payload"], [shard]))
        prompt_choice.assert_called_once()
        prompt_shard_inputs.assert_called_once_with(quiet=True)


class TestRecoveryWizardHelpers(unittest.TestCase):
    def test_build_review_rows_sharded_allow_unsigned(self) -> None:
        plan = SimpleNamespace(
            shard_frames=(_frame(FrameType.KEY_DOCUMENT),),
            auth_status="missing",
            allow_unsigned=True,
            input_label="Scan",
            input_detail="a.png",
            main_frames=(_frame(FrameType.MAIN_DOCUMENT), _frame(FrameType.MAIN_DOCUMENT)),
            auth_frames=(),
            shard_fallback_files=("a.txt",),
            shard_payloads_file=("b.txt",),
        )

        rows = wizard._build_recovery_review_rows(plan, RecoverArgs(output="out-dir"))
        self.assertIn(("Key material", "shard documents"), rows)
        self.assertIn(("Allow unsigned", "yes"), rows)
        self.assertIn(("Input source", "Scan: a.png"), rows)
        self.assertIn(("Main QR payloads", "2"), rows)
        self.assertIn(("Auth QR payloads", "none"), rows)

    def test_build_review_rows_passphrase_defaults(self) -> None:
        plan = SimpleNamespace(
            shard_frames=(),
            auth_status="verified",
            allow_unsigned=False,
            input_label=None,
            input_detail=None,
            main_frames=(_frame(FrameType.MAIN_DOCUMENT),),
            auth_frames=(_frame(FrameType.AUTH),),
            shard_fallback_files=(),
            shard_payloads_file=(),
        )

        rows = wizard._build_recovery_review_rows(plan, RecoverArgs(output=None))
        self.assertIn(("Key material", "passphrase"), rows)
        self.assertIn(("Output target", "prompt after recovery"), rows)
        self.assertIn(("Auth QR payloads", "1"), rows)

    @mock.patch("ethernity.cli.flows.recover_wizard._auth_frames_from_payloads")
    @mock.patch("ethernity.cli.flows.recover_wizard._auth_frames_from_fallback")
    def test_load_extra_auth_frames_combines_sources(
        self,
        auth_frames_from_fallback: mock.MagicMock,
        auth_frames_from_payloads: mock.MagicMock,
    ) -> None:
        auth_a = _frame(FrameType.AUTH, doc_id=b"\x22" * DOC_ID_LEN)
        auth_b = _frame(FrameType.AUTH, doc_id=b"\x22" * DOC_ID_LEN, data=b"b")
        auth_frames_from_fallback.return_value = [auth_a]
        auth_frames_from_payloads.return_value = [auth_b]

        frames = wizard._load_extra_auth_frames(
            RecoverArgs(auth_fallback_file="auth.txt", auth_payloads_file="auth.payload"),
            allow_unsigned=False,
            quiet=True,
        )

        self.assertEqual(frames, [auth_a, auth_b])

    @mock.patch(
        "ethernity.cli.flows.recover_wizard._auth_frames_from_fallback",
        side_effect=ValueError("bad magic"),
    )
    def test_load_extra_auth_frames_wraps_fallback_errors(
        self,
        _auth_frames_from_fallback: mock.MagicMock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "Auth recovery text is incomplete or invalid"):
            wizard._load_extra_auth_frames(
                RecoverArgs(auth_fallback_file="auth.txt"),
                allow_unsigned=False,
                quiet=True,
            )

    def test_load_shard_frames_returns_empty_when_nothing_supplied(self) -> None:
        self.assertEqual(wizard._load_shard_frames([], [], extra_frames=None, quiet=True), [])

    @mock.patch("ethernity.cli.flows.recover_wizard._frames_from_shard_inputs")
    @mock.patch(
        "ethernity.cli.flows.recover_wizard.status", return_value=contextlib.nullcontext(None)
    )
    def test_load_shard_frames_reads_from_files(
        self,
        _status: mock.MagicMock,
        frames_from_shard_inputs: mock.MagicMock,
    ) -> None:
        shard = _frame(FrameType.KEY_DOCUMENT)
        frames_from_shard_inputs.return_value = [shard]

        frames = wizard._load_shard_frames(["shards.txt"], [], extra_frames=[], quiet=False)

        self.assertEqual(frames, [shard])
        frames_from_shard_inputs.assert_called_once_with(["shards.txt"], [])

    @mock.patch(
        "ethernity.cli.flows.recover_wizard._frames_from_shard_inputs",
        side_effect=ValueError("bad magic"),
    )
    @mock.patch(
        "ethernity.cli.flows.recover_wizard.status", return_value=contextlib.nullcontext(None)
    )
    def test_load_shard_frames_wraps_parse_errors(
        self,
        _status: mock.MagicMock,
        _frames_from_shard_inputs: mock.MagicMock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "Shard recovery text is incomplete or invalid"):
            wizard._load_shard_frames(["shards.txt"], [], extra_frames=None, quiet=True)

    @mock.patch("ethernity.cli.flows.recover_wizard._frames_from_shard_inputs", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.recover_wizard.status", return_value=contextlib.nullcontext(None)
    )
    def test_load_shard_frames_rejects_empty_result(
        self,
        _status: mock.MagicMock,
        _frames_from_shard_inputs: mock.MagicMock,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "No valid shard data found"):
            wizard._load_shard_frames(["shards.txt"], [], extra_frames=[], quiet=True)


class TestRunRecoverWizard(unittest.TestCase):
    @mock.patch("ethernity.cli.flows.recover_wizard.write_plan_outputs", return_value=0)
    @mock.patch("ethernity.cli.flows.recover_wizard.plan_from_args")
    @mock.patch("ethernity.cli.flows.recover_wizard._warn")
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdout.isatty", return_value=False)
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdin.isatty", return_value=False)
    def test_noninteractive_assigns_stdin_fallback_and_warns_unsigned(
        self,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        warn_mock: mock.MagicMock,
        plan_from_args: mock.MagicMock,
        write_plan_outputs: mock.MagicMock,
    ) -> None:
        args = RecoverArgs(allow_unsigned=True, quiet=False)
        plan = SimpleNamespace(allow_unsigned=True)
        plan_from_args.return_value = plan

        result = wizard.run_recover_wizard(args, debug=True)

        self.assertEqual(result, 0)
        self.assertEqual(args.fallback_file, "-")
        warn_mock.assert_called_once()
        write_plan_outputs.assert_called_once_with(plan, quiet=False, debug=True)

    @mock.patch("ethernity.cli.flows.recover_wizard.console.print")
    @mock.patch("ethernity.cli.flows.recover_wizard.prompt_yes_no", return_value=False)
    @mock.patch(
        "ethernity.cli.flows.recover_wizard._build_recovery_review_rows", return_value=[("A", "B")]
    )
    @mock.patch("ethernity.cli.flows.recover_wizard.build_recovery_plan")
    @mock.patch("ethernity.cli.flows.recover_wizard._load_shard_frames", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.recover_wizard._prompt_key_material", return_value=("pass", [], [], [])
    )
    @mock.patch("ethernity.cli.flows.recover_wizard._load_extra_auth_frames", return_value=[])
    @mock.patch("ethernity.cli.flows.recover_wizard._prompt_recovery_input")
    @mock.patch("ethernity.cli.flows.recover_wizard.resolve_recover_config")
    @mock.patch("ethernity.cli.flows.recover_wizard.validate_recover_args")
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdin.isatty", return_value=True)
    def test_interactive_review_cancel_returns_one(
        self,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _validate_recover_args: mock.MagicMock,
        _resolve_recover_config: mock.MagicMock,
        prompt_recovery_input: mock.MagicMock,
        _load_extra_auth_frames: mock.MagicMock,
        _prompt_key_material: mock.MagicMock,
        _load_shard_frames: mock.MagicMock,
        build_recovery_plan: mock.MagicMock,
        _build_recovery_review_rows: mock.MagicMock,
        _prompt_yes_no: mock.MagicMock,
        console_print: mock.MagicMock,
    ) -> None:
        main = _frame(FrameType.MAIN_DOCUMENT)
        prompt_recovery_input.return_value = ([main], "Recovery text", "stdin")
        build_recovery_plan.return_value = SimpleNamespace(
            allow_unsigned=False,
            shard_frames=(),
            auth_status="verified",
            input_label="Recovery text",
            input_detail="stdin",
            main_frames=(main,),
            auth_frames=(),
            doc_id=main.doc_id,
        )

        result = wizard.run_recover_wizard(
            RecoverArgs(quiet=False, assume_yes=False), show_header=False
        )

        self.assertEqual(result, 1)
        self.assertIn(mock.call("Recovery cancelled."), console_print.mock_calls)

    @mock.patch("ethernity.cli.flows.recover_wizard.write_recovered_outputs")
    @mock.patch("ethernity.cli.flows.recover_wizard._resolve_recover_output", return_value="out")
    @mock.patch("ethernity.cli.flows.recover_wizard.decrypt_manifest_and_extract")
    @mock.patch("ethernity.cli.flows.recover_wizard.prompt_yes_no", side_effect=[True, False])
    @mock.patch(
        "ethernity.cli.flows.recover_wizard._build_recovery_review_rows", return_value=[("A", "B")]
    )
    @mock.patch("ethernity.cli.flows.recover_wizard.build_recovery_plan")
    @mock.patch("ethernity.cli.flows.recover_wizard._load_shard_frames", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.recover_wizard._prompt_key_material", return_value=("pass", [], [], [])
    )
    @mock.patch("ethernity.cli.flows.recover_wizard._load_extra_auth_frames", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.recover_wizard._prompt_recovery_input",
        return_value=([_frame(FrameType.MAIN_DOCUMENT)], "Recovery text", "stdin"),
    )
    @mock.patch("ethernity.cli.flows.recover_wizard.resolve_recover_config")
    @mock.patch("ethernity.cli.flows.recover_wizard.validate_recover_args")
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdin.isatty", return_value=True)
    def test_interactive_output_cancel_returns_one(
        self,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _validate_recover_args: mock.MagicMock,
        _resolve_recover_config: mock.MagicMock,
        _prompt_recovery_input: mock.MagicMock,
        _load_extra_auth_frames: mock.MagicMock,
        _prompt_key_material: mock.MagicMock,
        _load_shard_frames: mock.MagicMock,
        build_recovery_plan: mock.MagicMock,
        _build_recovery_review_rows: mock.MagicMock,
        _prompt_yes_no: mock.MagicMock,
        decrypt_manifest_and_extract: mock.MagicMock,
        _resolve_recover_output: mock.MagicMock,
        write_recovered_outputs: mock.MagicMock,
    ) -> None:
        main = _frame(FrameType.MAIN_DOCUMENT)
        build_recovery_plan.return_value = SimpleNamespace(
            allow_unsigned=False,
            shard_frames=(),
            auth_status="verified",
            input_label="Recovery text",
            input_detail="stdin",
            main_frames=(main,),
            auth_frames=(),
            doc_id=main.doc_id,
        )
        decrypt_manifest_and_extract.return_value = (
            SimpleNamespace(input_origin="file", input_roots=()),
            [(SimpleNamespace(path="a.txt"), b"x")],
        )

        result = wizard.run_recover_wizard(
            RecoverArgs(quiet=False, assume_yes=False), show_header=False
        )

        self.assertEqual(result, 1)
        write_recovered_outputs.assert_not_called()

    @mock.patch("ethernity.cli.flows.recover_wizard.write_recovered_outputs")
    @mock.patch("ethernity.cli.flows.recover_wizard._resolve_recover_output", return_value="out")
    @mock.patch("ethernity.cli.flows.recover_wizard.decrypt_manifest_and_extract")
    @mock.patch("ethernity.cli.flows.recover_wizard.prompt_yes_no", side_effect=[True, True])
    @mock.patch(
        "ethernity.cli.flows.recover_wizard._build_recovery_review_rows", return_value=[("A", "B")]
    )
    @mock.patch("ethernity.cli.flows.recover_wizard.build_recovery_plan")
    @mock.patch("ethernity.cli.flows.recover_wizard._load_shard_frames", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.recover_wizard._prompt_key_material", return_value=("pass", [], [], [])
    )
    @mock.patch("ethernity.cli.flows.recover_wizard._load_extra_auth_frames", return_value=[])
    @mock.patch(
        "ethernity.cli.flows.recover_wizard._prompt_recovery_input",
        return_value=([_frame(FrameType.MAIN_DOCUMENT)], "Recovery text", "stdin"),
    )
    @mock.patch(
        "ethernity.cli.flows.recover_wizard.ui_screen_mode",
        return_value=contextlib.nullcontext(),
    )
    @mock.patch("ethernity.cli.flows.recover_wizard.resolve_recover_config")
    @mock.patch("ethernity.cli.flows.recover_wizard.validate_recover_args")
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.recover_wizard.sys.stdin.isatty", return_value=True)
    def test_interactive_success_writes_outputs(
        self,
        _stdin_tty: mock.MagicMock,
        _stdout_tty: mock.MagicMock,
        _validate_recover_args: mock.MagicMock,
        _resolve_recover_config: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_recovery_input: mock.MagicMock,
        _load_extra_auth_frames: mock.MagicMock,
        _prompt_key_material: mock.MagicMock,
        _load_shard_frames: mock.MagicMock,
        build_recovery_plan: mock.MagicMock,
        _build_recovery_review_rows: mock.MagicMock,
        _prompt_yes_no: mock.MagicMock,
        decrypt_manifest_and_extract: mock.MagicMock,
        _resolve_recover_output: mock.MagicMock,
        write_recovered_outputs: mock.MagicMock,
    ) -> None:
        main = _frame(FrameType.MAIN_DOCUMENT)
        plan = SimpleNamespace(
            allow_unsigned=False,
            shard_frames=(),
            auth_status="verified",
            input_label="Recovery text",
            input_detail="stdin",
            main_frames=(main,),
            auth_frames=(),
            doc_id=main.doc_id,
        )
        build_recovery_plan.return_value = plan
        extracted = [(SimpleNamespace(path="a.txt"), b"x")]
        decrypt_manifest_and_extract.return_value = (
            SimpleNamespace(input_origin="mixed", input_roots=("vault",)),
            extracted,
        )

        result = wizard.run_recover_wizard(
            RecoverArgs(quiet=False, assume_yes=False), show_header=False
        )

        self.assertEqual(result, 0)
        ui_screen_mode.assert_called_once_with(quiet=False)
        _resolve_recover_output.assert_called_once_with(
            extracted,
            None,
            interactive=True,
            doc_id=main.doc_id,
            input_origin="mixed",
            input_roots=("vault",),
        )
        write_recovered_outputs.assert_called_once_with(
            extracted,
            output_path="out",
            auth_status="verified",
            allow_unsigned=False,
            quiet=False,
        )


class TestWritePlanOutputs(unittest.TestCase):
    @mock.patch("ethernity.cli.flows.recover_wizard.write_recovered_outputs")
    @mock.patch("ethernity.cli.flows.recover_wizard.decrypt_and_extract")
    def test_write_plan_outputs_success(
        self,
        decrypt_and_extract: mock.MagicMock,
        write_recovered_outputs: mock.MagicMock,
    ) -> None:
        plan = SimpleNamespace(output_path="out", auth_status="verified", allow_unsigned=False)
        extracted = [(SimpleNamespace(path="x"), b"y")]
        decrypt_and_extract.return_value = extracted

        result = wizard.write_plan_outputs(plan, quiet=True, debug=True)

        self.assertEqual(result, 0)
        decrypt_and_extract.assert_called_once_with(plan, quiet=True, debug=True)
        write_recovered_outputs.assert_called_once_with(
            extracted,
            output_path="out",
            auth_status="verified",
            allow_unsigned=False,
            quiet=True,
        )


if __name__ == "__main__":
    unittest.main()
