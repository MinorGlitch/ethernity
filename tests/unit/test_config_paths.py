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

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ethernity.config.paths as config_paths


class TestConfigPaths(unittest.TestCase):
    def test_resources_root_uses_package_file_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            resources_dir = Path(tmpdir) / "resources"
            resources_dir.mkdir(parents=True, exist_ok=True)
            init_path = resources_dir / "__init__.py"
            init_path.write_text('"""resources"""', encoding="utf-8")

            with mock.patch.object(config_paths.resources_pkg, "__file__", str(init_path)):
                self.assertEqual(config_paths._resources_root(), resources_dir.resolve())


if __name__ == "__main__":
    unittest.main()
