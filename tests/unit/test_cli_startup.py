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
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_run_startup_debug_and_auto_init_prints_message(self) -> None:
        with mock.patch.object(startup, "configure_ui"):
            with mock.patch.object(startup, "_ensure_playwright_browsers"):
                with mock.patch.object(startup, "install_rich_traceback") as traceback_mock:
                    with mock.patch.object(startup, "user_config_needs_init", return_value=True):
                        with mock.patch.object(
                            startup, "init_user_config", return_value="/tmp/cfg"
                        ):
                            with mock.patch.object(startup.console, "print") as print_mock:
                                result = startup.run_startup(
                                    quiet=False,
                                    no_color=True,
                                    no_animations=True,
                                    debug=True,
                                    init_config=False,
                                )
        self.assertFalse(result)
        traceback_mock.assert_called_once_with(show_locals=True)
        self.assertEqual(print_mock.call_count, 1)
        self.assertIn("Initialized user config", str(print_mock.call_args[0][0]))

    def test_configure_playwright_env_respects_existing_path(self) -> None:
        with mock.patch.dict(
            os.environ, {startup._PLAYWRIGHT_BROWSERS_ENV: "/already"}, clear=False
        ):
            with mock.patch.object(startup, "user_cache_dir") as cache_mock:
                startup._configure_playwright_env()
                self.assertEqual(os.environ[startup._PLAYWRIGHT_BROWSERS_ENV], "/already")
        cache_mock.assert_not_called()

    def test_configure_playwright_env_sets_default_cache_path(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(startup._PLAYWRIGHT_BROWSERS_ENV, None)
            with mock.patch.object(startup, "user_cache_dir", return_value="/cache/ms-playwright"):
                startup._configure_playwright_env()
                self.assertEqual(
                    os.environ[startup._PLAYWRIGHT_BROWSERS_ENV],
                    "/cache/ms-playwright",
                )

    def test_playwright_driver_command_platform_variants_and_override(self) -> None:
        with mock.patch.object(startup.inspect, "getfile", return_value="/opt/pw/__init__.py"):
            with mock.patch.object(startup.sys, "platform", "darwin"):
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("PLAYWRIGHT_NODEJS_PATH", None)
                    node_path, cli_path = startup._playwright_driver_command()
        self.assertEqual(Path(node_path), Path("/opt/pw") / "driver" / "node")
        self.assertEqual(Path(cli_path), Path("/opt/pw") / "driver" / "package" / "cli.js")

        with mock.patch.object(startup.inspect, "getfile", return_value="/opt/pw/__init__.py"):
            with mock.patch.object(startup.sys, "platform", "win32"):
                with mock.patch.dict(
                    os.environ, {"PLAYWRIGHT_NODEJS_PATH": "C:/node.exe"}, clear=False
                ):
                    node_path, cli_path = startup._playwright_driver_command()
        self.assertEqual(node_path, "C:/node.exe")
        self.assertEqual(Path(cli_path), Path("/opt/pw") / "driver" / "package" / "cli.js")

    def test_playwright_chromium_installed_success_and_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "chromium"
            executable.write_text("bin", encoding="utf-8")
            fake_pw = mock.MagicMock()
            fake_pw.chromium.executable_path = str(executable)
            fake_context = mock.MagicMock()
            fake_context.__enter__.return_value = fake_pw
            fake_context.__exit__.return_value = False
            with mock.patch.object(startup, "sync_playwright", return_value=fake_context):
                self.assertTrue(startup._playwright_chromium_installed())

        with mock.patch.object(startup, "sync_playwright", side_effect=RuntimeError("boom")):
            self.assertFalse(startup._playwright_chromium_installed())

    def test_progress_update_branches(self) -> None:
        progress = mock.Mock()
        startup._progress_update(progress, None, 1, 10, "desc")
        progress.update.assert_not_called()

        startup._progress_update(progress, 9, 3, 7, "installing")
        progress.update.assert_has_calls(
            [
                mock.call(9, total=7),
                mock.call(9, description="installing"),
                mock.call(9, completed=3),
            ]
        )

    def test_progress_finalize_branches(self) -> None:
        progress = mock.Mock()
        progress.tasks = {
            1: SimpleNamespace(total=5, completed=0),
            2: SimpleNamespace(total=None, completed=0),
            3: SimpleNamespace(total=None, completed=2),
        }

        startup._progress_finalize(progress, 1)
        startup._progress_finalize(progress, 2)
        startup._progress_finalize(progress, 3)

        progress.update.assert_has_calls([mock.call(1, completed=5), mock.call(2, completed=1)])
        self.assertEqual(progress.update.call_count, 2)

    def test_ensure_dependency_short_circuits_and_progress_paths(self) -> None:
        ensure = mock.Mock()

        with mock.patch.dict(os.environ, {"SKIP_ME": "1"}, clear=False):
            startup._ensure_dependency(
                quiet=True,
                skip_env="SKIP_ME",
                description="x",
                ensure=ensure,
                precheck=None,
            )
        ensure.assert_not_called()

        startup._ensure_dependency(
            quiet=True,
            skip_env="SKIP_ME_MISSING",
            description="x",
            ensure=ensure,
            precheck=lambda: True,
        )
        ensure.assert_not_called()

        with mock.patch.object(startup, "progress", return_value=contextlib.nullcontext(None)):
            startup._ensure_dependency(
                quiet=True,
                skip_env="SKIP_ME_MISSING",
                description="x",
                ensure=ensure,
                precheck=lambda: False,
            )
        ensure.assert_called_once_with(None)
        ensure.reset_mock()

        progress_bar = mock.Mock()
        progress_bar.add_task.return_value = 12
        with mock.patch.object(
            startup, "progress", return_value=contextlib.nullcontext(progress_bar)
        ):
            with mock.patch.object(startup, "_progress_finalize") as finalize_mock:
                startup._ensure_dependency(
                    quiet=False,
                    skip_env="SKIP_ME_MISSING",
                    description="installing",
                    ensure=ensure,
                    precheck=None,
                )
        finalize_mock.assert_called_once_with(progress_bar, 12)
        self.assertEqual(ensure.call_count, 1)
        callback = ensure.call_args[0][0]
        self.assertIsNotNone(callback)
        assert callback is not None
        callback(50, 100, "half")
        progress_bar.update.assert_any_call(12, total=100)
        progress_bar.update.assert_any_call(12, description="half")
        progress_bar.update.assert_any_call(12, completed=50)

    def test_playwright_precheck_configures_env_before_check(self) -> None:
        with mock.patch.object(startup, "_configure_playwright_env") as cfg_mock:
            with mock.patch.object(
                startup, "_playwright_chromium_installed", return_value=True
            ) as check_mock:
                self.assertTrue(startup._playwright_precheck())
        cfg_mock.assert_called_once()
        check_mock.assert_called_once()

    def test_playwright_install_without_progress_success(self) -> None:
        with mock.patch.object(
            startup, "_playwright_driver_command", return_value=("node", "cli.js")
        ):
            with mock.patch.object(startup, "_playwright_driver_env", return_value={"A": "B"}):
                with mock.patch.object(startup.subprocess, "run") as run_mock:
                    run_mock.return_value = mock.Mock(returncode=0, stderr="", stdout="")
                    startup._playwright_install(None)
        run_mock.assert_called_once()

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

    def test_playwright_install_streaming_paths(self) -> None:
        progress_updates: list[tuple[int | None, int | None, str | None]] = []

        def progress_cb(completed: int | None, total: int | None, description: str | None) -> None:
            progress_updates.append((completed, total, description))

        process = mock.Mock()
        process.stdout = iter(["downloading 10%\n", "working\n", "ready 80%\n"])
        process.wait.return_value = 0

        with mock.patch.object(
            startup, "_playwright_driver_command", return_value=("node", "cli.js")
        ):
            with mock.patch.object(startup, "_playwright_driver_env", return_value={}):
                with mock.patch.object(startup.subprocess, "Popen", return_value=process):
                    startup._playwright_install(progress_cb)

        self.assertGreaterEqual(len(progress_updates), 4)
        self.assertEqual(progress_updates[0], (0, 100, None))
        self.assertIn((10, 100, None), progress_updates)
        self.assertIn((11, 100, None), progress_updates)
        self.assertIn((80, 100, None), progress_updates)

    def test_playwright_install_streaming_missing_stdout_fails(self) -> None:
        process = mock.Mock()
        process.stdout = None

        with mock.patch.object(
            startup, "_playwright_driver_command", return_value=("node", "cli.js")
        ):
            with mock.patch.object(startup, "_playwright_driver_env", return_value={}):
                with mock.patch.object(startup.subprocess, "Popen", return_value=process):
                    with self.assertRaises(RuntimeError) as ctx:
                        startup._playwright_install(lambda *_: None)
        self.assertIn("unable to capture output", str(ctx.exception))

    def test_playwright_install_streaming_nonzero_exit_reports_recent_output(self) -> None:
        process = mock.Mock()
        process.stdout = iter(["line one\n", "line two\n"])
        process.wait.return_value = 2

        with mock.patch.object(
            startup, "_playwright_driver_command", return_value=("node", "cli.js")
        ):
            with mock.patch.object(startup, "_playwright_driver_env", return_value={}):
                with mock.patch.object(startup.subprocess, "Popen", return_value=process):
                    with self.assertRaises(RuntimeError) as ctx:
                        startup._playwright_install(lambda *_: None)
        self.assertIn("Playwright install failed", str(ctx.exception))
        self.assertIn("line one", str(ctx.exception))
        self.assertIn("line two", str(ctx.exception))

    def test_parse_playwright_progress_variants(self) -> None:
        self.assertEqual(startup._parse_playwright_progress(" 42% "), 42)
        self.assertIsNone(startup._parse_playwright_progress("no percent"))

    def test_parse_playwright_progress_invalid_integer_guard(self) -> None:
        fake_match = mock.Mock()
        fake_match.group.return_value = "not-a-number"
        fake_re = mock.Mock()
        fake_re.search.return_value = fake_match
        with mock.patch.object(startup, "_PLAYWRIGHT_PERCENT_RE", fake_re):
            self.assertIsNone(startup._parse_playwright_progress("ignored"))


if __name__ == "__main__":
    unittest.main()
