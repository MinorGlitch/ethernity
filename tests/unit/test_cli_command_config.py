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

import typer

from ethernity.cli.commands import config as config_module


class TestConfigCommand(unittest.TestCase):
    def _ctx(self, **values: object) -> object:
        return mock.Mock(obj=dict(values))

    def test_resolve_editor_command(self) -> None:
        self.assertEqual(config_module._resolve_editor_command("code -w"), ["code", "-w"])
        self.assertIsNone(config_module._resolve_editor_command("  "))
        self.assertIsNone(config_module._resolve_editor_command("default"))
        self.assertIsNone(config_module._resolve_editor_command("system"))

    @mock.patch.dict(os.environ, {"VISUAL": "nvim -u NONE", "EDITOR": "nano"}, clear=True)
    def test_resolve_editor_command_uses_visual_over_editor(self) -> None:
        self.assertEqual(config_module._resolve_editor_command(None), ["nvim", "-u", "NONE"])

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_resolve_editor_command_no_env_returns_none(self) -> None:
        self.assertIsNone(config_module._resolve_editor_command(None))

    def test_open_in_editor_missing_file_raises(self) -> None:
        missing = Path(tempfile.gettempdir()) / "ethernity-missing-config.toml"
        if missing.exists():
            missing.unlink()
        with self.assertRaisesRegex(FileNotFoundError, "config file not found"):
            config_module._open_in_editor(missing, editor=None, quiet=True)

    @mock.patch("ethernity.cli.commands.config.typer.launch")
    @mock.patch("ethernity.cli.commands.config._resolve_editor_command", return_value=None)
    @mock.patch("ethernity.cli.commands.config.console.print")
    def test_open_in_editor_system_launcher_paths(
        self,
        print_mock: mock.MagicMock,
        _resolve_editor_command: mock.MagicMock,
        launch: mock.MagicMock,
    ) -> None:
        with tempfile.NamedTemporaryFile(suffix=".toml") as fh:
            path = Path(fh.name)
            config_module._open_in_editor(path, editor=None, quiet=False)
            config_module._open_in_editor(path, editor=None, quiet=True)
        launch.assert_called()
        self.assertEqual(launch.call_count, 2)
        print_mock.assert_called_once()

    @mock.patch("ethernity.cli.commands.config.subprocess.run")
    @mock.patch(
        "ethernity.cli.commands.config._resolve_editor_command",
        return_value=["code", "-w"],
    )
    @mock.patch("ethernity.cli.commands.config.console.print")
    def test_open_in_editor_explicit_editor_paths(
        self,
        print_mock: mock.MagicMock,
        _resolve_editor_command: mock.MagicMock,
        subprocess_run: mock.MagicMock,
    ) -> None:
        with tempfile.NamedTemporaryFile(suffix=".toml") as fh:
            path = Path(fh.name)
            config_module._open_in_editor(path, editor="code -w", quiet=False)
            config_module._open_in_editor(path, editor="code -w", quiet=True)
        self.assertEqual(subprocess_run.call_count, 2)
        subprocess_run.assert_any_call(["code", "-w", str(path)], check=False)
        print_mock.assert_called_once()

    @mock.patch("ethernity.cli.commands.config._open_in_editor")
    @mock.patch(
        "ethernity.cli.commands.config.resolve_config_path", return_value=Path("/tmp/cfg.toml")
    )
    @mock.patch("ethernity.cli.commands.config._run_cli", side_effect=lambda func, debug: func())
    def test_config_command_open_editor_with_context_values(
        self,
        _run_cli: mock.MagicMock,
        resolve_config_path: mock.MagicMock,
        open_in_editor: mock.MagicMock,
    ) -> None:
        ctx = self._ctx(config="ctx.toml", quiet=True, debug=False)
        config_module.config(ctx, config=None, editor="nano", print_path=False)
        resolve_config_path.assert_called_once_with("ctx.toml")
        open_in_editor.assert_called_once_with(Path("/tmp/cfg.toml"), editor="nano", quiet=True)

    @mock.patch("ethernity.cli.commands.config._open_in_editor")
    @mock.patch("ethernity.cli.commands.config.console.print")
    @mock.patch(
        "ethernity.cli.commands.config.resolve_config_path", return_value=Path("/tmp/print.toml")
    )
    @mock.patch("ethernity.cli.commands.config._run_cli", side_effect=lambda func, debug: func())
    def test_config_command_print_path_short_circuit(
        self,
        _run_cli: mock.MagicMock,
        resolve_config_path: mock.MagicMock,
        print_mock: mock.MagicMock,
        open_in_editor: mock.MagicMock,
    ) -> None:
        ctx = self._ctx(config="ctx.toml", quiet=False, debug=True)
        config_module.config(ctx, config=None, editor=None, print_path=True)
        resolve_config_path.assert_called_once_with("ctx.toml")
        print_mock.assert_called_once_with("/tmp/print.toml")
        open_in_editor.assert_not_called()

    def test_register(self) -> None:
        app = typer.Typer()
        config_module.register(app)
        self.assertGreater(len(app.registered_commands), 0)


if __name__ == "__main__":
    unittest.main()
