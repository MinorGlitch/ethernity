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

import os
import sys
from collections.abc import Generator, Sequence
from contextlib import contextmanager

from rich import box
from rich.align import Align
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
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
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from ..core.types import RecoverArgs
from .prompts import (
    print_prompt_header,
    prompt_choice,
    prompt_choice_list,
    prompt_int,
    prompt_multiline,
    prompt_optional,
    prompt_optional_path,
    prompt_optional_path_with_picker,
    prompt_optional_secret,
    prompt_path_with_picker,
    prompt_paths_with_picker,
    prompt_required,
    prompt_required_path,
    prompt_required_paths,
    prompt_required_secret,
    prompt_select_path,
    prompt_select_paths,
    prompt_yes_no,
    validate_path,
)
from .state import UIContext, WizardState, format_hint, get_context, isatty

DEBUG_MAX_BYTES_DEFAULT = 1024

DEFAULT_CONTEXT = get_context()
THEME = DEFAULT_CONTEXT.theme
console = DEFAULT_CONTEXT.console
console_err = DEFAULT_CONTEXT.console_err


def _resolve_context(context: UIContext | None) -> UIContext:
    return context or DEFAULT_CONTEXT


HOME_BANNER = r"""
 _____ _____ _     _____ ____  _      _ _____ ___  _
/  __//__ __Y \ /|/  __//  __\/ \  /|/ Y__ __\\  \//
|  \    / \ | |_|||  \  |  \/|| |\ ||| | / \   \  /
|  /_   | | | | |||  /_ |    /| | \||| | | |   / /
\____\  \_/ \_/ \|\____\\_/\_\\_/  \|\_/ \_/  /_/

"""


def clear_screen(*, context: UIContext | None = None) -> None:
    context = _resolve_context(context)
    try:
        context.console.clear()
    except (OSError, ValueError):
        pass
    if os.name == "nt":
        try:
            os.system("cls")
        except OSError:
            pass
    elif context.console.is_terminal is False:
        try:
            os.system("clear")
        except OSError:
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


def build_kv_table(rows: Sequence[tuple[str, str]], *, title: str | None = None) -> Table:
    table = Table(title=title, show_header=False, box=box.SIMPLE, show_lines=False)
    table.add_column("Field", style="bold", no_wrap=True)
    table.add_column("Value")
    for key, value in rows:
        table.add_row(str(key), str(value))
    return table


def build_review_table(rows: Sequence[tuple[str, str | None]]) -> Table:
    table = Table(show_header=False, box=box.MINIMAL, show_lines=False, pad_edge=False)
    table.add_column("Field", style="muted", no_wrap=True)
    table.add_column("Value")
    for key, value in rows:
        if value is None:
            table.add_row(Text(str(key), style="accent"), Text(""), end_section=True)
            continue
        table.add_row(str(key), str(value))
    return table


def build_action_list(items: Sequence[str]) -> Table:
    table = Table.grid(padding=(0, 1))
    table.add_column(no_wrap=True)
    table.add_column()
    for item in items:
        table.add_row("-", Text(item))
    return table


def build_list_table(title: str, items: Sequence[str]) -> Table:
    table = Table(title=title, show_header=False, box=box.ASCII)
    table.add_column("Value")
    for item in items:
        table.add_row(str(item))
    return table


def panel(title: str, renderable, *, style: str = "panel") -> Panel:
    return Panel(
        renderable,
        title=title,
        title_align="left",
        border_style=style,
        box=box.ROUNDED,
        padding=(1, 2),
    )


def print_completion_panel(
    title: str,
    items: Sequence[str],
    *,
    quiet: bool,
    use_err: bool = False,
) -> None:
    if quiet:
        return
    output = console_err if use_err else console
    output.print(panel(title, build_action_list(items), style="success"))


def build_outputs_tree(
    qr_path: str,
    recovery_path: str,
    shard_paths: Sequence[str],
    signing_key_shard_paths: Sequence[str],
    kit_index_path: str | None = None,
) -> Tree:
    tree = Tree("Documents", guide_style="muted")
    tree.add(f"[accent]QR document[/accent] {qr_path}")
    tree.add(f"[accent]Recovery document[/accent] {recovery_path}")
    if kit_index_path:
        tree.add(f"[accent]Recovery kit index[/accent] {kit_index_path}")
    if shard_paths:
        shards = tree.add(f"[accent]Shard documents[/accent] ({len(shard_paths)})")
        for path in shard_paths:
            shards.add(path)
    if signing_key_shard_paths:
        shards = tree.add(
            f"[accent]Signing-key shard documents[/accent] ({len(signing_key_shard_paths)})"
        )
        for path in signing_key_shard_paths:
            shards.add(path)
    return tree


def build_recovered_tree(
    entries: Sequence[tuple[object, bytes]],
    output_path: str | None,
    *,
    single_entry_output_is_directory: bool = False,
) -> Tree | None:
    if not output_path:
        return None
    if len(entries) == 1 and not single_entry_output_is_directory:
        tree = Tree("Output file", guide_style="muted")
        tree.add(output_path)
        return tree
    tree = Tree(output_path, guide_style="muted")
    for entry, _data in entries:
        rel = getattr(entry, "path", "payload.bin")
        tree.add(rel)
    return tree


def prompt_home_action(*, quiet: bool) -> str:
    if not quiet:
        banner = Align.center(HOME_BANNER.rstrip("\n"))
        subtitle = Align.center("[subtitle]Secure paper backups and recovery[/subtitle]")
        console.print(panel("Ethernity", banner, style="accent"))
        console.print(subtitle)
        console.print(Rule(style="rule"))
    return prompt_choice(
        "What would you like to do?",
        {
            "backup": "Create a new backup PDF.",
            "recover": "Recover from an existing backup.",
            "kit": "Generate a recovery kit QR document.",
        },
        default="backup",
        help_text=(
            "You can also run `ethernity backup`, `ethernity recover`, or `ethernity kit` directly."
        ),
    )


def empty_recover_args(
    *,
    config: str | None,
    paper: str | None,
    quiet: bool,
    debug_max_bytes: int = 0,
    debug_reveal_secrets: bool = False,
) -> RecoverArgs:
    return RecoverArgs(
        config=config,
        paper=paper,
        debug_max_bytes=debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        quiet=quiet,
    )


__all__ = [
    "DEBUG_MAX_BYTES_DEFAULT",
    "HOME_BANNER",
    "THEME",
    "WizardState",
    "console",
    "console_err",
    "build_action_list",
    "build_kv_table",
    "build_list_table",
    "build_outputs_tree",
    "build_recovered_tree",
    "build_review_table",
    "configure_ui",
    "empty_recover_args",
    "format_hint",
    "panel",
    "print_completion_panel",
    "print_prompt_header",
    "prompt_choice",
    "prompt_choice_list",
    "prompt_home_action",
    "prompt_int",
    "prompt_multiline",
    "prompt_optional",
    "prompt_optional_path",
    "prompt_optional_path_with_picker",
    "prompt_optional_secret",
    "prompt_path_with_picker",
    "prompt_required",
    "prompt_required_path",
    "prompt_required_paths",
    "prompt_required_secret",
    "prompt_paths_with_picker",
    "prompt_select_path",
    "prompt_select_paths",
    "prompt_yes_no",
    "ui_screen_mode",
    "progress",
    "status",
    "validate_path",
    "wizard_flow",
    "wizard_stage",
]
