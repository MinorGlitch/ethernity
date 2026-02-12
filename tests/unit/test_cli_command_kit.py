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
from pathlib import Path
from unittest import mock

import typer

from ethernity.cli.commands import kit as kit_command
from ethernity.cli.flows.kit import KitResult


class TestKitCommand(unittest.TestCase):
    def _ctx(self, **values: object) -> object:
        return mock.Mock(obj=dict(values))

    @mock.patch("ethernity.cli.commands.kit.print_completion_panel")
    @mock.patch("ethernity.cli.commands.kit.render_kit_qr_document")
    def test_run_kit_render_quiet_and_non_quiet(
        self,
        render_kit_qr_document: mock.MagicMock,
        print_completion_panel: mock.MagicMock,
    ) -> None:
        render_kit_qr_document.return_value = KitResult(
            output_path=Path("kit.pdf"),
            chunk_count=3,
            chunk_size=800,
            bytes_total=1234,
            doc_id_hex="ab" * 16,
        )

        kit_command._run_kit_render(
            bundle=None,
            output=None,
            config_value=None,
            paper_value=None,
            design_value=None,
            qr_chunk_size=None,
            quiet_value=True,
        )
        print_completion_panel.assert_not_called()

        kit_command._run_kit_render(
            bundle=None,
            output=None,
            config_value=None,
            paper_value=None,
            design_value=None,
            qr_chunk_size=None,
            quiet_value=False,
        )
        print_completion_panel.assert_called_once()

    @mock.patch("ethernity.cli.commands.kit._run_kit_render")
    @mock.patch("ethernity.cli.commands.kit._run_cli", side_effect=lambda func, debug: func())
    @mock.patch(
        "ethernity.cli.commands.kit._resolve_config_and_paper",
        return_value=("ctx.toml", "LETTER"),
    )
    def test_kit_command_resolves_context_and_executes(
        self,
        _resolve_config_and_paper: mock.MagicMock,
        _run_cli: mock.MagicMock,
        run_kit_render: mock.MagicMock,
    ) -> None:
        ctx = self._ctx(design="forge", quiet=True, debug=True)
        kit_command.kit(
            ctx,
            output=Path("out.pdf"),
            bundle=Path("bundle.html"),
            qr_chunk_size=512,
            config=None,
            paper=None,
            design=None,
            quiet=False,
        )
        run_kit_render.assert_called_once_with(
            bundle=Path("bundle.html"),
            output=Path("out.pdf"),
            config_value="ctx.toml",
            paper_value="LETTER",
            design_value="forge",
            qr_chunk_size=512,
            quiet_value=True,
        )

    def test_register(self) -> None:
        app = typer.Typer()
        kit_command.register(app)
        self.assertGreater(len(app.registered_commands), 0)


if __name__ == "__main__":
    unittest.main()
