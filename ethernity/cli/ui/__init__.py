#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

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
from rich.table import Table
from rich.text import Text
from rich.spinner import Spinner
from rich.tree import Tree

from ..core.log import _warn
from . import state as ui_state
from .prompts import (
    _print_prompt_header,
    _prompt_choice,
    _prompt_choice_list,
    _prompt_int,
    _prompt_multiline,
    _prompt_optional,
    _prompt_optional_path,
    _prompt_optional_secret,
    _prompt_required,
    _prompt_required_path,
    _prompt_required_paths,
    _prompt_required_secret,
    _prompt_yes_no,
    _validate_path,
)

ANIMATIONS_ENABLED = True
DEBUG_MAX_BYTES_DEFAULT = 4096

THEME = ui_state.THEME
console = ui_state.console
console_err = ui_state.console_err
_format_hint = ui_state._format_hint

HOME_BANNER = r"""
 _____ _____ _     _____ ____  _      _ _____ ___  _
/  __//__ __Y \ /|/  __//  __\/ \  /|/ Y__ __\\  \//
|  \    / \ | |_|||  \  |  \/|| |\ ||| | / \   \  / 
|  /_   | | | | |||  /_ |    /| | \||| | | |   / /  
\____\  \_/ \_/ \|\____\\_/\_\\_/  \|\_/ \_/  /_/   
                                                    
"""


@dataclass
class WizardState:
    name: str
    total_steps: int
    step: int = 0
    quiet: bool = False


WIZARD_STATE: WizardState | None = None


def _clear_screen() -> None:
    try:
        console.clear()
    except Exception:
        pass
    if os.name == "nt":
        try:
            os.system("cls")
        except Exception:
            pass
    elif console.is_terminal is False:
        try:
            os.system("clear")
        except Exception:
            pass


def _configure_ui(*, no_color: bool, no_animations: bool) -> None:
    global ANIMATIONS_ENABLED
    ANIMATIONS_ENABLED = not no_animations
    console.no_color = no_color
    console_err.no_color = no_color


@contextmanager
def _wizard_flow(*, name: str, total_steps: int, quiet: bool):
    global WIZARD_STATE
    previous = WIZARD_STATE
    WIZARD_STATE = WizardState(name=name, total_steps=total_steps, quiet=quiet)
    try:
        yield WIZARD_STATE
    finally:
        WIZARD_STATE = previous


@contextmanager
def _wizard_stage(title: str, *, help_text: str | None = None):
    state = WIZARD_STATE
    previous_style = ui_state.PROMPT_STYLE
    if state is not None and not state.quiet:
        if state.step > 0:
            _clear_screen()
        state.step += 1
        step_label = f"Step {state.step}/{state.total_steps} - {title}"
        console.print(Rule(Text(step_label, style="title"), style="rule", align="left"))
        if help_text:
            console.print(Padding(ui_state._format_hint(help_text), (0, 0, 0, 1)))
        ui_state.PROMPT_STYLE = "compact"
    try:
        yield
    finally:
        ui_state.PROMPT_STYLE = previous_style


@contextmanager
def _progress(*, quiet: bool):
    if quiet:
        yield None
        return
    force_render = ui_state._isatty(sys.__stdout__, sys.stdout)
    if ANIMATIONS_ENABLED:
        progress = Progress(
            SpinnerColumn(style="accent"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
            disable=not force_render,
        )
    else:
        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
            refresh_per_second=2,
            disable=not force_render,
        )
    with progress:
        yield progress


@contextmanager
def _status(message: str, *, quiet: bool):
    if quiet:
        yield None
        return
    if not ANIMATIONS_ENABLED:
        console.print(f"[subtitle]{message}[/subtitle]")
        yield None
        return
    spinner = Spinner("dots", text=Text(message, style="subtitle"))
    with Live(
        spinner,
        console=console,
        transient=False,
        refresh_per_second=12,
    ) as live:
        live.refresh()
        try:
            console.file.flush()
        except Exception:
            pass
        try:
            yield live
        finally:
            live.update(Text(f"✓ {message}", style="success"), refresh=True)


def _build_kv_table(rows: Sequence[tuple[str, str]], *, title: str | None = None) -> Table:
    table = Table(title=title, show_header=False, box=box.SIMPLE, show_lines=False)
    table.add_column("Field", style="bold", no_wrap=True)
    table.add_column("Value")
    for key, value in rows:
        table.add_row(str(key), str(value))
    return table


def _build_review_table(rows: Sequence[tuple[str, str]]) -> Table:
    table = Table(show_header=False, box=box.MINIMAL, show_lines=False, pad_edge=False)
    table.add_column("Field", style="muted", no_wrap=True)
    table.add_column("Value")
    for key, value in rows:
        table.add_row(str(key), str(value))
    return table


def _build_action_list(items: Sequence[str]) -> Table:
    table = Table.grid(padding=(0, 1))
    table.add_column(no_wrap=True)
    table.add_column()
    for item in items:
        table.add_row("-", Text(item))
    return table


def _build_list_table(title: str, items: Sequence[str]) -> Table:
    table = Table(title=title, show_header=False, box=box.ASCII)
    table.add_column("Value")
    for item in items:
        table.add_row(str(item))
    return table


def _panel(title: str, renderable, *, style: str = "panel") -> Panel:
    return Panel(
        renderable,
        title=title,
        title_align="left",
        border_style=style,
        box=box.ROUNDED,
        padding=(1, 2),
    )


def _print_completion_panel(
    title: str,
    items: Sequence[str],
    *,
    quiet: bool,
    use_err: bool = False,
) -> None:
    if quiet:
        return
    output = console_err if use_err else console
    output.print(_panel(title, _build_action_list(items), style="success"))


def _build_outputs_tree(
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


def _build_recovered_tree(
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


def _prompt_home_action(*, quiet: bool) -> str:
    if not quiet:
        banner = Align.center(HOME_BANNER.rstrip("\n"))
        subtitle = Align.center("[subtitle]Secure paper backups and recovery[/subtitle]")
        console.print(_panel("Ethernity", banner, style="accent"))
        console.print(subtitle)
        console.print(Rule(style="rule"))
    return _prompt_choice(
        "What would you like to do?",
        {
            "backup": "Create a new backup PDF.",
            "recover": "Recover from an existing backup.",
        },
        default="backup",
        help_text="You can also run `ethernity backup` or `ethernity recover` directly.",
    )


def _empty_recover_args(
    *, config: str | None, paper: str | None, quiet: bool
) -> argparse.Namespace:
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


def __getattr__(name: str):
    if name == "PROMPT_STYLE":
        return ui_state.PROMPT_STYLE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ANIMATIONS_ENABLED",
    "DEBUG_MAX_BYTES_DEFAULT",
    "HOME_BANNER",
    "PROMPT_STYLE",
    "THEME",
    "WizardState",
    "console",
    "console_err",
    "_build_action_list",
    "_build_kv_table",
    "_build_list_table",
    "_build_outputs_tree",
    "_build_recovered_tree",
    "_build_review_table",
    "_configure_ui",
    "_empty_recover_args",
    "_format_hint",
    "_panel",
    "_print_completion_panel",
    "_print_prompt_header",
    "_prompt_choice",
    "_prompt_choice_list",
    "_prompt_home_action",
    "_prompt_int",
    "_prompt_multiline",
    "_prompt_optional",
    "_prompt_optional_path",
    "_prompt_optional_secret",
    "_prompt_required",
    "_prompt_required_path",
    "_prompt_required_paths",
    "_prompt_required_secret",
    "_prompt_yes_no",
    "_progress",
    "_status",
    "_validate_path",
    "_warn",
    "_wizard_flow",
    "_wizard_stage",
]
