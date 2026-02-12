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
from types import SimpleNamespace
from unittest import mock

import typer

from ethernity.cli.commands import recover as recover_command
from ethernity.cli.core.types import RecoverArgs
from ethernity.cli.flows import recover as recover_flow


class TestRecoverCommand(unittest.TestCase):
    def _ctx(self, **values: object) -> object:
        return mock.Mock(obj=dict(values))

    def _call_recover(self, ctx: object, **overrides: object) -> None:
        options = {
            "fallback_file": None,
            "payloads_file": None,
            "scan": None,
            "passphrase": None,
            "shard_fallback_file": None,
            "shard_dir": None,
            "shard_payloads_file": None,
            "auth_fallback_file": None,
            "auth_payloads_file": None,
            "output": None,
            "allow_unsigned": False,
            "assume_yes": False,
            "config": None,
            "paper": None,
            "quiet": False,
        }
        options.update(overrides)
        recover_command.recover(ctx, **options)

    def test_expand_shard_dir(self) -> None:
        self.assertEqual(recover_command._expand_shard_dir(None), [])
        with self.assertRaises(typer.BadParameter):
            recover_command._expand_shard_dir("/definitely/missing")

        with tempfile.NamedTemporaryFile() as fh:
            with self.assertRaises(typer.BadParameter):
                recover_command._expand_shard_dir(fh.name)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(typer.BadParameter):
                recover_command._expand_shard_dir(str(root))

            (root / "b.txt").write_text("b", encoding="utf-8")
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / "z.md").write_text("z", encoding="utf-8")
            resolved = recover_command._expand_shard_dir(str(root))
            self.assertEqual(resolved, [str(root / "a.txt"), str(root / "b.txt")])

    @mock.patch("ethernity.cli.commands.recover.run_recover_wizard", return_value=0)
    @mock.patch("ethernity.cli.commands.recover._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.commands.recover._should_use_wizard_for_recover", return_value=True)
    @mock.patch("ethernity.cli.commands.recover._expand_shard_dir", return_value=[])
    @mock.patch(
        "ethernity.cli.commands.recover._resolve_config_and_paper", return_value=("cfg", "A4")
    )
    @mock.patch("ethernity.cli.commands.recover.sys.stdin.isatty", return_value=False)
    def test_recover_auto_stdin_wizard_path(
        self,
        _stdin_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        _expand_shard_dir: mock.MagicMock,
        _should_use_wizard_for_recover: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_recover_wizard: mock.MagicMock,
    ) -> None:
        ctx = self._ctx(quiet=False, debug=False)
        self._call_recover(ctx)
        args = run_recover_wizard.call_args.args[0]
        self.assertEqual(args.fallback_file, "-")
        self.assertEqual(args.config, "cfg")
        self.assertEqual(args.paper, "A4")
        self.assertEqual(run_recover_wizard.call_args.kwargs["debug"], False)

    @mock.patch("ethernity.cli.commands.recover.run_recover_command", return_value=0)
    @mock.patch("ethernity.cli.commands.recover._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.commands.recover._should_use_wizard_for_recover", return_value=False)
    @mock.patch("ethernity.cli.commands.recover._expand_shard_dir", return_value=["dir1.txt"])
    @mock.patch(
        "ethernity.cli.commands.recover._resolve_config_and_paper", return_value=("cfg", "A4")
    )
    @mock.patch("ethernity.cli.commands.recover.sys.stdin.isatty", return_value=True)
    def test_recover_nonwizard_path_merges_shard_inputs(
        self,
        _stdin_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        _expand_shard_dir: mock.MagicMock,
        _should_use_wizard_for_recover: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_recover_command: mock.MagicMock,
    ) -> None:
        ctx = self._ctx(quiet=False, debug=True)
        self._call_recover(
            ctx,
            shard_fallback_file=["manual.txt"],
            shard_dir="shards",
            allow_unsigned=True,
        )
        args = run_recover_command.call_args.args[0]
        self.assertEqual(args.shard_fallback_file, ["manual.txt", "dir1.txt"])
        self.assertTrue(args.allow_unsigned)
        self.assertEqual(run_recover_command.call_args.kwargs["debug"], True)

    def test_register(self) -> None:
        app = typer.Typer()
        recover_command.register(app)
        self.assertGreater(len(app.registered_commands), 0)


class TestRecoverFlow(unittest.TestCase):
    @mock.patch("ethernity.cli.flows.recover.run_recover_plan", return_value=0)
    @mock.patch("ethernity.cli.flows.recover._warn")
    @mock.patch("ethernity.cli.flows.recover.plan_from_args")
    def test_run_recover_command_warn_paths(
        self,
        plan_from_args: mock.MagicMock,
        warn: mock.MagicMock,
        run_recover_plan: mock.MagicMock,
    ) -> None:
        plan_from_args.return_value = SimpleNamespace(allow_unsigned=True)
        args = RecoverArgs(quiet=False)
        result = recover_flow.run_recover_command(args, debug=True)
        self.assertEqual(result, 0)
        warn.assert_called_once()
        run_recover_plan.assert_called_once_with(
            plan_from_args.return_value, quiet=False, debug=True
        )

        warn.reset_mock()
        run_recover_plan.reset_mock()
        plan_from_args.return_value = SimpleNamespace(allow_unsigned=False)
        recover_flow.run_recover_command(args, debug=False)
        warn.assert_not_called()
        run_recover_plan.assert_called_once_with(
            plan_from_args.return_value, quiet=False, debug=False
        )

    @mock.patch("ethernity.cli.flows.recover._run_recover_wizard", return_value=3)
    def test_run_recover_wizard_delegates(self, run_wizard: mock.MagicMock) -> None:
        args = RecoverArgs()
        self.assertEqual(recover_flow.run_recover_wizard(args, debug=True), 3)
        run_wizard.assert_called_once_with(args, debug=True)

    @mock.patch("ethernity.cli.flows.recover.sys.stdout.isatty", return_value=True)
    @mock.patch("ethernity.cli.flows.recover.sys.stdin.isatty", return_value=True)
    def test_should_use_wizard_for_recover(
        self, _stdin_tty: mock.MagicMock, _stdout_tty: mock.MagicMock
    ) -> None:
        self.assertTrue(recover_flow._should_use_wizard_for_recover(RecoverArgs()))
        self.assertFalse(
            recover_flow._should_use_wizard_for_recover(RecoverArgs(fallback_file="x"))
        )
        self.assertFalse(
            recover_flow._should_use_wizard_for_recover(RecoverArgs(shard_fallback_file=["x"]))
        )

        with mock.patch("ethernity.cli.flows.recover.sys.stdin.isatty", return_value=False):
            self.assertFalse(recover_flow._should_use_wizard_for_recover(RecoverArgs()))


if __name__ == "__main__":
    unittest.main()
