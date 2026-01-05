#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Callable
import importlib.metadata
from typing import Any

import typer
from rich.traceback import install as install_rich_traceback

from ..ui import console_err


def _run_cli(func: Callable[[], Any], *, debug: bool) -> None:
    if debug:
        install_rich_traceback(show_locals=True)
    try:
        result = func()
    except Exception as exc:
        if debug:
            raise
        console_err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2)
    if isinstance(result, int) and result != 0:
        raise typer.Exit(code=result)


def _ctx_value(ctx: typer.Context, key: str) -> Any:
    if ctx.obj is None:
        return None
    return ctx.obj.get(key)


def _resolve_config_and_paper(
    ctx: typer.Context,
    config: str | None,
    paper: str | None,
) -> tuple[str | None, str | None]:
    config_value = config or _ctx_value(ctx, "config")
    paper_value = paper or _ctx_value(ctx, "paper")
    if config_value and paper_value:
        raise typer.BadParameter("use either --config or --paper, not both")
    return config_value, paper_value


def _get_version() -> str:
    try:
        return importlib.metadata.version("ethernity")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"
