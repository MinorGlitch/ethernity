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
from pathlib import Path
from unittest import mock

import typer
from typer.testing import CliRunner

import ethernity.cli as cli
from ethernity.cli.features.extend import command as extend_command
from ethernity.cli.features.extend.service import PublishedExtensionResult
from ethernity.cli.shared.types import CliContextState
from ethernity.config import (
    BackupDefaults,
    CliDefaults,
    DebugDefaults,
    RecoverDefaults,
    RuntimeDefaults,
    UiDefaults,
)


class TestExtendCommand(unittest.TestCase):
    def _ctx(self, **values: object) -> object:
        return mock.Mock(obj=CliContextState(**values))

    @mock.patch("ethernity.cli.features.extend.command.run_extend_command", return_value=0)
    @mock.patch(
        "ethernity.cli.features.extend.command._run_cli", side_effect=lambda func, debug: func()
    )
    @mock.patch(
        "ethernity.cli.features.extend.command._resolve_config_and_paper",
        return_value=("ctx.toml", "LETTER"),
    )
    def test_extend_command_resolves_context_and_defaults(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_extend_command: mock.MagicMock,
    ) -> None:
        ctx = self._ctx(
            design="forge",
            quiet=False,
            debug=True,
            backup_defaults=BackupDefaults(
                base_dir="./vault",
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=3,
            ),
        )
        extend_command.extend(
            ctx,
            root_dir=Path("/tmp/root"),
            input=[Path("updated.txt")],
            input_dir=None,
            base_dir=None,
            layout_debug_dir="/tmp/layout",
            qr_chunk_size=640,
            passphrase="secret",
            shard_fallback_file=None,
            shard_payloads_file=None,
            shard_scan=None,
            unlock_policy=None,
            shard_threshold=None,
            shard_count=None,
            signing_key_mode=None,
            signing_key_shard_threshold=None,
            signing_key_shard_count=None,
            config=None,
            paper=None,
            design=None,
            debug=False,
            quiet=False,
        )

        args = run_extend_command.call_args.args[0]
        self.assertEqual(args.config, "ctx.toml")
        self.assertEqual(args.paper, "LETTER")
        self.assertEqual(args.design, "forge")
        self.assertEqual(args.root_dir, "/tmp/root")
        self.assertEqual(args.input, ["updated.txt"])
        self.assertEqual(args.base_dir, "./vault")
        self.assertEqual(args.layout_debug_dir, "/tmp/layout")
        self.assertEqual(args.qr_chunk_size, 640)
        self.assertEqual(args.passphrase, "secret")
        self.assertEqual(args.shard_scan, [])
        self.assertIsNone(args.unlock_policy)
        self.assertEqual(args.shard_threshold, 2)
        self.assertEqual(args.shard_count, 3)
        self.assertEqual(args.signing_key_mode, "sharded")
        self.assertEqual(args.signing_key_shard_threshold, 2)
        self.assertEqual(args.signing_key_shard_count, 3)
        self.assertTrue(run_extend_command.call_args.kwargs["debug"])

    @mock.patch("ethernity.cli.features.extend.command.console_err")
    def test_extend_command_requires_explicit_scope(self, console_err: mock.MagicMock) -> None:
        ctx = self._ctx(quiet=False, debug=False)

        with self.assertRaises(typer.Exit) as raised:
            extend_command.extend(
                ctx,
                root_dir=Path("/tmp/root"),
                input=None,
                input_dir=None,
                base_dir=None,
                layout_debug_dir=None,
                qr_chunk_size=None,
                passphrase=None,
                shard_fallback_file=None,
                shard_payloads_file=None,
                shard_scan=None,
                unlock_policy=None,
                shard_threshold=None,
                shard_count=None,
                signing_key_mode=None,
                signing_key_shard_threshold=None,
                signing_key_shard_count=None,
                config=None,
                paper=None,
                design=None,
                debug=False,
                quiet=False,
            )

        self.assertEqual(raised.exception.exit_code, 2)
        console_err.print.assert_called_once()

    @mock.patch("ethernity.cli.features.extend.command._print_completion_actions")
    @mock.patch("ethernity.cli.features.extend.command._print_extend_summary")
    @mock.patch("ethernity.cli.features.extend.command.run_extend")
    def test_run_extend_command_prints_summary(
        self,
        run_extend: mock.MagicMock,
        print_extend_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        result = PublishedExtensionResult(
            index=2,
            doc_id=b"\xaa" * 16,
            doc_hash=b"\xbb" * 32,
            final_dir=Path("/tmp/root/extensions/02"),
            qr_document_path=Path("/tmp/root/extensions/02/qr_document-02-aa.pdf"),
            recovery_document_path=Path("/tmp/root/extensions/02/recovery_document-02-aa.pdf"),
            recovery_kit_index_path=None,
            shard_paths=(Path("/tmp/root/extensions/02/shard-1.pdf"),),
            signing_key_shard_paths=(),
        )
        run_extend.return_value = result

        exit_code = extend_command.run_extend_command(
            extend_command.ExtendArgs(root_dir="/tmp/root", input=["updated.txt"], quiet=False)
        )

        self.assertEqual(exit_code, 0)
        print_extend_summary.assert_called_once_with(result, quiet=False)
        print_completion_actions.assert_called_once_with(result, quiet=False)

    def test_register(self) -> None:
        app = typer.Typer()
        extend_command.register(app)
        self.assertGreater(len(app.registered_commands), 0)

    @mock.patch("ethernity.cli.features.extend.command.run_extend_command", return_value=0)
    @mock.patch(
        "ethernity.cli.features.extend.command._run_cli", side_effect=lambda func, debug: func()
    )
    @mock.patch(
        "ethernity.cli.features.extend.command._resolve_config_and_paper",
        return_value=("ctx.toml", "LETTER"),
    )
    def test_extend_command_passes_unlock_policy(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_extend_command: mock.MagicMock,
    ) -> None:
        extend_command.extend(
            self._ctx(
                quiet=False,
                debug=False,
                backup_defaults=BackupDefaults(
                    shard_threshold=2,
                    shard_count=3,
                    signing_key_mode="sharded",
                    signing_key_shard_threshold=2,
                    signing_key_shard_count=3,
                ),
            ),
            root_dir=Path("/tmp/root"),
            input=[Path("updated.txt")],
            input_dir=None,
            base_dir=None,
            layout_debug_dir=None,
            qr_chunk_size=None,
            passphrase=None,
            shard_fallback_file=None,
            shard_payloads_file=None,
            shard_scan=None,
            unlock_policy="reuse-root",
            shard_threshold=None,
            shard_count=None,
            signing_key_mode=None,
            signing_key_shard_threshold=None,
            signing_key_shard_count=None,
            config=None,
            paper=None,
            design=None,
            debug=False,
            quiet=False,
        )

        args = run_extend_command.call_args.args[0]
        self.assertEqual(args.unlock_policy, "reuse-root")
        self.assertIsNone(args.shard_threshold)
        self.assertIsNone(args.shard_count)
        self.assertIsNone(args.signing_key_mode)
        self.assertIsNone(args.signing_key_shard_threshold)
        self.assertIsNone(args.signing_key_shard_count)

    @mock.patch("ethernity.cli.features.extend.command.run_extend_command", return_value=0)
    @mock.patch(
        "ethernity.cli.features.extend.command._run_cli", side_effect=lambda func, debug: func()
    )
    @mock.patch(
        "ethernity.cli.features.extend.command._resolve_config_and_paper",
        return_value=("ctx.toml", "LETTER"),
    )
    def test_extend_command_passes_shard_unlock_inputs(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_extend_command: mock.MagicMock,
    ) -> None:
        extend_command.extend(
            self._ctx(quiet=False, debug=False, backup_defaults=BackupDefaults()),
            root_dir=Path("/tmp/root"),
            input=[Path("updated.txt")],
            input_dir=None,
            base_dir=None,
            layout_debug_dir=None,
            qr_chunk_size=None,
            passphrase=None,
            shard_fallback_file=["manual.txt"],
            shard_payloads_file=["payloads.txt"],
            shard_scan=["scan.pdf"],
            unlock_policy=None,
            shard_threshold=None,
            shard_count=None,
            signing_key_mode=None,
            signing_key_shard_threshold=None,
            signing_key_shard_count=None,
            config=None,
            paper=None,
            design=None,
            debug=False,
            quiet=False,
        )

        args = run_extend_command.call_args.args[0]
        self.assertEqual(args.shard_fallback_file, ["manual.txt"])
        self.assertEqual(args.shard_payloads_file, ["payloads.txt"])
        self.assertEqual(args.shard_scan, ["scan.pdf"])


class TestExtendCliApp(unittest.TestCase):
    runner = CliRunner()

    def test_extend_bootstraps_operator_defaults_from_cli_config(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: extend_command.ExtendArgs, *, debug: bool = False) -> int:
            captured["base_dir"] = args.base_dir
            captured["shard_threshold"] = args.shard_threshold
            captured["root_dir"] = args.root_dir
            captured["input"] = list(args.input or [])
            captured["debug"] = debug
            return 0

        defaults = CliDefaults(
            backup=BackupDefaults(base_dir="./vault", shard_threshold=2),
            recover=RecoverDefaults(),
            ui=UiDefaults(),
            debug=DebugDefaults(),
            runtime=RuntimeDefaults(),
        )

        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            with mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=defaults):
                with mock.patch(
                    "ethernity.cli.features.extend.command.run_extend_command",
                    side_effect=_capture_args,
                ):
                    result = self.runner.invoke(
                        cli.app,
                        ["extend", "--root-dir", "/tmp/root", "--input", "-"],
                        input="payload",
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["base_dir"], "./vault")
        self.assertEqual(captured["shard_threshold"], 2)
        self.assertEqual(captured["root_dir"], "/tmp/root")
        self.assertEqual(captured["input"], ["-"])
