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
import importlib
import unittest
from dataclasses import dataclass
from unittest import mock

import typer

from ethernity.cli.core.types import RecoverArgs

app_module = importlib.import_module("ethernity.cli.app")


@dataclass
class _Ctx:
    invoked_subcommand: str | None = None
    obj: dict[str, object] | None = None

    def ensure_object(self, _type):
        if self.obj is None:
            self.obj = {}
        return self.obj


class TestCliApp(unittest.TestCase):
    @mock.patch("ethernity.cli.app.console.print")
    def test_version_callback(self, print_mock: mock.MagicMock) -> None:
        with self.assertRaises(typer.Exit):
            app_module._version_callback(True)
        print_mock.assert_called_once()
        app_module._version_callback(False)

    @mock.patch("ethernity.cli.app.console_err.print")
    @mock.patch("ethernity.cli.app.run_startup", side_effect=ValueError("startup-failed"))
    def test_cli_startup_exception_returns_exit_2(
        self,
        _run_startup: mock.MagicMock,
        print_err: mock.MagicMock,
    ) -> None:
        ctx = _Ctx()
        with self.assertRaises(typer.Exit) as exc_info:
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        self.assertEqual(exc_info.exception.exit_code, 2)
        print_err.assert_called_once()

    @mock.patch("ethernity.cli.app.run_startup", return_value=True)
    def test_cli_startup_should_exit(
        self,
        _run_startup: mock.MagicMock,
    ) -> None:
        ctx = _Ctx()
        with self.assertRaises(typer.Exit) as exc_info:
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        self.assertEqual(exc_info.exception.exit_code, 0)

    @mock.patch("ethernity.cli.app.console_err.print")
    @mock.patch("ethernity.cli.app.sys.stdin.isatty", return_value=False)
    @mock.patch("ethernity.cli.app.run_startup", return_value=False)
    def test_cli_no_subcommand_non_tty_errors(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        print_err: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        with self.assertRaises(typer.Exit) as exc_info:
            app_module.cli(
                ctx,
                config=None,
                paper=None,
                design=None,
                debug=False,
                debug_max_bytes=1024,
                debug_reveal_secrets=False,
                quiet=False,
                no_color=False,
                no_animations=False,
                init_config=False,
                version=False,
            )
        self.assertEqual(exc_info.exception.exit_code, 2)
        print_err.assert_called_once()

    @mock.patch("ethernity.cli.app.run_recover_wizard", return_value=0)
    @mock.patch("ethernity.cli.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.app.empty_recover_args", return_value=RecoverArgs())
    @mock.patch("ethernity.cli.app.prompt_home_action", return_value="recover")
    @mock.patch("ethernity.cli.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch("ethernity.cli.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.app.run_startup", return_value=False)
    def test_cli_interactive_recover_route(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_home_action: mock.MagicMock,
        _empty_recover_args: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_recover_wizard: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        app_module.cli(
            ctx,
            config=None,
            paper=None,
            design=None,
            debug=True,
            debug_max_bytes=1024,
            debug_reveal_secrets=True,
            quiet=False,
            no_color=False,
            no_animations=False,
            init_config=False,
            version=False,
        )
        ui_screen_mode.assert_called_once_with(quiet=False)
        run_recover_wizard.assert_called_once()
        self.assertTrue(run_recover_wizard.call_args.kwargs["debug"])
        _empty_recover_args.assert_called_once_with(
            config="cfg",
            paper="A4",
            quiet=False,
            debug_max_bytes=1024,
            debug_reveal_secrets=True,
        )

    @mock.patch("ethernity.cli.app.run_wizard", return_value=0)
    @mock.patch("ethernity.cli.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.app.prompt_home_action", return_value="backup")
    @mock.patch("ethernity.cli.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch("ethernity.cli.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.app.run_startup", return_value=False)
    def test_cli_interactive_backup_route(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_home_action: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_wizard: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        app_module.cli(
            ctx,
            config=None,
            paper=None,
            design="forge",
            debug=False,
            debug_max_bytes=1024,
            debug_reveal_secrets=True,
            quiet=False,
            no_color=False,
            no_animations=False,
            init_config=False,
            version=False,
        )
        ui_screen_mode.assert_called_once_with(quiet=False)
        run_wizard.assert_called_once()
        self.assertEqual(run_wizard.call_args.kwargs["args"].design, "forge")
        self.assertTrue(run_wizard.call_args.kwargs["debug_reveal_secrets"])

    @mock.patch("ethernity.cli.app._run_kit_render", return_value=None)
    @mock.patch("ethernity.cli.app._run_cli", side_effect=lambda func, debug: func())
    @mock.patch("ethernity.cli.app.prompt_home_action", return_value="kit")
    @mock.patch("ethernity.cli.app.ui_screen_mode", return_value=contextlib.nullcontext())
    @mock.patch("ethernity.cli.app._resolve_config_and_paper", return_value=("cfg", "A4"))
    @mock.patch("ethernity.cli.app.sys.stdin.isatty", return_value=True)
    @mock.patch("ethernity.cli.app.run_startup", return_value=False)
    def test_cli_interactive_kit_route(
        self,
        _run_startup: mock.MagicMock,
        _stdin_tty: mock.MagicMock,
        _resolve_config_and_paper: mock.MagicMock,
        ui_screen_mode: mock.MagicMock,
        _prompt_home_action: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_kit_render: mock.MagicMock,
    ) -> None:
        ctx = _Ctx(invoked_subcommand=None)
        app_module.cli(
            ctx,
            config=None,
            paper=None,
            design="forge",
            debug=False,
            debug_max_bytes=1024,
            debug_reveal_secrets=False,
            quiet=False,
            no_color=False,
            no_animations=False,
            init_config=False,
            version=False,
        )
        ui_screen_mode.assert_called_once_with(quiet=False)
        run_kit_render.assert_called_once_with(
            bundle=None,
            output=None,
            config_value="cfg",
            paper_value="A4",
            design_value="forge",
            qr_chunk_size=None,
            quiet_value=False,
        )

    @mock.patch("ethernity.cli.app.app")
    def test_main_dispatches(self, app_mock: mock.MagicMock) -> None:
        app_module.main()
        app_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
