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

import base64
import mimetypes
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import typer

from ethernity.cli.commands import render as render_module
from ethernity.render.storage_paths import DEFAULT_LOGO_PATH


class TestRenderCommand(unittest.TestCase):
    def _ctx(self, **values: object) -> object:
        return mock.Mock(obj=dict(values))

    def test_data_uri_for_path_with_known_and_unknown_mime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logo.png"
            path.write_bytes(b"\x89PNG")
            uri = render_module._data_uri_for_path(path)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        payload = uri.split(",", 1)[1]
        self.assertEqual(base64.b64decode(payload), b"\x89PNG")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payload.blobx"
            path.write_bytes(b"abc")
            with mock.patch.object(mimetypes, "guess_type", return_value=(None, None)):
                uri = render_module._data_uri_for_path(path)
        self.assertTrue(uri.startswith("data:application/octet-stream;base64,"))

    @mock.patch("ethernity.cli.commands.render.console.print")
    @mock.patch("ethernity.cli.commands.render.render_envelope_docx")
    @mock.patch("ethernity.cli.commands.render.render_html_to_pdf")
    @mock.patch("ethernity.cli.commands.render.render_template", return_value="<html />")
    @mock.patch("ethernity.cli.commands.render.envelope_page_size_mm", return_value=(10.0, 20.0))
    @mock.patch(
        "ethernity.cli.commands.render.envelope_template_path", return_value=Path("template")
    )
    @mock.patch(
        "ethernity.cli.commands.render._data_uri_for_path",
        return_value="data:image/png;base64,AA==",
    )
    @mock.patch("ethernity.cli.commands.render._run_cli", side_effect=lambda func, debug: func())
    def test_render_pdf_path(
        self,
        _run_cli: mock.MagicMock,
        _data_uri_for_path: mock.MagicMock,
        _envelope_template_path: mock.MagicMock,
        _envelope_page_size_mm: mock.MagicMock,
        render_template: mock.MagicMock,
        render_html_to_pdf: mock.MagicMock,
        render_envelope_docx: mock.MagicMock,
        print_mock: mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logo = Path(tmp) / "logo.png"
            logo.write_bytes(b"\x89PNG")
            ctx = self._ctx(debug=True, quiet=False)
            render_module.render(
                ctx,
                target="envelope-c6",
                orientation="portrait",
                format="pdf",
                output=Path("out.pdf"),
                logo=logo,
            )

        _run_cli.assert_called_once()
        self.assertTrue(_run_cli.call_args.kwargs["debug"])
        render_template.assert_called_once()
        template_context = render_template.call_args.args[1]
        self.assertEqual(template_context["logo_src"], "data:image/png;base64,AA==")
        self.assertEqual(template_context["page_width_mm"], 10.0)
        self.assertEqual(template_context["page_height_mm"], 20.0)
        render_html_to_pdf.assert_called_once_with("<html />", Path("out.pdf"))
        render_envelope_docx.assert_not_called()
        print_mock.assert_called_once_with("out.pdf")

    @mock.patch("ethernity.cli.commands.render.console.print")
    @mock.patch("ethernity.cli.commands.render.render_envelope_docx")
    @mock.patch("ethernity.cli.commands.render.render_html_to_pdf")
    @mock.patch("ethernity.cli.commands.render.envelope_page_size_mm", return_value=(10.0, 20.0))
    @mock.patch(
        "ethernity.cli.commands.render.envelope_template_path", return_value=Path("template")
    )
    @mock.patch("ethernity.cli.commands.render._run_cli", side_effect=lambda func, debug: func())
    def test_render_docx_path_quiet_default_output(
        self,
        _run_cli: mock.MagicMock,
        _envelope_template_path: mock.MagicMock,
        _envelope_page_size_mm: mock.MagicMock,
        render_html_to_pdf: mock.MagicMock,
        render_envelope_docx: mock.MagicMock,
        print_mock: mock.MagicMock,
    ) -> None:
        ctx = self._ctx(debug=False, quiet=True)
        with mock.patch("ethernity.cli.commands.render.Path.cwd", return_value=Path("/tmp")):
            render_module.render(
                ctx,
                target="envelope-c5",
                orientation="landscape",
                format="docx",
                output=None,
                logo=None,
            )

        render_html_to_pdf.assert_not_called()
        render_envelope_docx.assert_called_once_with(
            Path("/tmp/envelope-c5.docx"),
            kind="c5",
            logo_path=DEFAULT_LOGO_PATH,
            orientation="landscape",
        )
        print_mock.assert_not_called()

    def test_register(self) -> None:
        app = typer.Typer()
        render_module.register(app)
        self.assertGreater(len(app.registered_commands), 0)


if __name__ == "__main__":
    unittest.main()
