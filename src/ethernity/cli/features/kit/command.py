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

import functools
from pathlib import Path
from typing import Annotated

import typer

from ethernity.cli.features.kit.workflow import DEFAULT_KIT_CHUNK_SIZE, render_kit_qr_document
from ethernity.cli.shared.common import (
    _ctx_state,
    _paper_callback,
    _resolve_config_and_paper,
    _run_cli,
)
from ethernity.cli.shared.ui_api import print_completion_panel

_KIT_HELP = (
    "Generate a printable QR document for the recovery kit.\n\n"
    "The recovery kit is a self-contained HTML file that can decrypt and recover\n"
    "your backups offline. Scan the QR codes with any device to reconstruct it.\n\n"
    "Examples:\n"
    "  ethernity kit                    # Generate QR document with defaults\n"
    "  ethernity kit -o my_kit.pdf      # Custom output filename\n"
    "  ethernity kit --paper LETTER     # Use US Letter paper size"
)


def register(app: typer.Typer) -> None:
    app.command(help=_KIT_HELP)(kit)


def _run_kit_render(
    *,
    bundle: Path | None,
    output: Path | None,
    config_value: str | None,
    paper_value: str | None,
    design_value: str | None,
    variant_value: str,
    qr_chunk_size: int | None,
    quiet_value: bool,
) -> None:
    result = render_kit_qr_document(
        bundle_path=bundle,
        output_path=output,
        config_path=config_value,
        paper_size=paper_value,
        design=design_value,
        variant=variant_value,
        chunk_size=qr_chunk_size,
        quiet=quiet_value,
    )
    if not quiet_value:
        actions = [
            f"Saved to {result.output_path}",
            (
                f"QR codes: {result.chunk_count} "
                f"(QR #1 shell + payload QRs up to {result.chunk_size} bytes)"
            ),
            f"Kit variant: {variant_value}",
            "Print this document and store it with your recovery materials.",
        ]
        print_completion_panel("Recovery kit ready", actions, quiet=quiet_value)


def kit(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output PDF path (default: recovery_kit_qr.pdf).",
        ),
    ] = None,
    bundle: Annotated[
        Path | None,
        typer.Option(
            "--bundle",
            "-b",
            help="Custom recovery kit HTML bundle to use instead of the built-in one.",
        ),
    ] = None,
    qr_chunk_size: Annotated[
        int | None,
        typer.Option(
            "--qr-chunk-size",
            help=(
                "Payload bytes per QR chunk (QR #2+ only; the first shell QR is fixed). "
                "Lower values create more codes but are easier to scan (default: %s)."
                % DEFAULT_KIT_CHUNK_SIZE
            ),
        ),
    ] = None,
    variant: Annotated[
        str,
        typer.Option(
            "--variant",
            help="Recovery kit variant: lean (default) or scanner (includes jsQR camera scanning).",
            rich_help_panel="Behavior",
        ),
    ] = "lean",
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            "-c",
            help="Use a custom TOML configuration file.",
            rich_help_panel="Config",
        ),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option(
            "--paper",
            "-p",
            help="Paper size override: A4 (default) or Letter.",
            callback=_paper_callback,
            rich_help_panel="Config",
        ),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option(
            "--design",
            help="Template design folder (auto-discovered under templates/).",
            rich_help_panel="Config",
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            "-q",
            help="Suppress progress output.",
            rich_help_panel="Behavior",
        ),
    ] = False,
) -> None:
    state = _ctx_state(ctx)
    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    design_value = design or (state.design if state is not None else None)
    quiet_value = quiet or (state.quiet if state is not None else False)
    variant_value = variant.strip().lower()
    _run_cli(
        functools.partial(
            _run_kit_render,
            bundle=bundle,
            output=output,
            config_value=config_value,
            paper_value=paper_value,
            design_value=design_value,
            variant_value=variant_value,
            qr_chunk_size=qr_chunk_size,
            quiet_value=quiet_value,
        ),
        debug=state.debug if state is not None else False,
    )
