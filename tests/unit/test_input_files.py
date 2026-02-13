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

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.cli.io.inputs import _load_input_files


class _FakeProgress:
    def __init__(self) -> None:
        self._next_id = 0
        self.events: list[tuple[str, object]] = []

    def add_task(self, description: str, total=None) -> int:
        self._next_id += 1
        self.events.append(("add", (description, total)))
        return self._next_id

    def update(self, task_id: int, **kwargs) -> None:
        self.events.append(("update", (task_id, kwargs)))

    def refresh(self) -> None:
        self.events.append(("refresh", None))

    def advance(self, task_id: int) -> None:
        self.events.append(("advance", task_id))


class TestInputFiles(unittest.TestCase):
    def test_directory_recursion_and_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            nested = root / "nested"
            nested.mkdir(parents=True)
            (root / "a.txt").write_bytes(b"A")
            (nested / "b.txt").write_bytes(b"B")

            entries, base, input_origin, input_roots = _load_input_files(
                [], [str(root)], None, allow_stdin=False
            )

            self.assertEqual(base, root.resolve())
            self.assertEqual(input_origin, "directory")
            self.assertEqual(input_roots, ["root"])
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

    def test_stdin_not_allowed(self) -> None:
        with self.assertRaisesRegex(ValueError, "stdin input is not supported here"):
            _load_input_files(["-"], [], None, allow_stdin=False)

    def test_no_input_files_found(self) -> None:
        with self.assertRaisesRegex(ValueError, "no input files found"):
            _load_input_files([], [], None, allow_stdin=False)

    def test_input_dir_not_found(self) -> None:
        with self.assertRaisesRegex(ValueError, "input dir not found"):
            _load_input_files([], ["/no/such/dir"], None, allow_stdin=False)

    def test_input_dir_not_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "input dir is not a directory"):
                _load_input_files([], [str(path)], None, allow_stdin=False)

    def test_input_file_not_found(self) -> None:
        with self.assertRaisesRegex(ValueError, "input file not found"):
            _load_input_files(["/no/such/file"], [], None, allow_stdin=False)

    def test_input_path_not_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            with mock.patch("pathlib.Path.is_dir", return_value=False):
                with self.assertRaisesRegex(ValueError, "input path is not a file"):
                    _load_input_files([str(path)], [], None, allow_stdin=False)

    def test_empty_stdin_rejected(self) -> None:
        with mock.patch("ethernity.cli.io.inputs.sys.stdin", new=io.StringIO("")):
            with self.assertRaisesRegex(ValueError, "stdin input is empty"):
                _load_input_files(["-"], [], None, allow_stdin=True)

    def test_duplicate_relative_path_from_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "data.txt"
            file_path.write_text("file", encoding="utf-8")
            with mock.patch("ethernity.cli.io.inputs.sys.stdin", new=io.StringIO("stdin-data")):
                with self.assertRaisesRegex(ValueError, "duplicate relative path 'data.txt'"):
                    _load_input_files([str(file_path), "-"], [], None, allow_stdin=True)

    def test_commonpath_error_reports_different_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            left = Path(tmpdir) / "left.txt"
            right = Path(tmpdir) / "right.txt"
            left.write_text("left", encoding="utf-8")
            right.write_text("right", encoding="utf-8")
            with mock.patch(
                "ethernity.cli.io.inputs.os.path.commonpath",
                side_effect=ValueError("different drives"),
            ):
                with self.assertRaisesRegex(ValueError, "different roots"):
                    _load_input_files([str(left), str(right)], [], None, allow_stdin=False)

    def test_invalid_utf8_relative_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "file.txt"
            path.write_bytes(b"data")
            with mock.patch(
                "ethernity.cli.io.inputs.normalize_path",
                side_effect=ValueError("invalid utf8"),
            ):
                with self.assertRaisesRegex(ValueError, "not valid UTF-8"):
                    _load_input_files([str(path)], [], None, allow_stdin=False)

    def test_progress_updates_are_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root"
            root.mkdir(parents=True)
            for idx in range(11):
                (root / f"file-{idx}.txt").write_text(f"payload-{idx}", encoding="utf-8")

            progress = _FakeProgress()
            entries, _, input_origin, input_roots = _load_input_files(
                [],
                [str(root)],
                None,
                allow_stdin=False,
                progress=progress,
            )

        self.assertEqual(len(entries), 11)
        self.assertEqual(input_origin, "directory")
        self.assertEqual(input_roots, ["root"])
        update_events = [event for event in progress.events if event[0] == "update"]
        self.assertTrue(update_events)
        descriptions = [payload[1].get("description", "") for _, payload in update_events]
        self.assertTrue(any("Scanning input files..." in desc for desc in descriptions))
        self.assertTrue(any("Reading input files..." in desc for desc in descriptions))

    def test_file_only_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "file.txt"
            file_path.write_text("x", encoding="utf-8")
            _entries, _base, input_origin, input_roots = _load_input_files(
                [str(file_path)],
                [],
                None,
                allow_stdin=False,
            )
        self.assertEqual(input_origin, "file")
        self.assertEqual(input_roots, [])

    def test_mixed_origin_file_and_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            single = root / "single.txt"
            single.write_text("single", encoding="utf-8")
            folder = root / "folder"
            folder.mkdir()
            (folder / "nested.txt").write_text("nested", encoding="utf-8")

            _entries, _base, input_origin, input_roots = _load_input_files(
                [str(single)],
                [str(folder)],
                None,
                allow_stdin=False,
            )

        self.assertEqual(input_origin, "mixed")
        self.assertEqual(input_roots, ["folder"])

    def test_directory_roots_preserve_duplicates_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "a" / "data"
            second = root / "b" / "data"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "one.txt").write_text("one", encoding="utf-8")
            (second / "two.txt").write_text("two", encoding="utf-8")

            _entries, _base, input_origin, input_roots = _load_input_files(
                [],
                [str(first), str(second)],
                None,
                allow_stdin=False,
            )

        self.assertEqual(input_origin, "directory")
        self.assertEqual(input_roots, ["data", "data"])


if __name__ == "__main__":
    unittest.main()
