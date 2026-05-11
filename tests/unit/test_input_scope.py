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

from ethernity.cli.shared.input_scope import load_input_scope, summarize_input_scope_diff


class TestInputScope(unittest.TestCase):
    def test_load_input_scope_and_diff_selected_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            selected = root / "selected"
            selected.mkdir()
            item = selected / "item.txt"
            item.write_text("new", encoding="utf-8")
            scope = load_input_scope(
                raw_files=(),
                raw_directories=(str(selected),),
                base_dir_arg=str(root),
                allow_stdin=False,
            )

            assert scope is not None
            diff = summarize_input_scope_diff(
                current_files={
                    "selected/item.txt": (b"old", int(item.stat().st_mtime)),
                    "selected/missing.txt": (b"old", None),
                    "outside.txt": (b"old", None),
                },
                scope=scope,
            )

        self.assertEqual(diff.changed_paths, ("selected/item.txt",))
        self.assertEqual(diff.missing_paths, ("selected/missing.txt",))
        self.assertEqual(diff.new_paths, ())
        self.assertEqual(diff.unchanged_paths, ())
