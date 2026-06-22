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
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from ethernity.cli.features.backup import workspace
from ethernity.cli.shared.types import BackupArgs, BackupResult, InputFile
from ethernity.core.models import ShardingConfig, SigningSeedMode


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        paper_size="A4",
        template_path=Path("/templates/sentinel/main.html"),
    )


def _state() -> workspace._CreateBackupState:
    return workspace._CreateBackupState(
        args=BackupArgs(),
        config_path=None,
        paper=None,
        design=None,
        quiet=False,
        debug_override=None,
        debug_max_bytes=1024,
        debug_reveal_secrets=False,
        config=_config(),
        selected_paths=[],
        input_files=[],
        resolved_base=None,
        output_dir=None,
        input_origin="file",
        input_roots=[],
        passphrase=None,
        passphrase_words=None,
        sealed=False,
        debug=False,
        signing_seed_mode=SigningSeedMode.EMBEDDED,
        sharding=None,
        signing_seed_sharding=None,
    )


class TestBackupWorkspace(TestCase):
    def test_workspace_sections_show_ready_defaults_and_missing_required_work(self) -> None:
        state = _state()
        state.input_files = [
            InputFile(
                source_path=Path("secret.txt"),
                relative_path="secret.txt",
                data=b"secret",
                mtime=None,
            )
        ]
        state.passphrase_words = 12
        state.recovery_chosen = True
        state.sharding = ShardingConfig(threshold=2, shares=3)

        sections = workspace._workspace_sections(state)

        self.assertEqual(
            [section.key for section in sections],
            ["files", "passphrase", "recovery", "layout"],
        )
        self.assertTrue(all(section.can_proceed for section in sections))
        self.assertIn("1 file(s)", sections[0].summary)
        self.assertIn("12-word", sections[1].summary)
        self.assertIn("2 of 3", sections[2].summary)

    @mock.patch("ethernity.cli.features.backup.workspace.progress")
    @mock.patch("ethernity.cli.features.backup.workspace._load_input_files")
    @mock.patch(
        "ethernity.cli.features.backup.workspace.prompt_optional_path_with_picker",
        return_value="/tmp/out",
    )
    @mock.patch("ethernity.cli.features.backup.workspace.prompt_paths_with_picker")
    def test_prompt_files_uses_picker_for_inputs_and_output(
        self,
        prompt_paths_with_picker: mock.MagicMock,
        prompt_optional_path_with_picker: mock.MagicMock,
        load_input_files: mock.MagicMock,
        progress: mock.MagicMock,
    ) -> None:
        progress.return_value.__enter__.return_value = None
        progress.return_value.__exit__.return_value = None
        state = _state()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_file = root / "secret.txt"
            input_file.write_text("secret", encoding="utf-8")
            prompt_paths_with_picker.return_value = [str(input_file)]
            loaded = InputFile(
                source_path=input_file,
                relative_path="secret.txt",
                data=b"secret",
                mtime=None,
            )
            load_input_files.return_value = ([loaded], root, "file", [])

            workspace._prompt_files_and_output(state)

        self.assertEqual(state.output_dir, "/tmp/out")
        self.assertEqual(state.args.output_dir, "/tmp/out")
        self.assertEqual(state.input_files, [loaded])
        self.assertEqual(state.args.input, [str(input_file)])
        self.assertIsNone(state.args.input_dir)
        self.assertEqual(prompt_paths_with_picker.call_args.kwargs["picker_id"], "backup-inputs")
        self.assertEqual(
            prompt_optional_path_with_picker.call_args.kwargs["picker_id"],
            "backup-output-folder",
        )

    @mock.patch("ethernity.cli.features.backup.workspace._maybe_save_backup_defaults")
    @mock.patch("ethernity.cli.features.backup.workspace._print_completion_actions")
    @mock.patch("ethernity.cli.features.backup.workspace.print_backup_summary")
    @mock.patch("ethernity.cli.features.backup.workspace._run_backup_from_state")
    @mock.patch("ethernity.cli.features.backup.workspace.prompt_yes_no", return_value=True)
    @mock.patch("ethernity.cli.features.backup.workspace.console.print")
    @mock.patch(
        "ethernity.cli.features.backup.workspace._build_review_rows",
        return_value=[("Inputs", "1 file")],
    )
    def test_review_reports_task_language(
        self,
        _build_review_rows: mock.MagicMock,
        console_print: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
        run_backup_from_state: mock.MagicMock,
        print_backup_summary: mock.MagicMock,
        print_completion_actions: mock.MagicMock,
        maybe_save_backup_defaults: mock.MagicMock,
    ) -> None:
        state = _state()
        state.input_files = [
            InputFile(
                source_path=Path("secret.txt"),
                relative_path="secret.txt",
                data=b"secret",
                mtime=None,
            )
        ]
        state.passphrase_words = 12
        state.recovery_chosen = True
        state.sharding = ShardingConfig(threshold=2, shares=3)
        run_backup_from_state.return_value = BackupResult(
            doc_id=b"\x11" * 16,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            shard_paths=(),
            signing_key_shard_paths=(),
            passphrase_used="passphrase",
        )

        self.assertEqual(workspace._review_and_run(state, configured_fields=frozenset()), 0)

        console_print.assert_called_once()
        prompt_yes_no.assert_called_once()
        self.assertEqual(prompt_yes_no.call_args.args[0], "Create backup documents")
        run_backup_from_state.assert_called_once()
        print_backup_summary.assert_called_once()
        print_completion_actions.assert_called_once()
        maybe_save_backup_defaults.assert_called_once()
