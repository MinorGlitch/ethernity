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
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.cli.shared.io.inputs import _directory_root_label, _load_input_files


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
    def test_directory_root_label_accepts_filesystem_root(self) -> None:
        root_anchor = Path.cwd().anchor or "/"
        label = _directory_root_label(Path(root_anchor))
        self.assertTrue(label)
        self.assertNotIn("/", label)
        self.assertNotIn("\\", label)

    def test_directory_root_label_windows_drive_fallback(self) -> None:
        path = mock.MagicMock()
        path.expanduser.return_value = path
        resolved = mock.MagicMock()
        resolved.name = ""
        resolved.anchor = "C:\\"
        path.resolve.return_value = resolved
        self.assertEqual(_directory_root_label(path), "drive-c")

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

    def test_directory_input_roots_preserve_leaf_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_label = " demo" if os.name == "nt" else " demo "
            root = Path(tmpdir) / root_label
            root.mkdir()
            (root / "a.txt").write_bytes(b"A")

            _entries, _base, _input_origin, input_roots = _load_input_files(
                [], [str(root)], None, allow_stdin=False
            )

        self.assertEqual(input_roots, [root_label])

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
        with self.assertRaisesRegex(FileNotFoundError, "input dir not found"):
            _load_input_files([], ["/no/such/dir"], None, allow_stdin=False)

    def test_input_dir_not_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "input dir is not a directory"):
                _load_input_files([], [str(path)], None, allow_stdin=False)

    def test_input_file_not_found(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "input file not found"):
            _load_input_files(["/no/such/file"], [], None, allow_stdin=False)

    def test_input_path_not_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            with mock.patch("pathlib.Path.is_dir", return_value=False):
                with self.assertRaisesRegex(ValueError, "input path is not a file"):
                    _load_input_files([str(path)], [], None, allow_stdin=False)

    def test_rejects_symlinked_input_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target.txt"
            link = root / "link.txt"
            target.write_text("secret", encoding="utf-8")
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "input path must not be a symlink"):
                _load_input_files([str(link)], [], None, allow_stdin=False)

    def test_rejects_symlinked_input_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            link = root / "link"
            target.mkdir()
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "input dir must not be a symlink"):
                _load_input_files([], [str(link)], None, allow_stdin=False)

    def test_rejects_symlinked_file_inside_input_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_dir = root / "input"
            target = root / "outside.txt"
            link = input_dir / "linked.txt"
            input_dir.mkdir()
            target.write_text("outside", encoding="utf-8")
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "input file must not be a symlink"):
                _load_input_files([], [str(input_dir)], None, allow_stdin=False)

    def test_rejects_symlinked_base_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            base_link = root / "base-link"
            file_path = target / "file.txt"
            target.mkdir()
            file_path.write_text("data", encoding="utf-8")
            try:
                base_link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "base dir must not be a symlink"):
                _load_input_files([str(file_path)], [], str(base_link), allow_stdin=False)

    def test_empty_stdin_rejected(self) -> None:
        with mock.patch("ethernity.cli.shared.io.inputs.sys.stdin", new=io.StringIO("")):
            with self.assertRaisesRegex(ValueError, "stdin input is empty"):
                _load_input_files(["-"], [], None, allow_stdin=True)

    def test_duplicate_relative_path_from_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "data.txt"
            file_path.write_text("file", encoding="utf-8")
            with mock.patch(
                "ethernity.cli.shared.io.inputs.sys.stdin", new=io.StringIO("stdin-data")
            ):
                with self.assertRaisesRegex(ValueError, "duplicate relative path 'data.txt'"):
                    _load_input_files([str(file_path), "-"], [], None, allow_stdin=True)

    def test_input_file_accepts_size_previously_over_early_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "big.bin"
            file_path.write_bytes(b"abcde")
            entries, _, _, _ = _load_input_files([str(file_path)], [], None, allow_stdin=False)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].relative_path, "big.bin")
        self.assertEqual(entries[0].data, b"abcde")

    def test_input_files_accept_cumulative_size_previously_over_early_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "one.bin"
            second = Path(tmpdir) / "two.bin"
            first.write_bytes(b"abc")
            second.write_bytes(b"def")
            entries, _, _, _ = _load_input_files(
                [str(first), str(second)],
                [],
                None,
                allow_stdin=False,
            )
        self.assertEqual(sum(len(entry.data) for entry in entries), 6)

    def test_input_files_accept_exact_cumulative_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "one.bin"
            second = Path(tmpdir) / "two.bin"
            first.write_bytes(b"abc")
            second.write_bytes(b"de")
            entries, _, _, _ = _load_input_files(
                [str(first), str(second)],
                [],
                None,
                allow_stdin=False,
            )
        self.assertEqual(sum(len(entry.data) for entry in entries), 5)

    def test_input_file_rejects_size_over_payload_bound_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "big.bin"
            file_path.write_bytes(b"abcde")
            with (
                mock.patch("ethernity.cli.shared.io.inputs.MAX_DECOMPRESSED_PAYLOAD_BYTES", 4),
                mock.patch(
                    "ethernity.cli.shared.io.inputs._read_planned_input_file",
                    side_effect=AssertionError("should not read"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "MAX_DECOMPRESSED_PAYLOAD_BYTES"):
                    _load_input_files([str(file_path)], [], None, allow_stdin=False)

    def test_input_files_reject_cumulative_size_over_payload_bound_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "one.bin"
            second = Path(tmpdir) / "two.bin"
            first.write_bytes(b"abc")
            second.write_bytes(b"def")
            with (
                mock.patch("ethernity.cli.shared.io.inputs.MAX_DECOMPRESSED_PAYLOAD_BYTES", 5),
                mock.patch(
                    "ethernity.cli.shared.io.inputs._read_planned_input_file",
                    side_effect=AssertionError("should not read"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "MAX_DECOMPRESSED_PAYLOAD_BYTES"):
                    _load_input_files(
                        [str(first), str(second)],
                        [],
                        None,
                        allow_stdin=False,
                    )

    def test_input_files_reject_manifest_file_count_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "one.bin"
            second = Path(tmpdir) / "two.bin"
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            with (
                mock.patch("ethernity.cli.shared.io.inputs.MAX_MANIFEST_FILES", 1),
                mock.patch(
                    "ethernity.cli.shared.io.inputs._read_planned_input_file",
                    side_effect=AssertionError("should not read"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "MAX_MANIFEST_FILES"):
                    _load_input_files(
                        [str(first), str(second)],
                        [],
                        None,
                        allow_stdin=False,
                    )

    def test_rejects_input_file_swapped_for_symlink_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "input.txt"
            target = root / "target.txt"
            file_path.write_text("original", encoding="utf-8")
            target.write_text("target", encoding="utf-8")
            real_open = os.open

            def _swap_then_open(path, flags):
                file_path.unlink()
                try:
                    file_path.symlink_to(target)
                except OSError as exc:
                    self.skipTest(f"symlinks unavailable: {exc}")
                return real_open(path, flags)

            with mock.patch("ethernity.cli.shared.io.inputs.os.open", side_effect=_swap_then_open):
                with self.assertRaisesRegex(
                    ValueError,
                    "input file must not be a symlink|input file changed while opening",
                ):
                    _load_input_files([str(file_path)], [], None, allow_stdin=False)

    def test_stdin_rejects_cumulative_size_over_payload_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "one.bin"
            file_path.write_bytes(b"abc")
            with (
                mock.patch("ethernity.cli.shared.io.inputs.MAX_DECOMPRESSED_PAYLOAD_BYTES", 5),
                mock.patch("ethernity.cli.shared.io.inputs.sys.stdin", new=io.StringIO("def")),
            ):
                with self.assertRaisesRegex(ValueError, "MAX_DECOMPRESSED_PAYLOAD_BYTES"):
                    _load_input_files([str(file_path), "-"], [], None, allow_stdin=True)

    def test_stdin_counts_toward_manifest_file_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "one.bin"
            file_path.write_bytes(b"abc")
            with (
                mock.patch("ethernity.cli.shared.io.inputs.MAX_MANIFEST_FILES", 1),
                mock.patch("ethernity.cli.shared.io.inputs.sys.stdin", new=io.StringIO("def")),
            ):
                with self.assertRaisesRegex(ValueError, "MAX_MANIFEST_FILES"):
                    _load_input_files([str(file_path), "-"], [], None, allow_stdin=True)

    def test_commonpath_error_reports_different_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            left = Path(tmpdir) / "left.txt"
            right = Path(tmpdir) / "right.txt"
            left.write_text("left", encoding="utf-8")
            right.write_text("right", encoding="utf-8")
            with mock.patch(
                "ethernity.cli.shared.io.inputs.os.path.commonpath",
                side_effect=ValueError("different drives"),
            ):
                with self.assertRaisesRegex(ValueError, "different roots"):
                    _load_input_files([str(left), str(right)], [], None, allow_stdin=False)

    def test_invalid_utf8_relative_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "file.txt"
            path.write_bytes(b"data")
            with mock.patch(
                "ethernity.cli.shared.io.inputs.normalize_path",
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
