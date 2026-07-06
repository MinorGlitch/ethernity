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

from pathlib import Path
from unittest import TestCase, mock

from ethernity.cli.features.kit import workspace


class TestKitWorkspace(TestCase):
    def test_workspace_sections_show_default_output_and_contents(self) -> None:
        state = workspace._KitState(config="cfg.toml", paper="A4", design="forge", quiet=False)

        sections = workspace._workspace_sections(state)

        self.assertEqual([section.key for section in sections], ["output", "contents", "layout"])
        self.assertTrue(all(section.can_proceed for section in sections))
        self.assertIn("default", sections[0].summary)
        self.assertIn("lean", sections[1].summary)
        self.assertIn("A4", sections[2].summary)

    @mock.patch(
        "ethernity.cli.features.kit.workspace.prompt_optional_path_with_picker",
        return_value="/tmp/kit.pdf",
    )
    def test_prompt_output_uses_picker(
        self, prompt_optional_path_with_picker: mock.MagicMock
    ) -> None:
        state = workspace._KitState(config=None, paper=None, design=None, quiet=False)

        workspace._prompt_output(state)

        self.assertEqual(state.output, Path("/tmp/kit.pdf"))
        self.assertEqual(
            prompt_optional_path_with_picker.call_args.kwargs["picker_id"], "kit-output"
        )

    @mock.patch("ethernity.cli.features.kit.workspace.prompt_yes_no", return_value=True)
    @mock.patch("ethernity.cli.features.kit.workspace.console.print")
    def test_confirm_review_reports_task_language(
        self,
        console_print: mock.MagicMock,
        prompt_yes_no: mock.MagicMock,
    ) -> None:
        args = workspace.KitWorkspaceArgs(
            bundle=Path("bundle.html"),
            output=Path("kit.pdf"),
            config="cfg.toml",
            paper="A4",
            design="forge",
            variant="scanner",
            qr_chunk_size=256,
            quiet=False,
        )

        self.assertTrue(workspace._confirm_review(args))

        console_print.assert_called_once()
        prompt_yes_no.assert_called_once()
        self.assertEqual(prompt_yes_no.call_args.args[0], "Print this recovery kit sheet")
