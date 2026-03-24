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

from collections.abc import Callable
from typing import Any

import typer
from rich.traceback import install as install_rich_traceback

from ethernity.cli.shared.types import CliContextState
from ethernity.cli.shared.ui_api import console_err
from ethernity.version import get_ethernity_version


def _enable_rich_debug_traceback() -> None:
    """Install Rich tracebacks with locals for debug-mode CLI execution."""

    install_rich_traceback(show_locals=True)


def _run_cli(func: Callable[[], Any], *, debug: bool) -> None:
    if debug:
        _enable_rich_debug_traceback()
    try:
        result = func()
    except KeyboardInterrupt:
        if debug:
            raise
        console_err.print("[warning]Cancelled by user.[/warning]")
        raise typer.Exit(code=130)
    except (OSError, RuntimeError, ValueError, TypeError, LookupError) as exc:
        if debug:
            raise
        console_err.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2)
    if isinstance(result, int) and result != 0:
        raise typer.Exit(code=result)


def _ctx_state(ctx: typer.Context) -> CliContextState | None:
    """Return the typed CLI context state when available."""

    obj = ctx.obj
    if isinstance(obj, CliContextState):
        return obj
    return None


def _resolve_config_and_paper(
    ctx: typer.Context,
    config: str | None,
    paper: str | None,
) -> tuple[str | None, str | None]:
    state = _ctx_state(ctx)
    config_value = config or (state.config if state is not None else None)
    paper_value = paper or (state.paper if state is not None else None)
    return config_value, paper_value


def _paper_callback(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in {"A4", "LETTER"}:
        raise typer.BadParameter("paper must be A4 or LETTER")
    return normalized


def _get_version() -> str:
    return get_ethernity_version() or "unknown"
