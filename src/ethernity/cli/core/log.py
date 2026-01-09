#!/usr/bin/env python3
from __future__ import annotations

from ..ui import console_err


def _warn(message: str, *, quiet: bool) -> None:
    if quiet:
        return
    console_err.print(f"[yellow]Warning:[/yellow] {message}")
