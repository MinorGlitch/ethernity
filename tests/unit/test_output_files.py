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

import io
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from ethernity.cli.io.outputs import (
    _ensure_output_dir,
    _safe_join,
    _write_output,
    _write_recovered_outputs,
)


class TestOutputFiles(unittest.TestCase):
    def test_ensure_output_dir_rejects_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "backup-dir"
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                _ensure_output_dir(str(existing), "deadbeef")

    def test_safe_join_rejects_unsafe_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with self.assertRaisesRegex(ValueError, "unsafe output path"):
                _safe_join(base, "../outside.txt")
            with self.assertRaisesRegex(ValueError, "unsafe output path"):
                _safe_join(base, "/absolute/path.txt")

    def test_write_output_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "out.bin"
            _write_output(str(path), b"payload", quiet=True)
            self.assertEqual(path.read_bytes(), b"payload")

    def test_write_output_writes_stdout_when_path_is_none(self) -> None:
        fake_stdout = types.SimpleNamespace(buffer=io.BytesIO())
        with mock.patch("sys.stdout", new=fake_stdout):
            _write_output(None, b"stdout-bytes", quiet=True)
        self.assertEqual(fake_stdout.buffer.getvalue(), b"stdout-bytes")

    def test_write_recovered_outputs_rejects_empty_entries(self) -> None:
        with self.assertRaisesRegex(ValueError, "no payloads to write"):
            _write_recovered_outputs(None, [], quiet=True)

    def test_write_recovered_outputs_requires_output_for_multiple_files(self) -> None:
        entries = [
            (types.SimpleNamespace(path="a.txt"), b"A"),
            (types.SimpleNamespace(path="b.txt"), b"B"),
        ]
        with self.assertRaisesRegex(ValueError, "multiple files require --output"):
            _write_recovered_outputs(None, entries, quiet=True)

    def test_write_recovered_outputs_single_entry_writes_target_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "single.bin"
            entries = [(types.SimpleNamespace(path="ignored.txt"), b"single")]
            _write_recovered_outputs(str(out_path), entries, quiet=True)
            self.assertEqual(out_path.read_bytes(), b"single")

    def test_write_recovered_outputs_multiple_entries_writes_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "recovered"
            entries = [
                (types.SimpleNamespace(path="dir/a.txt"), b"A"),
                (types.SimpleNamespace(path="b.txt"), b"B"),
            ]
            _write_recovered_outputs(str(out_dir), entries, quiet=True)
            self.assertEqual((out_dir / "dir" / "a.txt").read_bytes(), b"A")
            self.assertEqual((out_dir / "b.txt").read_bytes(), b"B")

    def test_write_recovered_outputs_rejects_unsafe_entry_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "recovered"
            entries = [
                (types.SimpleNamespace(path="../escape.txt"), b"A"),
                (types.SimpleNamespace(path="ok.txt"), b"B"),
            ]
            with self.assertRaisesRegex(ValueError, "unsafe output path"):
                _write_recovered_outputs(str(out_dir), entries, quiet=True)


if __name__ == "__main__":
    unittest.main()
