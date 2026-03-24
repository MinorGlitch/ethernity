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

import typer

from ethernity.cli.features.api import command as api_command
from ethernity.cli.features.backup import command as backup_command
from ethernity.cli.features.config import command as config_command
from ethernity.cli.features.kit import command as kit_command
from ethernity.cli.features.mint import command as mint_command
from ethernity.cli.features.recover import command as recover_command
from ethernity.cli.features.render import command as render_command


def register(app: typer.Typer) -> None:
    api_command.register(app)
    backup_command.register(app)
    config_command.register(app)
    kit_command.register(app)
    mint_command.register(app)
    render_command.register(app)
    recover_command.register(app)
