#!/usr/bin/env python3
from __future__ import annotations

import typer

from ..core.common import _ctx_value, _paper_callback, _resolve_config_and_paper, _run_cli


def register(app: typer.Typer) -> None:
    @app.command(help="Render a demo PDF using current settings.", hidden=True)
    def demo(
        ctx: typer.Context,
        config: str | None = typer.Option(None, "--config", help="Config file path."),
        paper: str | None = typer.Option(
            None,
            "--paper",
            help="Paper size preset.",
            callback=_paper_callback,
        ),
    ) -> None:
        config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
        try:
            from demo.render_demo import main as render_demo_main
        except ModuleNotFoundError:
            raise typer.BadParameter("demo scripts not available; run from the repo root")
        _run_cli(
            lambda: render_demo_main(config_value, paper_value),
            debug=bool(_ctx_value(ctx, "debug")),
        )
