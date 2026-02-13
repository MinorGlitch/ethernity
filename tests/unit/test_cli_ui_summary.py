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
from types import SimpleNamespace
from unittest import mock

from ethernity.cli.core.types import BackupResult
from ethernity.cli.ui import summary as summary_module
from ethernity.core.models import DocumentPlan


class TestUISummary(unittest.TestCase):
    def test_print_backup_summary_quiet_noop(self) -> None:
        result = BackupResult(
            doc_id=b"\x01" * 16,
            qr_path="qr.pdf",
            recovery_path="recovery.txt",
            shard_paths=(),
            signing_key_shard_paths=(),
            passphrase_used=None,
        )
        plan = DocumentPlan(version=1, sealed=False, sharding=None, signing_seed_sharding=None)
        with mock.patch("ethernity.cli.ui.summary.console.print") as print_mock:
            summary_module.print_backup_summary(result, plan, passphrase=None, quiet=True)
        print_mock.assert_not_called()

    @mock.patch("ethernity.cli.ui.summary.panel", return_value="PANEL")
    @mock.patch("ethernity.cli.ui.summary.build_outputs_tree", return_value="TREE")
    def test_print_backup_summary_prints_panel_when_not_quiet(
        self,
        build_outputs_tree: mock.MagicMock,
        panel: mock.MagicMock,
    ) -> None:
        result = BackupResult(
            doc_id=b"\x01" * 16,
            qr_path="qr.pdf",
            recovery_path="recovery.txt",
            shard_paths=("s1.pdf",),
            signing_key_shard_paths=("k1.pdf",),
            passphrase_used="secret",
            kit_index_path="kit-index.pdf",
        )
        plan = DocumentPlan(version=1, sealed=False, sharding=None, signing_seed_sharding=None)
        with mock.patch("ethernity.cli.ui.summary.console.print") as print_mock:
            summary_module.print_backup_summary(result, plan, passphrase="secret", quiet=False)
        build_outputs_tree.assert_called_once_with(
            "qr.pdf",
            "recovery.txt",
            ("s1.pdf",),
            ("k1.pdf",),
            "kit-index.pdf",
        )
        panel.assert_called_once_with("Outputs", "TREE")
        self.assertIn(mock.call(), print_mock.mock_calls)
        self.assertIn(mock.call("PANEL"), print_mock.mock_calls)

    @mock.patch("ethernity.cli.ui.summary.panel")
    @mock.patch("ethernity.cli.ui.summary.build_kv_table")
    @mock.patch("ethernity.cli.ui.summary.build_recovered_tree")
    def test_print_recover_summary_stdout_and_auth_row(
        self,
        build_recovered_tree: mock.MagicMock,
        build_kv_table: mock.MagicMock,
        panel: mock.MagicMock,
    ) -> None:
        entries = [(SimpleNamespace(path="a.txt"), b"x")]
        build_recovered_tree.return_value = None
        build_kv_table.return_value = "TABLE"
        panel.side_effect = ["SUMMARY_PANEL"]

        with mock.patch("ethernity.cli.ui.summary.console_err.print") as print_err:
            summary_module.print_recover_summary(
                entries,
                output_path=None,
                auth_status="verified",
                quiet=False,
            )

        build_kv_table.assert_called_once()
        rows = build_kv_table.call_args.args[0]
        self.assertIn(("Recovered", "1 file"), rows)
        self.assertIn(("Output", "stdout"), rows)
        self.assertIn(("Auth verification", "verified"), rows)
        build_recovered_tree.assert_called_once_with(
            entries,
            None,
            single_entry_output_is_directory=False,
        )
        print_err.assert_called_once_with("SUMMARY_PANEL")

    @mock.patch("ethernity.cli.ui.summary.panel")
    @mock.patch("ethernity.cli.ui.summary.build_kv_table")
    @mock.patch("ethernity.cli.ui.summary.build_recovered_tree")
    def test_print_recover_summary_with_tree(
        self,
        build_recovered_tree: mock.MagicMock,
        build_kv_table: mock.MagicMock,
        panel: mock.MagicMock,
    ) -> None:
        entries = [
            (SimpleNamespace(path="a.txt"), b"x"),
            (SimpleNamespace(path="b.txt"), b"y"),
        ]
        build_recovered_tree.return_value = "TREE"
        build_kv_table.return_value = "TABLE"
        panel.side_effect = ["SUMMARY_PANEL", "TREE_PANEL"]

        with mock.patch("ethernity.cli.ui.summary.console_err.print") as print_err:
            summary_module.print_recover_summary(
                entries,
                output_path="out-dir",
                auth_status=None,
                quiet=False,
            )

        rows = build_kv_table.call_args.args[0]
        self.assertIn(("Recovered", "2 files"), rows)
        self.assertIn(("Output", "out-dir"), rows)
        self.assertEqual(print_err.call_count, 2)
        self.assertEqual(print_err.mock_calls[0], mock.call("SUMMARY_PANEL"))
        self.assertEqual(print_err.mock_calls[1], mock.call("TREE_PANEL"))

    @mock.patch("ethernity.cli.ui.summary.panel")
    @mock.patch("ethernity.cli.ui.summary.build_kv_table")
    @mock.patch("ethernity.cli.ui.summary.build_recovered_tree")
    def test_print_recover_summary_single_entry_directory_mode(
        self,
        build_recovered_tree: mock.MagicMock,
        build_kv_table: mock.MagicMock,
        panel: mock.MagicMock,
    ) -> None:
        entries = [(SimpleNamespace(path="vault/a.txt"), b"x")]
        build_recovered_tree.return_value = "TREE"
        build_kv_table.return_value = "TABLE"
        panel.side_effect = ["SUMMARY_PANEL", "TREE_PANEL"]

        with mock.patch("ethernity.cli.ui.summary.console_err.print") as print_err:
            summary_module.print_recover_summary(
                entries,
                output_path="vault",
                auth_status=None,
                quiet=False,
                single_entry_output_is_directory=True,
            )

        build_recovered_tree.assert_called_once_with(
            entries,
            "vault",
            single_entry_output_is_directory=True,
        )
        self.assertEqual(print_err.call_count, 2)

    def test_print_recover_summary_quiet_noop(self) -> None:
        with mock.patch("ethernity.cli.ui.summary.console_err.print") as print_err:
            summary_module.print_recover_summary([], "x", auth_status=None, quiet=True)
        print_err.assert_not_called()

    def test_format_auth_status_mappings(self) -> None:
        cases = (
            ("verified", False, "verified"),
            ("skipped", False, "skipped (--rescue-mode)"),
            ("ignored", False, "failed (ignored due to --rescue-mode)"),
            ("invalid", False, "invalid"),
            ("invalid", True, "invalid (ignored due to --rescue-mode)"),
            ("missing", False, "missing"),
            ("missing", True, "skipped (--rescue-mode)"),
            ("custom", False, "custom"),
        )
        for status, allow_unsigned, expected in cases:
            with self.subTest(status=status, allow_unsigned=allow_unsigned):
                self.assertEqual(
                    summary_module.format_auth_status(status, allow_unsigned=allow_unsigned),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
