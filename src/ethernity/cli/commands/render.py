#!/usr/bin/env python3
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

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Literal

import typer

from ...render.docx_render import render_envelope_docx
from ...render.html_to_pdf import render_html_to_pdf
from ...render.storage_paths import (
    DEFAULT_LOGO_PATH,
    EnvelopeKind,
    EnvelopeOrientation,
    envelope_page_size_mm,
    envelope_template_path,
)
from ...render.templating import render_template
from ..api import console
from ..core.common import _ctx_value, _run_cli

RenderTarget = Literal["envelope-c6", "envelope-c5", "envelope-c4", "envelope-dl"]
RenderFormat = Literal["pdf", "docx"]
RenderOrientation = EnvelopeOrientation

_RENDER_HELP = (
    "Render helper templates (PDF/DOCX).\n\n"
    "Examples:\n"
    "  ethernity render envelope-c6 --format pdf -o envelope_c6.pdf\n"
    "  ethernity render envelope-c6 --format docx -o envelope_c6.docx\n"
    "  ethernity render envelope-dl --format pdf -o envelope_dl.pdf\n"
)

_ENVELOPE_TARGETS: dict[RenderTarget, EnvelopeKind] = {
    "envelope-c6": "c6",
    "envelope-c5": "c5",
    "envelope-c4": "c4",
    "envelope-dl": "dl",
}


def register(app: typer.Typer) -> None:
    app.command(help=_RENDER_HELP)(render)


def render(
    ctx: typer.Context,
    target: RenderTarget = typer.Argument(..., help="What to render (currently: envelope-c6)."),
    orientation: RenderOrientation = typer.Option(
        "portrait",
        "--orientation",
        help="Page orientation for envelope templates.",
        rich_help_panel="Outputs",
    ),
    format: RenderFormat = typer.Option(
        "pdf",
        "--format",
        "-f",
        help="Output format.",
        rich_help_panel="Outputs",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (defaults to <target>.<format>).",
        rich_help_panel="Outputs",
    ),
    logo: Path | None = typer.Option(
        None,
        "--logo",
        help="Override the default logo image.",
        rich_help_panel="Inputs",
    ),
) -> None:
    quiet_value = bool(_ctx_value(ctx, "quiet"))
    debug_value = bool(_ctx_value(ctx, "debug"))

    def _run() -> None:
        output_path = output or Path.cwd() / f"{target}.{format}"
        kind = _ENVELOPE_TARGETS[target]
        template_path = envelope_template_path(kind)
        page_width_mm, page_height_mm = envelope_page_size_mm(kind, orientation)

        if format == "pdf":
            context: dict[str, object] = {}
            if logo is not None:
                context["logo_src"] = _data_uri_for_path(logo)
            context["page_width_mm"] = page_width_mm
            context["page_height_mm"] = page_height_mm
            html = render_template(template_path, context)
            render_html_to_pdf(html, output_path)
        else:
            render_envelope_docx(
                output_path,
                kind=kind,
                logo_path=logo or DEFAULT_LOGO_PATH,
                orientation=orientation,
            )
        if not quiet_value:
            console.print(str(output_path))

    _run_cli(_run, debug=debug_value)


def _data_uri_for_path(path: Path) -> str:
    resolved = path.expanduser()
    payload = resolved.read_bytes()
    mime_type, _encoding = mimetypes.guess_type(resolved.name)
    if not mime_type:
        mime_type = "application/octet-stream"
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
