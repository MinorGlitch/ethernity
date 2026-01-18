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

from typer.testing import CliRunner

from ethernity.cli import app


class TestCliTyper(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_help_includes_commands(self) -> None:
        result = self.runner.invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("backup", result.output)
        self.assertIn("config", result.output)
        self.assertIn("recover", result.output)

    def test_version_flag(self) -> None:
        result = self.runner.invoke(app, ["--version"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("ethernity", result.output.lower())


if __name__ == "__main__":
    unittest.main()
