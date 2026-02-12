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

import importlib.metadata
import unittest
from types import SimpleNamespace
from unittest import mock

import typer

from ethernity.cli.core import common as common_module


class TestCliCoreCommon(unittest.TestCase):
    def test_run_cli_success_path(self) -> None:
        called: list[str] = []

        def _fn() -> None:
            called.append("ok")

        common_module._run_cli(_fn, debug=False)
        self.assertEqual(called, ["ok"])

    def test_run_cli_nonzero_int_raises_typer_exit(self) -> None:
        with self.assertRaises(typer.Exit) as exc_info:
            common_module._run_cli(lambda: 7, debug=False)
        self.assertEqual(exc_info.exception.exit_code, 7)

    @mock.patch("ethernity.cli.core.common.console_err.print")
    def test_run_cli_catches_known_errors_when_not_debug(
        self,
        print_mock: mock.MagicMock,
    ) -> None:
        with self.assertRaises(typer.Exit) as exc_info:
            common_module._run_cli(lambda: (_ for _ in ()).throw(ValueError("boom")), debug=False)
        self.assertEqual(exc_info.exception.exit_code, 2)
        print_mock.assert_called_once()
        self.assertIn("boom", str(print_mock.call_args.args[0]))

    def test_run_cli_debug_reraises(self) -> None:
        with self.assertRaises(LookupError):
            common_module._run_cli(
                lambda: (_ for _ in ()).throw(LookupError("debug-error")),
                debug=True,
            )

    @mock.patch("ethernity.cli.core.common.install_rich_traceback")
    def test_run_cli_debug_installs_traceback(
        self,
        install_rich_traceback: mock.MagicMock,
    ) -> None:
        common_module._run_cli(lambda: None, debug=True)
        install_rich_traceback.assert_called_once_with(show_locals=True)

    def test_ctx_value(self) -> None:
        ctx_with_obj = SimpleNamespace(obj={"quiet": True})
        ctx_without_obj = SimpleNamespace(obj=None)
        self.assertTrue(common_module._ctx_value(ctx_with_obj, "quiet"))
        self.assertIsNone(common_module._ctx_value(ctx_without_obj, "quiet"))

    def test_resolve_config_and_paper_precedence(self) -> None:
        ctx = SimpleNamespace(obj={"config": "ctx.toml", "paper": "A4"})
        self.assertEqual(
            common_module._resolve_config_and_paper(ctx, None, None),
            ("ctx.toml", "A4"),
        )
        self.assertEqual(
            common_module._resolve_config_and_paper(ctx, "arg.toml", "LETTER"),
            ("arg.toml", "LETTER"),
        )

    def test_paper_callback(self) -> None:
        self.assertIsNone(common_module._paper_callback(None))
        self.assertEqual(common_module._paper_callback("a4"), "A4")
        self.assertEqual(common_module._paper_callback(" letter "), "LETTER")
        with self.assertRaises(typer.BadParameter):
            common_module._paper_callback("A3")

    @mock.patch("ethernity.cli.core.common.importlib.metadata.version", return_value="1.2.3")
    def test_get_version_success(self, _version: mock.MagicMock) -> None:
        self.assertEqual(common_module._get_version(), "1.2.3")

    @mock.patch(
        "ethernity.cli.core.common.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError,
    )
    def test_get_version_fallback(self, _version: mock.MagicMock) -> None:
        self.assertEqual(common_module._get_version(), "0.0.0")


if __name__ == "__main__":
    unittest.main()
