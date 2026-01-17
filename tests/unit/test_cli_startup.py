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
from unittest import mock

from ethernity.cli import startup


class TestCliStartup(unittest.TestCase):
    def test_run_startup_init_config_exits(self) -> None:
        with mock.patch.object(startup, "configure_ui") as configure_mock:
            with mock.patch.object(startup, "_ensure_playwright_browsers") as pw_mock:
                with mock.patch.object(
                    startup, "init_user_config", return_value="/tmp/cfg"
                ) as init_mock:
                    with mock.patch.object(startup, "user_config_needs_init") as needs_mock:
                        with mock.patch.object(startup.console, "print") as print_mock:
                            result = startup.run_startup(
                                quiet=False,
                                no_color=False,
                                no_animations=False,
                                debug=False,
                                init_config=True,
                            )
        self.assertTrue(result)
        configure_mock.assert_called_once()
        pw_mock.assert_called_once()
        init_mock.assert_called_once()
        needs_mock.assert_not_called()
        print_mock.assert_called_once()

    def test_run_startup_initializes_missing_config(self) -> None:
        with mock.patch.object(startup, "configure_ui"):
            with mock.patch.object(startup, "_ensure_playwright_browsers"):
                with mock.patch.object(startup, "user_config_needs_init", return_value=True):
                    with mock.patch.object(
                        startup, "init_user_config", return_value="/tmp/cfg"
                    ) as init_mock:
                        with mock.patch.object(startup.console, "print"):
                            result = startup.run_startup(
                                quiet=True,
                                no_color=True,
                                no_animations=True,
                                debug=False,
                                init_config=False,
                            )
        self.assertFalse(result)
        init_mock.assert_called_once()

    def test_run_startup_no_config_needed(self) -> None:
        with mock.patch.object(startup, "configure_ui"):
            with mock.patch.object(startup, "_ensure_playwright_browsers"):
                with mock.patch.object(startup, "user_config_needs_init", return_value=False):
                    with mock.patch.object(startup, "init_user_config") as init_mock:
                        result = startup.run_startup(
                            quiet=True,
                            no_color=True,
                            no_animations=True,
                            debug=False,
                            init_config=False,
                        )
        self.assertFalse(result)
        init_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
