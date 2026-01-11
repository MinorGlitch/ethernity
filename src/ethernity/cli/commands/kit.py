#!/usr/bin/env python3
from __future__ import annotations

import functools
from pathlib import Path

import typer

from ..api import console
from ..core.common import _ctx_value, _paper_callback, _resolve_config_and_paper, _run_cli
from ..flows.kit import DEFAULT_KIT_CHUNK_SIZE, render_kit_qr_document

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
    chunk_size: int | None,
    quiet_value: bool,
) -> None:
    result = render_kit_qr_document(
        bundle_path=bundle,
        output_path=output,
        config_path=config_value,
        paper_size=paper_value,
        chunk_size=chunk_size,
        quiet=quiet_value,
    )
    if not quiet_value:
        console.print(f"[accent]Recovery kit saved:[/accent] {result.output_path}")
        console.print(
            f"[muted]QR codes:[/muted] {result.chunk_count} "
            f"({result.chunk_size} bytes each)"
        )
        console.print(
            f"[muted]Print this document and store it securely with your recovery materials.[/muted]"
        )


def kit(
    ctx: typer.Context,
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output PDF path (default: recovery_kit_qr.pdf).",
    ),
    bundle: Path | None = typer.Option(
        None,
        "--bundle",
        "-b",
        help="Custom recovery kit HTML bundle to use instead of the built-in one.",
    ),
    chunk_size: int | None = typer.Option(
        None,
        "--chunk-size",
        help=(
            "Data per QR code in bytes. Lower values create more codes but are easier "
            "to scan (default: %s)." % DEFAULT_KIT_CHUNK_SIZE
        ),
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Use a custom TOML configuration file.",
        rich_help_panel="Config",
    ),
    paper: str | None = typer.Option(
        None,
        "--paper",
        "-p",
        help="Paper size preset: A4 (default) or LETTER.",
        callback=_paper_callback,
        rich_help_panel="Config",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress progress output.",
        rich_help_panel="Behavior",
    ),
) -> None:
    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    quiet_value = quiet or bool(_ctx_value(ctx, "quiet"))
    _run_cli(
        functools.partial(
            _run_kit_render,
            bundle=bundle,
            output=output,
            config_value=config_value,
            paper_value=paper_value,
            chunk_size=chunk_size,
            quiet_value=quiet_value,
        ),
        debug=bool(_ctx_value(ctx, "debug")),
    )
