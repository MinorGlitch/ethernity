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

from __future__ import annotations

import re
import unittest
from unittest import mock

from typer.testing import CliRunner

from ethernity import cli

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class TestCliHelpPanels(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_human_command_help_uses_normalized_panel_order(self) -> None:
        cases = {
            "backup": [
                "╭─ Inputs",
                "╭─ Unlock",
                "╭─ Outputs",
                "╭─ Behavior",
                "╭─ Config",
                "╭─ Advanced",
                "╭─ Debug",
            ],
            "recover": [
                "╭─ Inputs",
                "╭─ Unlock",
                "╭─ Outputs",
                "╭─ Behavior",
                "╭─ Config",
            ],
            "extend": [
                "╭─ Inputs",
                "╭─ Unlock",
                "╭─ Outputs",
                "╭─ Behavior",
                "╭─ Config",
                "╭─ Advanced",
                "╭─ Debug",
            ],
            "compact": [
                "╭─ Inputs",
                "╭─ Unlock",
                "╭─ Outputs",
                "╭─ Behavior",
                "╭─ Config",
                "╭─ Advanced",
                "╭─ Debug",
            ],
            "mint": [
                "╭─ Inputs",
                "╭─ Unlock",
                "╭─ Outputs",
                "╭─ Behavior",
                "╭─ Config",
                "╭─ Advanced",
            ],
        }

        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            for command, panels in cases.items():
                with self.subTest(command=command):
                    result = self.runner.invoke(cli.app, [command, "--help"])
                    self.assertEqual(result.exit_code, 0, result.output)
                    output = _strip_ansi(result.output)
                    indexes = [output.index(panel) for panel in panels]
                    self.assertEqual(indexes, sorted(indexes))

    def test_recover_help_drops_legacy_panel_names(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(cli.app, ["recover", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        output = _strip_ansi(result.output)
        self.assertNotIn("╭─ Extensions", output)
        self.assertNotIn("╭─ Verification", output)
        self.assertNotIn("╭─ Output ─", output)

    def test_extend_help_uses_outputs_instead_of_sharding_panel(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(cli.app, ["extend", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        output = _strip_ansi(result.output)
        self.assertIn("╭─ Outputs", output)
        self.assertNotIn("╭─ Sharding", output)


if __name__ == "__main__":
    unittest.main()
