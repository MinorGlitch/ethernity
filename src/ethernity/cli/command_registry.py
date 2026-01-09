#!/usr/bin/env python3
from __future__ import annotations

import typer

from .commands import (
    backup as backup_command,
    kit as kit_command,
    manpage as manpage_command,
    recover as recover_command,
)


def register(app: typer.Typer) -> None:
    backup_command.register(app)
    kit_command.register(app)
    recover_command.register(app)
    manpage_command.register(app)
