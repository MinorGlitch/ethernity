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

import shutil
import subprocess
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "recovery_parse_vectors.json"
_SCRIPT_PATH = _PROJECT_ROOT / "kit" / "scripts" / "run_parse_vectors.mjs"


class TestKitVectors(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node runtime is required")
    def test_kit_parse_vectors(self) -> None:
        result = subprocess.run(
            ["node", str(_SCRIPT_PATH), str(_FIXTURE_PATH)],
            cwd=_PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=result.stderr.strip() or result.stdout.strip(),
        )


if __name__ == "__main__":
    unittest.main()
