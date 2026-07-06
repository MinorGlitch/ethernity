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

from ethernity.cli.features.recover import workspace
from ethernity.cli.shared.types import RecoverArgs


def _state() -> workspace._RestoreState:
    return workspace._RestoreState(
        args=RecoverArgs(),
        quiet=False,
        debug=False,
        frames=[],
        input_label=None,
        input_detail=None,
        passphrase=None,
        shard_fallback_files=[],
        shard_payloads_file=[],
        shard_scan=[],
        collected_shard_frames=[],
        output_path=None,
    )


class TestRecoverWorkspace(TestCase):
    def test_workspace_sections_show_restore_status(self) -> None:
        state = _state()
        state.frames = [mock.Mock()]
        state.input_label = "Backup PDF or images"
        state.input_detail = "/tmp/scan.pdf"
        state.passphrase = "secret"

        sections = workspace._workspace_sections(state)

        self.assertEqual(
            [section.key for section in sections],
            ["source", "unlock", "target", "output"],
        )
        self.assertTrue(all(section.can_proceed for section in sections))
        self.assertIn("Backup PDF or images", sections[0].summary)
        self.assertIn("Passphrase provided", sections[1].summary)
        self.assertIn("Latest supplied", sections[2].summary)
        self.assertIn("Choose after decrypt preview", sections[3].summary)

    @mock.patch("ethernity.cli.features.recover.workspace.prompt_optional", return_value="aa" * 32)
    @mock.patch("ethernity.cli.features.recover.workspace.prompt_int", return_value=2)
    @mock.patch("ethernity.cli.features.recover.workspace.prompt_choice", return_value="index")
    def test_prompt_target_sets_extension_index_and_expected_head(
        self,
        _prompt_choice: mock.MagicMock,
        _prompt_int: mock.MagicMock,
        _prompt_optional: mock.MagicMock,
    ) -> None:
        state = _state()

        workspace._prompt_target(state)

        self.assertEqual(state.args.extension_index, 2)
        self.assertIsNone(state.args.extension_doc_hash)
        self.assertEqual(state.args.expected_head_doc_hash, "aa" * 32)

    @mock.patch("ethernity.cli.features.recover.workspace._write_restored_outputs")
    @mock.patch(
        "ethernity.cli.features.recover.workspace._choose_output_after_preview",
        return_value="out",
    )
    @mock.patch("ethernity.cli.features.recover.workspace._decrypt_or_prompt_fix")
    @mock.patch("ethernity.cli.features.recover.workspace.prompt_yes_no", side_effect=[True, True])
    @mock.patch(
        "ethernity.cli.features.recover.workspace._build_recovery_review_rows",
        return_value=[("Inputs", "1")],
    )
    @mock.patch("ethernity.cli.features.recover.workspace.console.print")
    @mock.patch("ethernity.cli.features.recover.workspace._build_plan_or_prompt_fix")
    def test_review_decrypts_then_confirms_write(
        self,
        build_plan_or_prompt_fix: mock.MagicMock,
        console_print: mock.MagicMock,
        _build_recovery_review_rows: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
        decrypt_or_prompt_fix: mock.MagicMock,
        choose_output_after_preview: mock.MagicMock,
        write_restored_outputs: mock.MagicMock,
    ) -> None:
        state = _state()
        state.frames = [mock.Mock()]
        state.passphrase = "secret"
        plan = SimpleNamespace(
            ciphertext=b"cipher",
            passphrase="secret",
            auth_status="verified",
            allow_unsigned=False,
        )
        manifest = SimpleNamespace(input_origin="file", input_roots=())
        extracted = [(SimpleNamespace(path="secret.txt"), b"secret")]
        decrypted = SimpleNamespace(
            manifest=manifest,
            extracted=extracted,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        build_plan_or_prompt_fix.return_value = plan
        decrypt_or_prompt_fix.return_value = decrypted

        self.assertEqual(workspace._review_decrypt_and_write(state), 0)

        console_print.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in prompt_yes_no.call_args_list],
            ["Decrypt and preview recovered files", "Write recovered files"],
        )
        choose_output_after_preview.assert_called_once_with(state, plan, manifest, extracted)
        write_restored_outputs.assert_called_once()
