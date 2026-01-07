#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import typer

from ..core.common import _ctx_value, _paper_callback, _resolve_config_and_paper, _run_cli
from ..flows.kit import DEFAULT_KIT_CHUNK_SIZE, render_kit_qr_document
from ..ui import console


def register(app: typer.Typer) -> None:
    @app.command(
        help=(
            "Render the recovery kit as a QR document.\n\n"
            "The QR payloads contain the raw bundled HTML (no encryption or framing)."
        )
    )
    def kit(
        ctx: typer.Context,
        output: Path | None = typer.Option(
            None,
            "--output",
            "-o",
            help="Write the QR document to this path.",
        ),
        bundle: Path | None = typer.Option(
            None,
            "--bundle",
            help="Path to the bundled recovery kit HTML.",
        ),
        chunk_size: int | None = typer.Option(
            None,
            "--chunk-size",
            help=(
                "Bytes per QR payload (default: %s or the QR max, whichever is lower)."
                % DEFAULT_KIT_CHUNK_SIZE
            ),
        ),
        config: str | None = typer.Option(
            None,
            "--config",
            help="Use this TOML config.",
            rich_help_panel="Config",
        ),
        paper: str | None = typer.Option(
            None,
            "--paper",
            help="Paper preset (A4/LETTER).",
            callback=_paper_callback,
            rich_help_panel="Config",
        ),
        quiet: bool = typer.Option(
            False,
            "--quiet",
            help="Hide non-error output.",
            rich_help_panel="Behavior",
        ),
    ) -> None:
        config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
        quiet_value = quiet or bool(_ctx_value(ctx, "quiet"))

        def _run() -> None:
            result = render_kit_qr_document(
                bundle_path=bundle,
                output_path=output,
                config_path=config_value,
                paper_size=paper_value,
                chunk_size=chunk_size,
                quiet=quiet_value,
            )
            if not quiet_value:
                console.print(
                    f"[accent]Kit QR document:[/accent] {result.output_path}"
                )
                console.print(
                    f"[muted]Chunks:[/muted] {result.chunk_count} "
                    f"([muted]{result.chunk_size} bytes each[/muted])"
                )

        _run_cli(_run, debug=bool(_ctx_value(ctx, "debug")))
