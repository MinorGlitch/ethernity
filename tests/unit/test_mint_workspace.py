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

from ethernity.cli.features.mint import workspace
from ethernity.cli.shared.types import MintArgs


class TestMintWorkspace(TestCase):
    def test_workspace_sections_show_scan_freshness_warning(self) -> None:
        state = workspace._ReprintShardsState(
            config=None,
            paper=None,
            design=None,
            quiet=False,
        )
        state.source_kind = "scan"
        state.scan_paths = ["root.pdf", "extension-01.pdf"]
        state.allow_stale_head = True
        state.passphrase = "secret"
        state.output_plan = workspace._MintOutputPlan(
            passphrase=workspace._ShardOutputPlan(
                enabled=True,
                mode="fresh",
                threshold=2,
                count=3,
            ),
            signing_key=workspace._ShardOutputPlan(enabled=False),
        )

        sections = workspace._workspace_sections(state)

        self.assertEqual(
            [section.key for section in sections],
            ["source", "unlock", "authority", "shards", "output"],
        )
        self.assertEqual(sections[0].status, "warning")
        self.assertIn("latest scans acknowledged", sections[0].summary)
        self.assertTrue(all(section.can_proceed for section in sections))

    def test_workspace_sections_require_scan_freshness_resolution(self) -> None:
        state = workspace._ReprintShardsState(
            config=None,
            paper=None,
            design=None,
            quiet=False,
        )
        state.source_kind = "scan"
        state.scan_paths = ["root.pdf", "extension-01.pdf"]
        state.passphrase = "secret"
        state.output_plan = workspace._MintOutputPlan(
            passphrase=workspace._ShardOutputPlan(
                enabled=True,
                mode="fresh",
                threshold=2,
                count=3,
            ),
            signing_key=workspace._ShardOutputPlan(enabled=False),
        )

        sections = workspace._workspace_sections(state)

        self.assertEqual(sections[0].status, "missing")
        self.assertIn("confirm the latest chain state", sections[0].summary)
        self.assertFalse(sections[0].can_proceed)

    def test_workspace_sections_surface_signing_authority_blocker(self) -> None:
        state = workspace._ReprintShardsState(
            config=None,
            paper=None,
            design=None,
            quiet=False,
        )
        state.last_blocking_issues = (
            {
                "code": "SIGNING_KEY_SHARDS_REQUIRED",
                "message": "backup is sealed; provide signing authority shard inputs",
                "details": {},
            },
        )

        sections = workspace._workspace_sections(state)

        authority = sections[2]
        self.assertEqual(authority.key, "authority")
        self.assertEqual(authority.status, "missing")
        self.assertIn("backup is sealed", authority.summary)

    def test_build_args_carries_workspace_frames_and_output_plan(self) -> None:
        shard_frame = mock.Mock()
        signing_frame = mock.Mock()
        state = workspace._ReprintShardsState(
            config="cfg",
            paper="A4",
            design="forge",
            quiet=True,
        )
        state.source_kind = "scan"
        state.scan_paths = ["root.pdf"]
        state.expected_head_doc_hash = "aa" * 32
        state.shard_frames = [shard_frame]
        state.signing_key_shard_frames = [signing_frame]
        state.output_dir = "/tmp/minted"
        state.output_plan = workspace._MintOutputPlan(
            passphrase=workspace._ShardOutputPlan(
                enabled=True,
                mode="replacement",
                replacement_count=1,
            ),
            signing_key=workspace._ShardOutputPlan(
                enabled=True,
                mode="fresh",
                threshold=2,
                count=3,
            ),
        )

        args = workspace._build_args(state)

        self.assertEqual(args.config, "cfg")
        self.assertEqual(args.paper, "A4")
        self.assertEqual(args.design, "forge")
        self.assertEqual(args.scan, ["root.pdf"])
        self.assertEqual(args.expected_head_doc_hash, "aa" * 32)
        self.assertEqual(args.shard_frames, [shard_frame])
        self.assertEqual(args.signing_key_shard_frames, [signing_frame])
        self.assertEqual(args.passphrase_replacement_count, 1)
        self.assertEqual(args.signing_key_shard_threshold, 2)
        self.assertEqual(args.signing_key_shard_count, 3)
        self.assertTrue(args.output_dir_existing_parent)

    @mock.patch("ethernity.cli.features.mint.workspace.prompt_yes_no", return_value=True)
    @mock.patch("ethernity.cli.features.mint.workspace.prompt_choice", return_value="fresh")
    def test_signing_shard_plan_same_quorum_keeps_explicit_values(
        self,
        _prompt_choice: mock.MagicMock,
        _prompt_yes_no: mock.MagicMock,
    ) -> None:
        state = workspace._ReprintShardsState(
            config=None,
            paper=None,
            design=None,
            quiet=False,
        )
        passphrase_plan = workspace._ShardOutputPlan(
            enabled=True,
            mode="fresh",
            threshold=2,
            count=3,
        )

        signing_plan = workspace._prompt_signing_shard_plan(
            state,
            passphrase_plan=passphrase_plan,
        )

        self.assertEqual(signing_plan.threshold, 2)
        self.assertEqual(signing_plan.count, 3)
        self.assertEqual(workspace._shard_plan_summary(signing_plan), "fresh set (2 of 3)")

    def test_review_blockers_require_selected_capabilities(self) -> None:
        inspection = SimpleNamespace(
            blocking_issues=(),
            mint_capabilities={
                "can_mint_passphrase_shards": True,
                "can_mint_signing_key_shards": False,
            },
        )

        blockers = workspace._review_blockers(MintArgs(), inspection)

        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["code"], "SIGNING_KEY_SHARDS_NOT_READY")

    @mock.patch("ethernity.cli.features.mint.workspace.prompt_yes_no", return_value=True)
    @mock.patch("ethernity.cli.features.mint.workspace.console.print")
    def test_confirm_review_reports_task_language(
        self,
        console_print: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
    ) -> None:
        inspection = SimpleNamespace(
            recovery=SimpleNamespace(
                doc_id=b"d" * 16,
                auth_payload=SimpleNamespace(),
            ),
            signing_key_source="embedded signing seed",
            selected_extension_index=None,
            selected_extension_doc_hash=None,
            source_summary={"file_count": 2},
        )
        args = MintArgs(
            scan=["root.pdf"],
            passphrase="secret",
            shard_threshold=2,
            shard_count=3,
            mint_signing_key_shards=False,
        )

        self.assertTrue(workspace._confirm_review(args, inspection))

        console_print.assert_called_once()
        prompt_yes_no.assert_called_once()
        self.assertEqual(prompt_yes_no.call_args.args[0], "Reprint these shard documents")

    @mock.patch("ethernity.cli.features.mint.workspace.prompt_yes_no", return_value=True)
    @mock.patch("ethernity.cli.features.mint.workspace.console.print")
    def test_confirm_review_quiet_still_requires_confirmation(
        self,
        console_print: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
    ) -> None:
        inspection = SimpleNamespace(
            recovery=SimpleNamespace(
                doc_id=b"d" * 16,
                auth_payload=SimpleNamespace(),
            ),
            signing_key_source="embedded signing seed",
            selected_extension_index=None,
            selected_extension_doc_hash=None,
            source_summary={"file_count": 2},
        )
        args = MintArgs(
            scan=["root.pdf"],
            passphrase="secret",
            shard_threshold=2,
            shard_count=3,
            mint_signing_key_shards=False,
            quiet=True,
        )

        self.assertTrue(workspace._confirm_review(args, inspection))

        console_print.assert_not_called()
        prompt_yes_no.assert_called_once()
        self.assertEqual(prompt_yes_no.call_args.args[0], "Reprint these shard documents")
