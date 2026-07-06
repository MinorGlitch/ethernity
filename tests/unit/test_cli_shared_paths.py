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

from ethernity.cli.shared.paths import display_parent_path


class TestCliSharedPaths(unittest.TestCase):
    def test_display_parent_path_preserves_posix_string_style(self) -> None:
        self.assertEqual(display_parent_path("/tmp/out/qr_document.pdf"), "/tmp/out")

    def test_display_parent_path_preserves_windows_string_style(self) -> None:
        self.assertEqual(
            display_parent_path(r"C:\tmp\out\qr_document.pdf"),
            r"C:\tmp\out",
        )

    def test_display_parent_path_uses_host_style_for_path_objects(self) -> None:
        self.assertEqual(
            display_parent_path(Path("out") / "qr_document.pdf"),
            str(Path("out")),
        )


if __name__ == "__main__":
    unittest.main()
