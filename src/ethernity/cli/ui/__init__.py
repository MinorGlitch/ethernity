#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
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

from .prompts import (
    print_prompt_header,
    prompt_choice,
    prompt_choice_list,
    prompt_int,
    prompt_multiline,
    prompt_optional,
    prompt_optional_path,
    prompt_optional_secret,
    prompt_required,
    prompt_required_path,
    prompt_required_paths,
    prompt_required_secret,
    prompt_yes_no,
    validate_path,
)
from .state import UIContext, WizardState, format_hint, get_context, isatty

DEBUG_MAX_BYTES_DEFAULT = 4096

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
    except Exception:
        pass
    if os.name == "nt":
        try:
            os.system("cls")
        except Exception:
            pass
    elif context.console.is_terminal is False:
        try:
            os.system("clear")
        except Exception:
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
def wizard_flow(*, name: str, total_steps: int, quiet: bool, context: UIContext | None = None):
    context = _resolve_context(context)
    previous = context.wizard_state
    context.wizard_state = WizardState(name=name, total_steps=total_steps, quiet=quiet)
    try:
        yield context.wizard_state
    finally:
        context.wizard_state = previous


@contextmanager
def wizard_stage(title: str, *, help_text: str | None = None, context: UIContext | None = None):
    context = _resolve_context(context)
    state = context.wizard_state
    previous_style = context.prompt_style
    if state is not None and not state.quiet:
        if state.step > 0:
            clear_screen(context=context)
        state.step += 1
        step_label = f"Step {state.step}/{state.total_steps} - {title}"
        context.console.print(Rule(Text(step_label, style="title"), style="rule", align="left"))
        if help_text:
            context.console.print(Padding(format_hint(help_text), (0, 0, 0, 1)))
        context.prompt_style = "compact"
    try:
        yield
    finally:
        context.prompt_style = previous_style


@contextmanager
def progress(*, quiet: bool, context: UIContext | None = None):
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
def status(message: str, *, quiet: bool, context: UIContext | None = None):
    context = _resolve_context(context)
    if quiet:
        yield None
        return
    if not context.animations_enabled:
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
        live.refresh()
        try:
            context.console.file.flush()
        except Exception:
            pass
        try:
            yield live
        finally:
            live.update(Text(f"✓ {message}", style="success"), refresh=True)


def build_kv_table(rows: Sequence[tuple[str, str]], *, title: str | None = None) -> Table:
    table = Table(title=title, show_header=False, box=box.SIMPLE, show_lines=False)
    table.add_column("Field", style="bold", no_wrap=True)
    table.add_column("Value")
    for key, value in rows:
        table.add_row(str(key), str(value))
    return table


def build_review_table(rows: Sequence[tuple[str, str]]) -> Table:
    table = Table(show_header=False, box=box.MINIMAL, show_lines=False, pad_edge=False)
    table.add_column("Field", style="muted", no_wrap=True)
    table.add_column("Value")
    for key, value in rows:
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
) -> Tree:
    tree = Tree("Documents", guide_style="muted")
    tree.add(f"[accent]QR document[/accent] {qr_path}")
    tree.add(f"[accent]Recovery document[/accent] {recovery_path}")
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
) -> Tree | None:
    if not output_path:
        return None
    if len(entries) == 1:
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
        },
        default="backup",
        help_text="You can also run `ethernity backup` or `ethernity recover` directly.",
    )


def empty_recover_args(*, config: str | None, paper: str | None, quiet: bool) -> argparse.Namespace:
    return argparse.Namespace(
        config=config,
        paper=paper,
        fallback_file=None,
        frames_file=None,
        frames_encoding="auto",
        scan=[],
        passphrase=None,
        shard_fallback_file=[],
        shard_frames_file=[],
        shard_frames_encoding="auto",
        auth_fallback_file=None,
        auth_frames_file=None,
        auth_frames_encoding="auto",
        output=None,
        allow_unsigned=False,
        assume_yes=False,
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
    "prompt_optional_secret",
    "prompt_required",
    "prompt_required_path",
    "prompt_required_paths",
    "prompt_required_secret",
    "prompt_yes_no",
    "progress",
    "status",
    "validate_path",
    "wizard_flow",
    "wizard_stage",
]
