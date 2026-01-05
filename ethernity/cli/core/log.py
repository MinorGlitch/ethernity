#!/usr/bin/env python3
from __future__ import annotations

import sys

try:
    from rich.console import Console
except Exception:  # pragma: no cover - best-effort rich support
    Console = None


_console_err = Console(stderr=True) if Console is not None else None


def _warn(message: str, *, quiet: bool) -> None:
    if quiet:
        return
    if _console_err is not None:
        _console_err.print(f"[yellow]Warning:[/yellow] {message}")
    else:
        print(f"Warning: {message}", file=sys.stderr)
