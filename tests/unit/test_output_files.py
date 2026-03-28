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
import os
import stat
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from ethernity.cli.shared.io.outputs import (
    _ensure_output_dir,
    _safe_join,
    _write_output,
    _write_recovered_outputs,
)


def _home_env(home: Path) -> dict[str, str]:
    env = {"HOME": str(home), "USERPROFILE": str(home)}
    drive, tail = os.path.splitdrive(str(home))
    if drive:
        env["HOMEDRIVE"] = drive
        env["HOMEPATH"] = tail or "\\"
    return env


class TestOutputFiles(unittest.TestCase):
    def test_ensure_output_dir_rejects_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "backup-dir"
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                _ensure_output_dir(str(existing), "deadbeef")

    def test_ensure_output_dir_uses_existing_directory_as_parent_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir) / "backups"
            parent.mkdir()
            created = _ensure_output_dir(
                str(parent),
                "deadbeef",
                existing_directory_is_parent=True,
            )
            self.assertEqual(created, str(parent / "backup-deadbeef"))
            self.assertTrue((parent / "backup-deadbeef").is_dir())

    def test_safe_join_rejects_unsafe_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with self.assertRaisesRegex(ValueError, "unsafe output path"):
                _safe_join(base, "../outside.txt")
            absolute_path = str(Path(base.anchor) / "absolute" / "path.txt")
            with self.assertRaisesRegex(ValueError, "unsafe output path"):
                _safe_join(base, absolute_path)

    def test_write_output_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "out.bin"
            _write_output(str(path), b"payload")
            self.assertEqual(path.read_bytes(), b"payload")

    def test_write_output_expands_user_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            path = home / "out.bin"
            with mock.patch.dict("os.environ", _home_env(home), clear=False):
                _write_output("~/out.bin", b"payload")
            self.assertEqual(path.read_bytes(), b"payload")

    def test_permissions_hardened_on_posix(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX-only permission assertion")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "secure"
            _ensure_output_dir(str(out_dir), "deadbeef")
            out_file = out_dir / "payload.bin"
            _write_output(str(out_file), b"payload")

            dir_mode = stat.S_IMODE(out_dir.stat().st_mode)
            file_mode = stat.S_IMODE(out_file.stat().st_mode)
            self.assertEqual(dir_mode, 0o700)
            self.assertEqual(file_mode, 0o600)

    def test_permission_hardening_failures_are_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "secure"
            out_file = out_dir / "payload.bin"
            with mock.patch("ethernity.cli.shared.io.outputs._is_posix", return_value=True):
                with mock.patch("pathlib.Path.chmod", side_effect=OSError("denied")):
                    _ensure_output_dir(str(out_dir), "deadbeef")
                    _write_output(str(out_file), b"payload")

    def test_write_output_writes_stdout_when_path_is_none(self) -> None:
        fake_stdout = types.SimpleNamespace(buffer=io.BytesIO())
        with mock.patch("sys.stdout", new=fake_stdout):
            _write_output(None, b"stdout-bytes")
        self.assertEqual(fake_stdout.buffer.getvalue(), b"stdout-bytes")

    def test_write_recovered_outputs_rejects_empty_entries(self) -> None:
        with self.assertRaisesRegex(ValueError, "no payloads to write"):
            _write_recovered_outputs(None, [])

    def test_write_recovered_outputs_requires_output_for_multiple_files(self) -> None:
        entries = [
            (types.SimpleNamespace(path="a.txt"), b"A"),
            (types.SimpleNamespace(path="b.txt"), b"B"),
        ]
        with self.assertRaisesRegex(ValueError, "multiple files require --output"):
            _write_recovered_outputs(None, entries)

    def test_write_recovered_outputs_single_entry_writes_target_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "single.bin"
            entries = [(types.SimpleNamespace(path="ignored.txt"), b"single")]
            _write_recovered_outputs(str(out_path), entries)
            self.assertEqual(out_path.read_bytes(), b"single")

    def test_write_recovered_outputs_single_entry_directory_mode_writes_under_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "vault"
            entries = [(types.SimpleNamespace(path="nested/file.txt"), b"single")]
            _write_recovered_outputs(
                str(out_dir),
                entries,
                single_entry_output_is_directory=True,
            )
            self.assertEqual((out_dir / "nested" / "file.txt").read_bytes(), b"single")

    def test_write_recovered_outputs_single_entry_existing_directory_writes_under_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "vault"
            out_dir.mkdir()
            entries = [(types.SimpleNamespace(path="payload.bin"), b"single")]
            _write_recovered_outputs(str(out_dir), entries)
            self.assertEqual((out_dir / "payload.bin").read_bytes(), b"single")

    def test_write_recovered_outputs_multiple_entries_writes_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "recovered"
            entries = [
                (types.SimpleNamespace(path="dir/a.txt"), b"A"),
                (types.SimpleNamespace(path="b.txt"), b"B"),
            ]
            _write_recovered_outputs(str(out_dir), entries)
            self.assertEqual((out_dir / "dir" / "a.txt").read_bytes(), b"A")
            self.assertEqual((out_dir / "b.txt").read_bytes(), b"B")

    def test_write_recovered_outputs_replaces_existing_directory_authoritatively(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "recovered"
            out_dir.mkdir()
            (out_dir / "stale.txt").write_text("stale", encoding="utf-8")
            (out_dir / "kept.txt").write_text("old", encoding="utf-8")
            entries = [
                (types.SimpleNamespace(path="kept.txt"), b"new"),
                (types.SimpleNamespace(path="nested/fresh.txt"), b"fresh"),
            ]

            _write_recovered_outputs(str(out_dir), entries)

            self.assertFalse((out_dir / "stale.txt").exists())
            self.assertEqual((out_dir / "kept.txt").read_bytes(), b"new")
            self.assertEqual((out_dir / "nested" / "fresh.txt").read_bytes(), b"fresh")

    def test_write_recovered_outputs_rejects_unsafe_entry_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "recovered"
            entries = [
                (types.SimpleNamespace(path="../escape.txt"), b"A"),
                (types.SimpleNamespace(path="ok.txt"), b"B"),
            ]
            with self.assertRaisesRegex(ValueError, "unsafe output path"):
                _write_recovered_outputs(str(out_dir), entries)

    def test_write_recovered_outputs_rejects_case_colliding_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "recovered"
            entries = [
                (types.SimpleNamespace(path="Readme.txt"), b"A"),
                (types.SimpleNamespace(path="README.txt"), b"B"),
            ]
            with mock.patch(
                "ethernity.cli.shared.io.outputs._is_directory_case_sensitive",
                return_value=False,
            ):
                with self.assertRaisesRegex(ValueError, "collide on this filesystem"):
                    _write_recovered_outputs(str(out_dir), entries)

    def test_write_recovered_outputs_stdout_invokes_callback(self) -> None:
        fake_stdout = types.SimpleNamespace(buffer=io.BytesIO())
        calls: list[tuple[str, str, int, int]] = []

        def _capture(
            entry: object, _data: bytes, written_path: str, index: int, total: int
        ) -> None:
            calls.append((getattr(entry, "path", ""), written_path, index, total))

        with mock.patch("sys.stdout", new=fake_stdout):
            _write_recovered_outputs(
                None,
                [(types.SimpleNamespace(path="stdout.bin"), b"stdout-bytes")],
                on_entry_written=_capture,
            )

        self.assertEqual(fake_stdout.buffer.getvalue(), b"stdout-bytes")
        self.assertEqual(calls, [("stdout.bin", "-", 1, 1)])

    def test_ensure_output_dir_expands_user_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            with mock.patch.dict("os.environ", _home_env(home), clear=False):
                out_dir = _ensure_output_dir("~/vault", "deadbeef")
            self.assertEqual(out_dir, str(home / "vault"))
            self.assertTrue((home / "vault").is_dir())


if __name__ == "__main__":
    unittest.main()
