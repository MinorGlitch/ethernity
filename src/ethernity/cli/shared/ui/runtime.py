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

import sys
from collections.abc import Generator
from contextlib import contextmanager

from rich.console import Console
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.spinner import Spinner
from rich.text import Text

from ethernity.cli.shared.ui.state import (
    UIContext,
    get_context,
    isatty,
)

DEBUG_MAX_BYTES_DEFAULT = 1024

DEFAULT_CONTEXT = get_context()
THEME = DEFAULT_CONTEXT.theme
console = DEFAULT_CONTEXT.console
console_err = DEFAULT_CONTEXT.console_err


def _resolve_context(context: UIContext | None) -> UIContext:
    return context or DEFAULT_CONTEXT


def configure_ui(
    *,
    no_color: bool,
    no_animations: bool,
    context: UIContext | None = None,
) -> None:
    context = _resolve_context(context)
    context.animations_enabled = not no_animations
    context.console.no_color = no_color
    context.console_err.no_color = no_color


@contextmanager
def progress(
    *, quiet: bool, context: UIContext | None = None
) -> Generator[Progress | None, None, None]:
    context = _resolve_context(context)
    if quiet:
        yield None
        return
    force_render = isatty(sys.__stdout__, sys.stdout)
    if context.animations_enabled:
        progress_bar = Progress(
            SpinnerColumn(style="accent"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=context.console,
            transient=True,
            disable=not force_render,
        )
    else:
        progress_bar = Progress(
            TextColumn("[progress.description]{task.description}"),
            console=context.console,
            transient=True,
            refresh_per_second=2,
            disable=not force_render,
        )
    with progress_bar:
        yield progress_bar


@contextmanager
def status(
    message: str, *, quiet: bool, context: UIContext | None = None
) -> Generator[Live | None, None, None]:
    context = _resolve_context(context)
    if quiet:
        yield None
        return
    force_render = isatty(sys.__stdout__, sys.stdout)
    if not context.animations_enabled or not force_render:
        context.console.print(f"[subtitle]{message}[/subtitle]")
        yield None
        return
    spinner = Spinner("dots", text=Text(message, style="subtitle"))
    with Live(
        spinner,
        console=context.console,
        transient=False,
        refresh_per_second=12,
    ) as live:
        try:
            live.refresh()
        except (OSError, ValueError):
            pass
        try:
            context.console.file.flush()
        except (OSError, ValueError):
            pass
        try:
            yield live
        finally:
            try:
                live.update(Text(f"{message} ✓", style="success"), refresh=True)
            except (OSError, ValueError):
                pass


@contextmanager
def plain_status(
    message: str,
    *,
    quiet: bool = False,
    console: Console,
) -> Generator[Live | None, None, None]:
    """Render the legacy unstyled spinner used by document workflows."""

    if quiet:
        yield None
        return
    if not isatty(sys.__stdout__, sys.stdout):
        console.print(message)
        yield None
        return
    spinner = Spinner("dots", text=Text(message))
    with Live(spinner, console=console, transient=False, refresh_per_second=12) as live:
        yield live
