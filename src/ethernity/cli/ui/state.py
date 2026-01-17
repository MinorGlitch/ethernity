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
from dataclasses import dataclass

from rich.console import Console
from rich.text import Text
from rich.theme import Theme


def isatty(stream, fallback) -> bool:
    if stream is not None:
        try:
            return bool(stream.isatty())
        except (OSError, ValueError, AttributeError):
            return False
    return bool(getattr(fallback, "isatty", lambda: False)())


THEME = Theme(
    {
        "title": "bold cyan",
        "subtitle": "dim",
        "accent": "cyan",
        "success": "cyan",
        "warning": "yellow",
        "error": "red",
        "rule": "cyan",
        "panel": "cyan",
        "muted": "dim",
    }
)


@dataclass
class WizardState:
    name: str
    total_steps: int
    step: int = 0
    quiet: bool = False


@dataclass
class UIContext:
    theme: Theme
    console: Console
    console_err: Console
    animations_enabled: bool = True
    wizard_state: WizardState | None = None


def _build_console(*, stderr: bool) -> Console:
    raw = sys.__stderr__ if stderr else sys.__stdout__
    fallback = sys.stderr if stderr else sys.stdout
    return Console(stderr=stderr, theme=THEME, force_terminal=isatty(raw, fallback))


def create_default_context() -> UIContext:
    return UIContext(
        theme=THEME,
        console=_build_console(stderr=False),
        console_err=_build_console(stderr=True),
    )


DEFAULT_CONTEXT = create_default_context()


def get_context() -> UIContext:
    return DEFAULT_CONTEXT


def format_hint(help_text: str, *, context: UIContext | None = None) -> Text:
    return Text(help_text, style="dim italic")
