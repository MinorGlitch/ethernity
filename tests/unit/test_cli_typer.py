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

import re
import unittest
from unittest import mock

from typer.testing import CliRunner

from ethernity.cli import app
from ethernity.config.installer import DEFAULT_CONFIG_PATH

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


class TestCliTyper(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_root_info_commands(self) -> None:
        cases = (
            {
                "args": ["--help"],
                "expected_exit_code": 0,
                "contains": ("backup", "config", "recover"),
            },
            {
                "args": ["--version"],
                "expected_exit_code": 0,
                "contains": ("ethernity",),
            },
        )
        for case in cases:
            with self.subTest(args=case["args"]):
                with mock.patch("ethernity.cli.app.run_startup", return_value=False):
                    result = self.runner.invoke(app, case["args"])
                self.assertEqual(result.exit_code, case["expected_exit_code"])
                output = result.output.lower() if "--version" in case["args"] else result.output
                for expected in case["contains"]:
                    self.assertIn(expected, output)

    def test_root_no_subcommand_non_tty_references_help(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            with mock.patch("ethernity.cli.app.sys.stdin.isatty", return_value=False):
                result = self.runner.invoke(app, [])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("ethernity --help", result.output)

    def test_backup_help_lists_qr_chunk_size(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            result = self.runner.invoke(app, ["backup", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--qr-chunk-size", _strip_ansi(result.output))

    def test_kit_help_lists_qr_chunk_size(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            result = self.runner.invoke(app, ["kit", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--qr-chunk-size", _strip_ansi(result.output))

    def test_kit_old_chunk_size_flag_is_rejected(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            result = self.runner.invoke(app, ["kit", "--chunk-size", "100"])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("No such option", result.output)
        self.assertIn("--chunk-size", _strip_ansi(result.output))

    def test_kit_custom_bundle_missing_file_returns_actionable_error(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            result = self.runner.invoke(
                app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "kit",
                    "--bundle",
                    "/no/such/bundle.html",
                ],
            )
        self.assertEqual(result.exit_code, 2)
        self.assertIn("bundle file not found", result.output)
        self.assertIn("--bundle", result.output)


if __name__ == "__main__":
    unittest.main()
