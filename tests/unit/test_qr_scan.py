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

from ethernity.qr.scan import QrScanError, _expand_paths


class TestQrScanInputs(unittest.TestCase):
    def test_invalid_scan_paths_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cases = (
                ("missing-path", [Path("does-not-exist")]),
                ("empty-directory", [Path(tmpdir)]),
            )
            for name, paths in cases:
                with self.subTest(case=name):
                    with self.assertRaises(QrScanError):
                        list(_expand_paths(paths))


if __name__ == "__main__":
    unittest.main()
