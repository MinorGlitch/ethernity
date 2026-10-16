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
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from ethernity.tasks.file_summary import display_path
from ethernity.workflows.shared.paths import display_parent_path

pytestmark = pytest.mark.portability


class TestPathDisplay(unittest.TestCase):
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


@pytest.mark.parametrize(
    "home,path,expected",
    [
        (PurePosixPath("/home/alex"), "/home/alex", "~"),
        (PurePosixPath("/home/alex"), "/home/alex/docs/a.txt", "~/docs/a.txt"),
        (PurePosixPath("/home/alex"), "/home/alex-other/a.txt", "/home/alex-other/a.txt"),
        (PurePosixPath("/home/alex"), "docs/a.txt", "docs/a.txt"),
        (PurePosixPath("/home/alex"), r"/home/alex/a\b.txt", r"~/a\b.txt"),
        (PureWindowsPath("C:/Users/Alex"), r"C:\Users\Alex", "~"),
        (PureWindowsPath("C:/Users/Alex"), r"C:\Users\Alex\docs\a.txt", r"~\docs\a.txt"),
        (PureWindowsPath("C:/Users/Alex"), "c:/users/alex/docs/a.txt", r"~\docs\a.txt"),
        (
            PureWindowsPath("C:/Users/Alex"),
            r"C:\Users\Alex-other\a.txt",
            r"C:\Users\Alex-other\a.txt",
        ),
        (PureWindowsPath("C:/Users/Alex"), r"D:\Users\Alex\a.txt", r"D:\Users\Alex\a.txt"),
        (PureWindowsPath("//server/share/alex"), r"\\server\share\alex\a.txt", r"~\a.txt"),
    ],
)
def test_home_shortening_respects_path_flavour(monkeypatch, home, path, expected) -> None:
    monkeypatch.setattr(Path, "home", lambda: home)
    assert display_path(path) == expected


def test_display_shortens_the_native_home_without_resolving_files(tmp_path, set_home) -> None:
    set_home(tmp_path)
    missing = tmp_path / "not-created" / "records.txt"
    assert display_path(missing) == str(Path("~") / "not-created" / "records.txt")
    assert not missing.exists()


@pytest.mark.parametrize("limit", [0, 1, 3, 10, 24, 56])
def test_long_path_display_respects_length_limit(limit) -> None:
    path = "C:/another-drive/very-long-folder-name/another-directory/backup-documents.pdf"
    assert len(display_path(path, max_chars=limit)) <= limit
