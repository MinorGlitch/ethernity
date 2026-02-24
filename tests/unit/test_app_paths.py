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

import unittest
from pathlib import Path
from unittest import mock

from ethernity.core import app_paths


class TestAppPaths(unittest.TestCase):
    def test_config_derived_paths_use_user_config_root(self) -> None:
        with mock.patch.object(
            app_paths, "user_config_dir_path", return_value=Path("/cfg/ethernity")
        ):
            self.assertEqual(app_paths.user_config_file_path(), Path("/cfg/ethernity/config.toml"))
            self.assertEqual(app_paths.user_templates_root_path(), Path("/cfg/ethernity/templates"))
            self.assertEqual(
                app_paths.user_templates_design_path("forge"),
                Path("/cfg/ethernity/templates/forge"),
            )

    def test_cache_state_log_runtime_paths(self) -> None:
        with mock.patch.object(app_paths, "user_cache_dir", return_value="/cache/ethernity"):
            self.assertEqual(app_paths.user_cache_dir_path(), Path("/cache/ethernity"))
        with mock.patch.object(app_paths, "user_state_dir", return_value="/state/ethernity"):
            self.assertEqual(app_paths.user_state_dir_path(), Path("/state/ethernity"))
        with mock.patch.object(app_paths, "user_log_dir", return_value="/logs/ethernity"):
            self.assertEqual(app_paths.user_log_dir_path(), Path("/logs/ethernity"))
        with mock.patch.object(
            app_paths, "user_cache_dir_path", return_value=Path("/cache/ethernity")
        ):
            self.assertEqual(
                app_paths.runtime_scratch_dir_path(),
                Path("/cache/ethernity/runtime"),
            )

    def test_playwright_cache_dir_is_separate_cache_namespace(self) -> None:
        with mock.patch.object(
            app_paths,
            "user_cache_dir",
            return_value="/cache/ms-playwright",
        ) as cache_mock:
            self.assertEqual(
                app_paths.playwright_browsers_cache_dir(),
                Path("/cache/ms-playwright"),
            )
        cache_mock.assert_called_once_with(app_paths.PLAYWRIGHT_CACHE_APP_NAME, appauthor=False)


if __name__ == "__main__":
    unittest.main()
