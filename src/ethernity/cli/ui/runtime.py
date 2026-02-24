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

from rich.live import Live
from rich.padding import Padding
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.spinner import Spinner
from rich.text import Text

from .state import UIContext, WizardState, format_hint, get_context, isatty

DEBUG_MAX_BYTES_DEFAULT = 1024

DEFAULT_CONTEXT = get_context()
THEME = DEFAULT_CONTEXT.theme
console = DEFAULT_CONTEXT.console
console_err = DEFAULT_CONTEXT.console_err


def _resolve_context(context: UIContext | None) -> UIContext:
    return context or DEFAULT_CONTEXT


def clear_screen(*, context: UIContext | None = None) -> None:
    context = _resolve_context(context)
    try:
        context.console.clear()
    except (OSError, ValueError):
        pass


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
def ui_screen_mode(
    *,
    enabled: bool = True,
    quiet: bool = False,
    context: UIContext | None = None,
) -> Generator[None, None, None]:
    context = _resolve_context(context)
    previous_screen_mode = context.screen_mode
    previous_compact_prompt_headers = context.compact_prompt_headers
    previous_stage_prompt_count = context.stage_prompt_count
    active = enabled and not quiet
    context.screen_mode = active
    context.compact_prompt_headers = active
    context.stage_prompt_count = 0
    try:
        if active:
            clear_screen(context=context)
        yield
    finally:
        context.screen_mode = previous_screen_mode
        context.compact_prompt_headers = previous_compact_prompt_headers
        context.stage_prompt_count = previous_stage_prompt_count


@contextmanager
def wizard_flow(
    *, name: str, total_steps: int, quiet: bool, context: UIContext | None = None
) -> Generator[WizardState, None, None]:
    context = _resolve_context(context)
    previous = context.wizard_state
    context.wizard_state = WizardState(name=name, total_steps=total_steps, quiet=quiet)
    try:
        yield context.wizard_state
    finally:
        context.wizard_state = previous


@contextmanager
def wizard_stage(
    title: str, *, help_text: str | None = None, context: UIContext | None = None
) -> Generator[None, None, None]:
    context = _resolve_context(context)
    state = context.wizard_state
    context.stage_prompt_count = 0
    if state is not None and not state.quiet:
        if state.step > 0:
            clear_screen(context=context)
            context.console.print()
        state.step += 1
        step_label = f"Step {state.step}/{state.total_steps} - {title}"
        context.console.print(Rule(Text(step_label, style="title"), style="rule", align="left"))
        if help_text:
            context.console.print(Padding(format_hint(help_text), (0, 0, 0, 1)))
    yield


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
    transient = context.screen_mode
    spinner = Spinner("dots", text=Text(message, style="subtitle"))
    with Live(
        spinner,
        console=context.console,
        transient=transient,
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
            if not transient:
                try:
                    live.update(Text(f"{message} ✓", style="success"), refresh=True)
                except (OSError, ValueError):
                    pass
