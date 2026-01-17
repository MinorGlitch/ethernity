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

from ethernity.cli.io.inputs import _load_input_files


class TestInputFiles(unittest.TestCase):
    def test_directory_recursion_and_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            nested = root / "nested"
            nested.mkdir(parents=True)
            (root / "a.txt").write_bytes(b"A")
            (nested / "b.txt").write_bytes(b"B")

            entries, base = _load_input_files([], [str(root)], None, allow_stdin=False)

            self.assertEqual(base, root.resolve())
            rels = [entry.relative_path for entry in entries]
            self.assertEqual(rels, ["a.txt", "nested/b.txt"])

    def test_duplicate_relative_paths_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "file.txt"
            path.write_bytes(b"data")
            with self.assertRaises(ValueError) as ctx:
                _load_input_files([str(path), str(path)], [], None, allow_stdin=False)
            self.assertIn("duplicate relative path", str(ctx.exception))

    def test_base_dir_outside_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "file.txt"
            path.write_bytes(b"data")
            base = root / "other"
            base.mkdir()
            with self.assertRaises(ValueError) as ctx:
                _load_input_files([str(path)], [], str(base), allow_stdin=False)
            self.assertIn("outside base dir", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
