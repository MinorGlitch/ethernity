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

import importlib.metadata
from collections.abc import Callable
from typing import Any

import typer
from rich.traceback import install as install_rich_traceback

from ..api import console_err


def _run_cli(func: Callable[[], Any], *, debug: bool) -> None:
    if debug:
        install_rich_traceback(show_locals=True)
    try:
        result = func()
    except (OSError, RuntimeError, ValueError, TypeError, LookupError) as exc:
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


def _paper_callback(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in {"A4", "LETTER"}:
        raise typer.BadParameter("paper must be A4 or LETTER")
    return normalized


def _get_version() -> str:
    try:
        return importlib.metadata.version("ethernity")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"
