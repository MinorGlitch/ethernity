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

import questionary
from rich.align import Align
from rich.text import Text

from ethernity.cli.shared.types import MintArgs, RecoverArgs
from ethernity.cli.shared.ui.prompts import prompt_choice_list
from ethernity.cli.shared.ui.runtime import console

HOME_BANNER = "ETHERNITY"

HOME_ACTIONS: list[tuple[str, str] | questionary.Separator | questionary.Choice] = [
    questionary.Separator("Start"),
    questionary.Choice(
        "Create a backup",
        value="backup",
        description="Build a new paper backup set from your files.",
    ),
    questionary.Choice(
        "Recover from a backup",
        value="recover",
        description="Restore files from an existing backup set.",
    ),
    questionary.Separator(" "),
    questionary.Separator("Maintain"),
    questionary.Choice(
        "Add files to a backup",
        value="extend",
        description="Append a new extension to a paper or scanned backup set.",
    ),
    questionary.Choice(
        "Rebuild a backup set",
        value="compact",
        description="Fold extensions into one fresh backup set.",
    ),
    questionary.Choice(
        "Reprint shard documents",
        value="mint",
        description="Generate replacement shard documents from recovery material.",
    ),
    questionary.Separator(" "),
    questionary.Separator("Print"),
    questionary.Choice(
        "Print a recovery kit sheet",
        value="kit",
        description="Render the printable recovery kit page for offline use.",
    ),
]


def render_home_banner() -> None:
    """Render the shared Ethernity ASCII banner and subtitle."""

    banner = Text(HOME_BANNER, style="title")
    subtitle = Text("Secure paper backups and recovery", style="subtitle")
    console.print(Align.center(banner, pad=False))
    console.print(Align.center(subtitle, pad=False))


def prompt_home_action(*, quiet: bool) -> str:
    if not quiet:
        render_home_banner()
    return prompt_choice_list(
        HOME_ACTIONS,
        title="Get started",
        default="backup",
        help_text=None,
    )


def empty_recover_args(
    *,
    config: str | None,
    paper: str | None,
    quiet: bool,
    debug_max_bytes: int = 0,
    debug_reveal_secrets: bool = False,
) -> RecoverArgs:
    return RecoverArgs(
        config=config,
        paper=paper,
        debug_max_bytes=debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        quiet=quiet,
    )


def empty_mint_args(
    *,
    config: str | None,
    paper: str | None,
    design: str | None,
    quiet: bool,
) -> MintArgs:
    return MintArgs(
        config=config,
        paper=paper,
        design=design,
        quiet=quiet,
    )
