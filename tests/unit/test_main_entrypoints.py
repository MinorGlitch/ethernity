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

import runpy
import unittest
from unittest import mock


class TestMainEntrypoints(unittest.TestCase):
    @mock.patch("ethernity.cli.main")
    def test_package_main_dispatches_to_cli_main(self, cli_main: mock.MagicMock) -> None:
        runpy.run_module("ethernity.__main__", run_name="__main__")
        cli_main.assert_called_once_with()

    @mock.patch("ethernity.cli.app.main")
    def test_cli_main_dispatches_to_app_main(self, app_main: mock.MagicMock) -> None:
        runpy.run_module("ethernity.cli.__main__", run_name="__main__")
        app_main.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
