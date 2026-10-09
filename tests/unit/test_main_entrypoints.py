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
from pathlib import Path
from unittest import mock


class TestMainEntrypoints(unittest.TestCase):
    @mock.patch("ethernity.main.main")
    def test_package_main_dispatches_to_root_main(self, root_main: mock.MagicMock) -> None:
        root_main.return_value = 0
        with self.assertRaises(SystemExit) as ctx:
            runpy.run_module("ethernity.__main__", run_name="__main__")
        self.assertEqual(ctx.exception.code, 0)
        root_main.assert_called_once_with()

    @mock.patch("ethernity.main.main")
    def test_package_main_import_path_does_not_dispatch(self, root_main: mock.MagicMock) -> None:
        runpy.run_module("ethernity.__main__", run_name="ethernity.__main__")
        root_main.assert_not_called()

    def test_cli_module_entrypoint_is_removed(self) -> None:
        self.assertFalse(Path("src/ethernity/cli/__main__.py").exists())


if __name__ == "__main__":
    unittest.main()
