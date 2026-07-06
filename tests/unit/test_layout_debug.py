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

import tempfile
import unittest
from pathlib import Path

from ethernity.render.layout_debug import layout_debug_json_path, resolve_layout_debug_dir


class TestLayoutDebug(unittest.TestCase):
    def test_resolve_layout_debug_dir_rejects_managed_inventory_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            managed = root / "out"
            debug = managed / "debug"

            with self.assertRaisesRegex(ValueError, "managed artifact inventory"):
                resolve_layout_debug_dir(debug, forbidden_dirs={"output": managed})

    def test_layout_debug_json_path_builds_sidecar_path(self) -> None:
        self.assertEqual(
            layout_debug_json_path("/tmp/debug", "qr_document"),
            "/tmp/debug/qr_document.layout.json",
        )

    def test_layout_debug_json_path_preserves_windows_string_style(self) -> None:
        self.assertEqual(
            layout_debug_json_path(r"C:\tmp\debug", "qr_document"),
            r"C:\tmp\debug\qr_document.layout.json",
        )
