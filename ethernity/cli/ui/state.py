#!/usr/bin/env python3
from __future__ import annotations

import sys

from rich.console import Console
from rich.text import Text
from rich.theme import Theme


def _isatty(stream, fallback) -> bool:
    if stream is not None:
        try:
            return bool(stream.isatty())
        except Exception:
            return False
    return bool(getattr(fallback, "isatty", lambda: False)())


THEME = Theme(
    {
        "title": "bold cyan",
        "subtitle": "dim",
        "accent": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red",
        "rule": "blue",
        "panel": "cyan",
        "muted": "dim",
    }
)

console = Console(theme=THEME, force_terminal=_isatty(sys.__stdout__, sys.stdout))
console_err = Console(stderr=True, theme=THEME, force_terminal=_isatty(sys.__stderr__, sys.stderr))

PROMPT_STYLE = "full"


def _format_hint(help_text: str) -> Text:
    hint = Text("Hint: ", style="muted")
    hint.append(help_text, style="subtitle")
    return hint
