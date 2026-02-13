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

import unittest
from unittest import mock

from ethernity.cli.flows.prompts import _resolve_recover_output


class _ManifestEntry:
    def __init__(self, path: str | None = None) -> None:
        if path is not None:
            self.path = path


class TestResolveRecoverOutput(unittest.TestCase):
    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_single_file_defaults_to_inferred_manifest_name(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.side_effect = ["file", "inferred"]
        entry = _ManifestEntry("nested/final-name.tar.gz")

        resolved = _resolve_recover_output(
            [(entry, b"payload")],
            None,
            interactive=True,
            doc_id=b"\x11" * 16,
            input_origin="file",
            input_roots=(),
        )

        self.assertEqual(resolved, "final-name.tar.gz")
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_single_file_custom_blank_falls_back_to_inferred_name(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.side_effect = ["file", "custom"]
        mock_prompt_optional_path_with_picker.return_value = None
        entry = _ManifestEntry("report.pdf")

        resolved = _resolve_recover_output(
            [(entry, b"payload")],
            None,
            interactive=True,
            doc_id=b"\x22" * 16,
            input_origin="file",
            input_roots=(),
        )

        self.assertEqual(resolved, "report.pdf")
        mock_prompt_optional_path_with_picker.assert_called_once()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_single_file_stdout_bypasses_filename_prompt(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "stdout"

        resolved = _resolve_recover_output(
            [(_ManifestEntry("archive.zip"), b"payload")],
            None,
            interactive=True,
            doc_id=b"\x33" * 16,
            input_origin="file",
            input_roots=(),
        )

        self.assertIsNone(resolved)
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_single_file_missing_manifest_path_uses_bin_fallback(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.side_effect = ["file", "inferred"]

        resolved = _resolve_recover_output(
            [(_ManifestEntry(), b"payload")],
            None,
            interactive=True,
            doc_id=b"\x44" * 16,
            input_origin="file",
            input_roots=(),
        )

        self.assertEqual(resolved, "recovered.bin")
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_multi_file_default_directory_unchanged(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "inferred"
        entries = [
            (_ManifestEntry("a.txt"), b"a"),
            (_ManifestEntry("b.txt"), b"b"),
        ]

        resolved = _resolve_recover_output(
            entries,
            None,
            interactive=True,
            doc_id=b"\x55" * 16,
            input_origin="mixed",
            input_roots=("vault",),
        )

        self.assertEqual(resolved, "recovered-" + ("55" * 16))
        mock_prompt_choice.assert_called_once()
        mock_prompt_optional_path_with_picker.assert_not_called()

    def test_returns_preselected_output_or_noninteractive_unchanged(self) -> None:
        entry = _ManifestEntry("doc.txt")
        self.assertEqual(
            _resolve_recover_output(
                [(entry, b"payload")],
                "chosen.txt",
                interactive=True,
                doc_id=b"\x11" * 16,
                input_origin="file",
                input_roots=(),
            ),
            "chosen.txt",
        )
        self.assertIsNone(
            _resolve_recover_output(
                [(entry, b"payload")],
                None,
                interactive=False,
                doc_id=b"\x11" * 16,
                input_origin="file",
                input_roots=(),
            )
        )
        self.assertIsNone(
            _resolve_recover_output(
                [],
                None,
                interactive=True,
                doc_id=b"\x11" * 16,
                input_origin="file",
                input_roots=(),
            )
        )

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_multi_file_without_doc_id_uses_recovered_output_default(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "inferred"
        entries = [(_ManifestEntry("a.txt"), b"a"), (_ManifestEntry("b.txt"), b"b")]
        resolved = _resolve_recover_output(
            entries,
            None,
            interactive=True,
            doc_id=None,
            input_origin="mixed",
            input_roots=("vault",),
        )
        self.assertEqual(resolved, "recovered-output")
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_inferred_filename_trims_to_basename(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.side_effect = ["file", "inferred"]
        entry = _ManifestEntry("  /nested/path/archive.zip  ")
        resolved = _resolve_recover_output(
            [(entry, b"payload")],
            None,
            interactive=True,
            doc_id=b"\x11" * 16,
            input_origin="file",
            input_roots=(),
        )
        self.assertEqual(resolved, "archive.zip")
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_single_entry_directory_origin_uses_directory_prompt(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "inferred"
        entry = _ManifestEntry("report.txt")

        resolved = _resolve_recover_output(
            [(entry, b"payload")],
            None,
            interactive=True,
            doc_id=b"\x66" * 16,
            input_origin="directory",
            input_roots=("vault",),
        )

        self.assertEqual(resolved, "vault")
        mock_prompt_choice.assert_called_once()
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_single_entry_directory_origin_prefers_manifest_parent(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "inferred"

        resolved = _resolve_recover_output(
            [(_ManifestEntry("vault/report.txt"), b"payload")],
            None,
            interactive=True,
            doc_id=b"\x69" * 16,
            input_origin="directory",
            input_roots=("vault",),
        )

        self.assertEqual(resolved, "vault")
        mock_prompt_choice.assert_called_once()
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_single_entry_directory_origin_rejects_parent_dot_segment_root(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "inferred"

        resolved = _resolve_recover_output(
            [(_ManifestEntry("vault/report.txt"), b"payload")],
            None,
            interactive=True,
            doc_id=b"\x6a" * 16,
            input_origin="directory",
            input_roots=("..",),
        )

        self.assertEqual(resolved, "recovered-" + ("6a" * 16))
        mock_prompt_choice.assert_called_once()
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_single_entry_directory_origin_rejects_current_dot_segment_root(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "inferred"

        resolved = _resolve_recover_output(
            [(_ManifestEntry("vault/report.txt"), b"payload")],
            None,
            interactive=True,
            doc_id=b"\x6b" * 16,
            input_origin="directory",
            input_roots=(".",),
        )

        self.assertEqual(resolved, "recovered-" + ("6b" * 16))
        mock_prompt_choice.assert_called_once()
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_single_entry_mixed_origin_uses_directory_prompt(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "custom"
        mock_prompt_optional_path_with_picker.return_value = "/tmp/out"

        resolved = _resolve_recover_output(
            [(_ManifestEntry("report.txt"), b"payload")],
            None,
            interactive=True,
            doc_id=b"\x77" * 16,
            input_origin="mixed",
            input_roots=("vault",),
        )

        self.assertEqual(resolved, "/tmp/out")
        mock_prompt_choice.assert_called_once()
        mock_prompt_optional_path_with_picker.assert_called_once()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_mixed_origin_ignores_roots_and_uses_fallback_directory(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "inferred"

        resolved = _resolve_recover_output(
            [
                (_ManifestEntry("vault/a.txt"), b"a"),
                (_ManifestEntry("vault/sub/b.txt"), b"b"),
            ],
            None,
            interactive=True,
            doc_id=b"\x70" * 16,
            input_origin="mixed",
            input_roots=("vault",),
        )

        self.assertEqual(resolved, "recovered-" + ("70" * 16))
        mock_prompt_choice.assert_called_once()
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_directory_origin_with_multiple_roots_uses_fallback_directory(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "inferred"

        resolved = _resolve_recover_output(
            [
                (_ManifestEntry("a/file.txt"), b"a"),
                (_ManifestEntry("b/file.txt"), b"b"),
            ],
            None,
            interactive=True,
            doc_id=b"\x71" * 16,
            input_origin="directory",
            input_roots=("data", "data"),
        )

        self.assertEqual(resolved, "recovered-" + ("71" * 16))
        mock_prompt_choice.assert_called_once()
        mock_prompt_optional_path_with_picker.assert_not_called()

    @mock.patch("ethernity.cli.flows.prompts.prompt_optional_path_with_picker")
    @mock.patch("ethernity.cli.flows.prompts.prompt_choice")
    def test_multi_file_custom_blank_directory_falls_back_to_inferred_default(
        self,
        mock_prompt_choice: mock.MagicMock,
        mock_prompt_optional_path_with_picker: mock.MagicMock,
    ) -> None:
        mock_prompt_choice.return_value = "custom"
        mock_prompt_optional_path_with_picker.return_value = None

        resolved = _resolve_recover_output(
            [(_ManifestEntry("a.txt"), b"a"), (_ManifestEntry("b.txt"), b"b")],
            None,
            interactive=True,
            doc_id=b"\x88" * 16,
            input_origin="mixed",
            input_roots=("vault",),
        )

        self.assertEqual(resolved, "recovered-" + ("88" * 16))
        mock_prompt_choice.assert_called_once()
        mock_prompt_optional_path_with_picker.assert_called_once()


if __name__ == "__main__":
    unittest.main()
