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
    def test_run_startup_flow_matrix(self) -> None:
        cases = (
            {
                "name": "init-config-exits",
                "init_config": True,
                "needs_init": False,
                "quiet": False,
                "expect_result": True,
                "expect_init_calls": 1,
                "expect_needs_calls": 0,
                "expect_print_calls": 1,
            },
            {
                "name": "missing-config-initialized",
                "init_config": False,
                "needs_init": True,
                "quiet": True,
                "expect_result": False,
                "expect_init_calls": 1,
                "expect_needs_calls": 1,
                "expect_print_calls": 0,
            },
            {
                "name": "config-already-present",
                "init_config": False,
                "needs_init": False,
                "quiet": True,
                "expect_result": False,
                "expect_init_calls": 0,
                "expect_needs_calls": 1,
                "expect_print_calls": 0,
            },
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                with mock.patch.object(startup, "configure_ui") as configure_mock:
                    with mock.patch.object(startup, "_ensure_playwright_browsers") as pw_mock:
                        with mock.patch.object(
                            startup,
                            "init_user_config",
                            return_value="/tmp/cfg",
                        ) as init_mock:
                            with mock.patch.object(
                                startup,
                                "user_config_needs_init",
                                return_value=case["needs_init"],
                            ) as needs_mock:
                                with mock.patch.object(startup.console, "print") as print_mock:
                                    result = startup.run_startup(
                                        quiet=bool(case["quiet"]),
                                        no_color=True,
                                        no_animations=True,
                                        debug=False,
                                        init_config=bool(case["init_config"]),
                                    )
                self.assertEqual(result, case["expect_result"])
                configure_mock.assert_called_once()
                pw_mock.assert_called_once()
                self.assertEqual(init_mock.call_count, case["expect_init_calls"])
                self.assertEqual(needs_mock.call_count, case["expect_needs_calls"])
                self.assertEqual(print_mock.call_count, case["expect_print_calls"])

    def test_playwright_install_failure_surfaces_actionable_error(self) -> None:
        with mock.patch.object(
            startup,
            "_playwright_driver_command",
            return_value=("node", "cli.js"),
        ):
            with mock.patch.object(startup, "_playwright_driver_env", return_value={}):
                with mock.patch.object(startup.subprocess, "run") as run_mock:
                    run_mock.return_value = mock.Mock(
                        returncode=1,
                        stderr="network timeout",
                        stdout="",
                    )
                    with self.assertRaises(RuntimeError) as ctx:
                        startup._playwright_install(None)
        self.assertIn("Playwright install failed", str(ctx.exception))
        self.assertIn("network timeout", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
