#!/usr/bin/env python3
from __future__ import annotations

import sys

from rich.console import Console


_console_err = Console(stderr=True)


def _warn(message: str, *, quiet: bool) -> None:
    if quiet:
        return
    _console_err.print(f"[yellow]Warning:[/yellow] {message}")
