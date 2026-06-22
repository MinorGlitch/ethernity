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

from types import SimpleNamespace
from unittest import TestCase, mock

from ethernity.cli.features.extend import workspace
from ethernity.cli.shared.types import ExtendArgs


class TestExtendWorkspace(TestCase):
    def test_workspace_sections_show_scan_freshness_warning(self) -> None:
        state = workspace._AddFilesState(config=None, paper=None, design=None, quiet=False)
        state.source_kind = "scan"
        state.root_dir = "/tmp/out"
        state.scan_paths = ["root.pdf"]
        state.allow_stale_head = True
        state.passphrase = "secret"
        state.selected_paths = ["updated.txt"]
        state.output_policy = workspace._AddFilesOutputPolicy(
            unlock_policy="self-contained",
            shard_threshold=2,
            shard_count=3,
        )

        sections = workspace._workspace_sections(state)

        self.assertEqual(
            [section.key for section in sections],
            ["source", "unlock", "files", "recovery"],
        )
        self.assertEqual(sections[0].status, "warning")
        self.assertIn("latest scans acknowledged", sections[0].summary)
        self.assertTrue(all(section.can_proceed for section in sections))

    def test_build_args_splits_files_and_directories(self) -> None:
        state = workspace._AddFilesState(config="cfg", paper="A4", design="forge", quiet=True)
        state.source_kind = "folder"
        state.root_dir = "/tmp/root"
        state.passphrase = "secret"
        state.selected_paths = ["updated.txt", "/tmp"]
        state.output_policy = workspace._AddFilesOutputPolicy(
            unlock_policy="self-contained",
            shard_threshold=2,
            shard_count=3,
            signing_key_mode="not-stored",
        )

        args = workspace._build_args(state)

        self.assertEqual(args.config, "cfg")
        self.assertEqual(args.paper, "A4")
        self.assertEqual(args.design, "forge")
        self.assertEqual(args.root_dir, "/tmp/root")
        self.assertEqual(args.input, ["updated.txt"])
        self.assertEqual(args.input_dir, ["/tmp"])
        self.assertEqual(args.passphrase, "secret")
        self.assertEqual(args.shard_threshold, 2)
        self.assertEqual(args.shard_count, 3)

    @mock.patch("ethernity.cli.features.extend.workspace.prompt_yes_no", return_value=True)
    @mock.patch("ethernity.cli.features.extend.workspace.console.print")
    def test_confirm_review_reports_task_language(
        self,
        console_print: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
    ) -> None:
        prepared = SimpleNamespace(
            next_index=2,
            changed_paths=("updated.txt",),
            new_paths=("new.txt",),
            unchanged_paths=("same.txt",),
        )
        args = ExtendArgs(
            root_dir="/tmp/root",
            scan=["root.pdf"],
            input=["updated.txt"],
            passphrase="secret",
            unlock_policy="self-contained",
            shard_threshold=2,
            shard_count=3,
            signing_key_mode="not-stored",
            expected_head_doc_hash="aa" * 32,
        )

        self.assertTrue(workspace._confirm_review(args, prepared))

        console_print.assert_called_once()
        prompt_yes_no.assert_called_once()
        self.assertEqual(prompt_yes_no.call_args.args[0], "Add these files to the backup")
