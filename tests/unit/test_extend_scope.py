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

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.extensions import LogicalFileState
from ethernity.workflows.extension.request import ExtensionRequest
from ethernity.workflows.extension.scope import load_selected_scope, summarize_scope_diff


def _logical_file(path: str, data: bytes, *, mtime: int | None) -> LogicalFileState:
    return LogicalFileState(
        path=path,
        size=len(data),
        sha256=hashlib.sha256(data).digest(),
        mtime=mtime,
        data=data,
    )


class TestExtendScope(unittest.TestCase):
    def test_load_selected_scope_tracks_normalized_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            nested = workspace / "docs" / "nested"
            workspace.mkdir()
            nested.mkdir(parents=True)
            (workspace / "alpha.txt").write_text("alpha", encoding="utf-8")
            (nested / "beta.txt").write_text("beta", encoding="utf-8")

            scope = load_selected_scope(
                ExtensionRequest(
                    input_paths=(str(workspace / "alpha.txt"),),
                    input_directories=(str(nested),),
                    base_directory=str(workspace),
                )
            )

        assert scope is not None
        self.assertEqual(scope.input_origin, "mixed")
        self.assertEqual(scope.exact_paths, ("alpha.txt",))
        self.assertEqual(scope.directory_prefixes, ("docs/nested",))
        self.assertEqual(scope.input_roots, ("nested",))
        self.assertEqual(scope.total_bytes, 9)
        self.assertEqual(
            scope.to_inspection_payload(),
            {
                "files": [str(workspace / "alpha.txt")],
                "directories": [str(nested)],
                "base_dir": str(workspace),
                "file_count": 2,
                "total_bytes": 9,
                "input_origin": "mixed",
                "input_roots": ["nested"],
            },
        )

    def test_summarize_scope_diff_reports_new_changed_unchanged_and_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            docs = workspace / "docs"
            docs.mkdir(parents=True)
            (workspace / "alpha.txt").write_text("alpha", encoding="utf-8")
            (docs / "beta.txt").write_text("beta-new", encoding="utf-8")
            (docs / "gamma.txt").write_text("gamma", encoding="utf-8")

            scope = load_selected_scope(
                ExtensionRequest(
                    input_paths=(str(workspace / "alpha.txt"),),
                    input_directories=(str(docs),),
                    base_directory=str(workspace),
                )
            )

        assert scope is not None
        alpha_input = next(item for item in scope.input_files if item.relative_path == "alpha.txt")
        diff = summarize_scope_diff(
            (
                _logical_file("alpha.txt", b"alpha", mtime=alpha_input.mtime),
                _logical_file("docs/beta.txt", b"beta-old", mtime=2),
                _logical_file("docs/missing.txt", b"missing", mtime=3),
            ),
            scope,
        )

        self.assertEqual(diff.new_paths, ("docs/gamma.txt",))
        self.assertEqual(diff.changed_paths, ("docs/beta.txt",))
        self.assertEqual(diff.unchanged_paths, ("alpha.txt",))
        self.assertEqual(diff.missing_paths, ("docs/missing.txt",))
        self.assertEqual(diff.ambiguous_path_aliases, ())
        self.assertEqual(
            diff.to_payload(),
            {
                "new_paths": ["docs/gamma.txt"],
                "changed_paths": ["docs/beta.txt"],
                "unchanged_paths": ["alpha.txt"],
                "missing_paths": ["docs/missing.txt"],
                "new_count": 1,
                "changed_count": 1,
                "unchanged_count": 1,
                "missing_count": 1,
            },
        )

    def test_summarize_scope_diff_flags_exact_file_path_alias_without_base_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            docs = workspace / "docs"
            docs.mkdir(parents=True)
            (docs / "a.txt").write_text("new", encoding="utf-8")

            scope = load_selected_scope(
                ExtensionRequest(
                    input_paths=(str(docs / "a.txt"),),
                )
            )

        assert scope is not None
        diff = summarize_scope_diff(
            (_logical_file("docs/a.txt", b"old", mtime=1),),
            scope,
        )

        self.assertEqual(diff.new_paths, ("a.txt",))
        self.assertEqual(diff.missing_paths, ())
        self.assertEqual(diff.ambiguous_path_aliases, (("a.txt", "docs/a.txt"),))

    def test_load_selected_scope_accepts_stdin_as_documented_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()

            with mock.patch("sys.stdin", io.StringIO("stdin payload")):
                scope = load_selected_scope(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_paths=("-",),
                    )
                )

        assert scope is not None
        self.assertEqual(scope.input_origin, "file")
        self.assertEqual(scope.input_roots, ())
        self.assertEqual(scope.exact_paths, ())
        self.assertEqual(scope.directory_prefixes, ())
        self.assertEqual(len(scope.input_files), 1)
        self.assertEqual(scope.input_files[0].relative_path, "data.txt")
        self.assertEqual(scope.input_files[0].data, b"stdin payload")

    def test_load_selected_scope_rejects_root_artifacts_before_loading_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            extension_dir = root_dir / "extensions" / "01"
            extension_dir.mkdir(parents=True)
            (root_dir / "qr_document.pdf").write_bytes(b"root qr")

            with (
                mock.patch(
                    "ethernity.workflows.extension.scope.load_input_scope",
                    side_effect=AssertionError("input scope should not load"),
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "extend input scope must not include backup root artifacts",
                ),
            ):
                load_selected_scope(
                    ExtensionRequest(
                        publish_root=str(root_dir),
                        input_directories=(str(root_dir),),
                        base_directory=str(root_dir),
                    )
                )
