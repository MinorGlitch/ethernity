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

from unittest import TestCase, mock

from ethernity.cli.features.compact import workspace
from ethernity.cli.shared.types import CompactArgs


class TestCompactWorkspace(TestCase):
    def test_workspace_sections_show_scan_freshness_warning(self) -> None:
        state = workspace._RebuildState(config=None, paper=None, design=None, quiet=False)
        state.source_kind = "scan"
        state.scan_paths = ["root.pdf"]
        state.allow_stale_head = True
        state.passphrase = "secret"
        state.output_dir = "/tmp/out"

        sections = workspace._workspace_sections(state)

        self.assertEqual([section.key for section in sections], ["source", "unlock", "output"])
        self.assertEqual(sections[0].status, "warning")
        self.assertIn("latest scans acknowledged", sections[0].summary)
        self.assertTrue(all(section.can_proceed for section in sections))

    def test_build_args_preserves_unlock_material(self) -> None:
        frame = mock.Mock()
        state = workspace._RebuildState(config="cfg", paper="A4", design="forge", quiet=True)
        state.source_kind = "folder"
        state.root_dir = "/tmp/root"
        state.output_dir = "/tmp/out"
        state.shard_fallback_files = ["shards.txt"]
        state.shard_payloads_file = ["payloads.txt"]
        state.shard_scan = ["shard.pdf"]
        state.shard_frames = [frame]

        args = workspace._build_args(state)

        self.assertEqual(args.config, "cfg")
        self.assertEqual(args.paper, "A4")
        self.assertEqual(args.design, "forge")
        self.assertEqual(args.root_dir, "/tmp/root")
        self.assertIsNone(args.scan)
        self.assertEqual(args.output_dir, "/tmp/out")
        self.assertEqual(args.shard_fallback_file, ["shards.txt"])
        self.assertEqual(args.shard_payloads_file, ["payloads.txt"])
        self.assertEqual(args.shard_scan, ["shard.pdf"])
        self.assertEqual(args.shard_frames, [frame])
        self.assertTrue(args.quiet)

    @mock.patch("ethernity.cli.features.compact.workspace.prompt_yes_no", return_value=True)
    @mock.patch("ethernity.cli.features.compact.workspace.console.print")
    def test_confirm_review_reports_task_language(
        self,
        console_print: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
    ) -> None:
        args = CompactArgs(
            scan=["root.pdf"],
            output_dir="/tmp/out",
            passphrase="secret",
            expected_head_doc_hash="aa" * 32,
        )

        self.assertTrue(workspace._confirm_review(args))

        console_print.assert_called_once()
        prompt_yes_no.assert_called_once()
        self.assertEqual(prompt_yes_no.call_args.args[0], "Rebuild this backup set")
