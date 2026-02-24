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
import shlex
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from ...config import resolve_config_path
from ..api import console
from ..core.common import _ctx_state, _run_cli

_CONFIG_HELP = (
    "Open the active TOML config in an editor.\n\n"
    "If no editor is specified, Ethernity uses $VISUAL / $EDITOR when set, otherwise it opens\n"
    "the file with the system default application.\n\n"
    "Examples:\n"
    "  ethernity config\n"
    "  ethernity config --config ./my_config.toml\n"
    "  ethernity config --editor nano\n"
    '  ethernity config --editor "code -w"\n'
)


def register(app: typer.Typer) -> None:
    app.command(help=_CONFIG_HELP)(config)


def config(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            "-c",
            help="Open this config file (overrides the default).",
            rich_help_panel="Config",
        ),
    ] = None,
    editor: Annotated[
        str | None,
        typer.Option(
            "--editor",
            "-e",
            help="Editor command (defaults to $VISUAL/$EDITOR; use 'default' for system opener).",
            rich_help_panel="Behavior",
        ),
    ] = None,
    print_path: Annotated[
        bool,
        typer.Option(
            "--print-path",
            help="Print the resolved config path and exit.",
            rich_help_panel="Behavior",
        ),
    ] = False,
) -> None:
    state = _ctx_state(ctx)
    config_value = config or (state.config if state is not None else None)
    quiet_value = state.quiet if state is not None else False
    debug_value = state.debug if state is not None else False

    def _run() -> None:
        path = resolve_config_path(config_value)
        if print_path:
            console.print(str(path))
            return
        _open_in_editor(path, editor=editor, quiet=quiet_value)

    _run_cli(_run, debug=debug_value)


def _open_in_editor(path: Path, *, editor: str | None, quiet: bool) -> None:
    resolved = path.expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"config file not found: {resolved}")

    editor_cmd = _resolve_editor_command(editor)
    if editor_cmd is None:
        if not quiet:
            console.print(f"[dim]Opening {resolved}...[/dim]")
        typer.launch(str(resolved))
        return

    if not quiet:
        console.print(f"[dim]Opening {resolved} with {' '.join(editor_cmd)}...[/dim]")
    subprocess.run([*editor_cmd, str(resolved)], check=False)


def _resolve_editor_command(editor: str | None) -> list[str] | None:
    if editor is not None:
        value = editor.strip()
        if not value:
            return None
        if value.lower() in {"default", "system"}:
            return None
        return shlex.split(value, posix=os.name != "nt")

    value = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ""
    value = value.strip()
    if not value:
        return None
    return shlex.split(value, posix=os.name != "nt")
