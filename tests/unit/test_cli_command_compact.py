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
from ethernity.cli.features.compact import command as compact_command
from ethernity.cli.shared.types import BackupResult, CliContextState
from ethernity.config import (
    BackupDefaults,
    CliDefaults,
    DebugDefaults,
    RecoverDefaults,
    RuntimeDefaults,
    UiDefaults,
)


class TestCompactCommand(unittest.TestCase):
    def _ctx(self, **values: object) -> object:
        return mock.Mock(obj=CliContextState(**values))

    @mock.patch("ethernity.cli.features.compact.command.run_compact_command", return_value=0)
    @mock.patch(
        "ethernity.cli.features.compact.command._run_cli", side_effect=lambda func, debug: func()
    )
    @mock.patch(
        "ethernity.cli.features.compact.command._resolve_config_and_paper",
        return_value=("ctx.toml", "LETTER"),
    )
    def test_compact_command_resolves_context_and_defaults(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_compact_command: mock.MagicMock,
    ) -> None:
        ctx = self._ctx(
            design="forge",
            quiet=False,
            debug=True,
            backup_defaults=BackupDefaults(output_dir="./compacted"),
        )
        compact_command.compact(
            ctx,
            root_dir=Path("/tmp/root"),
            output_dir=None,
            shard_fallback_file=["shard-a.txt"],
            shard_payloads_file=["shard-a.payloads"],
            shard_scan=["shard-a.pdf"],
            auth_fallback_file="auth.txt",
            auth_payloads_file="auth.payloads",
            layout_debug_dir="/tmp/layout",
            qr_chunk_size=640,
            passphrase="secret",
            config=None,
            paper=None,
            design=None,
            debug=False,
            quiet=False,
        )

        args = run_compact_command.call_args.args[0]
        self.assertEqual(args.config, "ctx.toml")
        self.assertEqual(args.paper, "LETTER")
        self.assertEqual(args.design, "forge")
        self.assertEqual(args.root_dir, "/tmp/root")
        self.assertEqual(args.output_dir, "./compacted")
        self.assertEqual(args.shard_fallback_file, ["shard-a.txt"])
        self.assertEqual(args.shard_payloads_file, ["shard-a.payloads"])
        self.assertEqual(args.shard_scan, ["shard-a.pdf"])
        self.assertEqual(args.auth_fallback_file, "auth.txt")
        self.assertEqual(args.auth_payloads_file, "auth.payloads")
        self.assertEqual(args.layout_debug_dir, "/tmp/layout")
        self.assertEqual(args.qr_chunk_size, 640)
        self.assertEqual(args.passphrase, "secret")
        self.assertTrue(run_compact_command.call_args.kwargs["debug"])

    @mock.patch("ethernity.cli.features.compact.command.console_err")
    def test_compact_command_requires_output_dir(self, console_err: mock.MagicMock) -> None:
        ctx = self._ctx(quiet=False, debug=False)

        with self.assertRaises(typer.Exit) as raised:
            compact_command.compact(
                ctx,
                root_dir=Path("/tmp/root"),
                output_dir=None,
                shard_fallback_file=None,
                shard_payloads_file=None,
                shard_scan=None,
                auth_fallback_file=None,
                auth_payloads_file=None,
                layout_debug_dir=None,
                qr_chunk_size=None,
                passphrase=None,
                config=None,
                paper=None,
                design=None,
                debug=False,
                quiet=False,
            )

        self.assertEqual(raised.exception.exit_code, 2)
        console_err.print.assert_called_once()

    @mock.patch("ethernity.cli.features.compact.command._print_completion_actions")
    @mock.patch("ethernity.cli.features.compact.command._print_compact_summary")
    @mock.patch("ethernity.cli.features.compact.command.run_compact")
    def test_run_compact_command_prints_summary(
        self,
        run_compact: mock.MagicMock,
        print_compact_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
    ) -> None:
        result = BackupResult(
            doc_id=b"\xaa" * 16,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            kit_index_path=None,
            shard_paths=("/tmp/out/shard-deadbeef-1-of-2.pdf",),
            signing_key_shard_paths=(),
            passphrase_used=None,
        )
        run_compact.return_value = result

        exit_code = compact_command.run_compact_command(
            compact_command.CompactArgs(root_dir="/tmp/root", output_dir="/tmp/out", quiet=False)
        )

        self.assertEqual(exit_code, 0)
        print_compact_summary.assert_called_once_with(result, root_dir="/tmp/root", quiet=False)
        print_completion_actions.assert_called_once_with(result, output_dir="/tmp/out", quiet=False)

    def test_register(self) -> None:
        app = typer.Typer()
        compact_command.register(app)
        self.assertGreater(len(app.registered_commands), 0)


class TestCompactCliApp(unittest.TestCase):
    runner = CliRunner()

    def test_compact_bootstraps_operator_defaults_from_cli_config(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: compact_command.CompactArgs, *, debug: bool = False) -> int:
            captured["root_dir"] = args.root_dir
            captured["output_dir"] = args.output_dir
            captured["debug"] = debug
            return 0

        defaults = CliDefaults(
            backup=BackupDefaults(output_dir="./compacted"),
            recover=RecoverDefaults(),
            ui=UiDefaults(),
            debug=DebugDefaults(),
            runtime=RuntimeDefaults(),
        )

        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            with mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=defaults):
                with mock.patch(
                    "ethernity.cli.features.compact.command.run_compact_command",
                    side_effect=_capture_args,
                ):
                    result = self.runner.invoke(
                        cli.app,
                        ["compact", "--root-dir", "/tmp/root", "--passphrase", "secret"],
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["root_dir"], "/tmp/root")
        self.assertEqual(captured["output_dir"], "./compacted")
