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

import importlib.metadata
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity import version as version_module


class TestVersion(unittest.TestCase):
    def setUp(self) -> None:
        version_module.get_ethernity_version.cache_clear()

    def tearDown(self) -> None:
        version_module.get_ethernity_version.cache_clear()

    @mock.patch("ethernity.version.importlib.metadata.version", return_value="1.2.3")
    def test_get_ethernity_version_from_metadata(self, _version: mock.MagicMock) -> None:
        self.assertEqual(version_module.get_ethernity_version(), "1.2.3")

    @mock.patch(
        "ethernity.version.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError,
    )
    def test_get_ethernity_version_from_pyproject_when_metadata_missing(
        self,
        _version: mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject = Path(tmpdir) / "pyproject.toml"
            pyproject.write_text(
                '[project]\nname = "ethernity"\nversion = "9.8.7"\n',
                encoding="utf-8",
            )
            with mock.patch("ethernity.version._PYPROJECT_PATH", pyproject):
                self.assertEqual(version_module.get_ethernity_version(), "9.8.7")

    @mock.patch(
        "ethernity.version.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError,
    )
    def test_get_ethernity_version_returns_empty_when_all_sources_missing(
        self,
        _version: mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_pyproject = Path(tmpdir) / "missing.toml"
            with mock.patch("ethernity.version._PYPROJECT_PATH", missing_pyproject):
                self.assertEqual(version_module.get_ethernity_version(), "")


if __name__ == "__main__":
    unittest.main()
