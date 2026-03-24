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

from rich.align import Align
from rich.rule import Rule

from ethernity.cli.shared.types import MintArgs, RecoverArgs
from ethernity.cli.shared.ui.prompts import prompt_choice
from ethernity.cli.shared.ui.renderables import panel
from ethernity.cli.shared.ui.runtime import console

HOME_BANNER = r"""
 _____ _____ _     _____ ____  _      _ _____ ___  _
/  __//__ __Y \ /|/  __//  __\/ \  /|/ Y__ __\\  \//
|  \    / \ | |_|||  \  |  \/|| |\ ||| | / \   \  /
|  /_   | | | | |||  /_ |    /| | \||| | | |   / /
\____\  \_/ \_/ \|\____\\_/\_\\_/  \|\_/ \_/  /_/

"""


def render_home_banner() -> None:
    """Render the shared Ethernity ASCII banner and subtitle."""

    banner = Align.center(HOME_BANNER.rstrip("\n"))
    subtitle = Align.center("[subtitle]Secure paper backups and recovery[/subtitle]")
    console.print(panel("Ethernity", banner, style="accent"))
    console.print(subtitle)
    console.print(Rule(style="rule"))


def prompt_home_action(*, quiet: bool) -> str:
    if not quiet:
        render_home_banner()
    return prompt_choice(
        "What would you like to do?",
        {
            "backup": "Create a new backup PDF.",
            "recover": "Recover from an existing backup.",
            "mint": "Mint fresh shard documents from an existing backup.",
            "kit": "Generate a recovery kit QR document.",
        },
        default="backup",
        help_text=(
            "You can also run `ethernity backup`, `ethernity recover`, `ethernity mint`, "
            "or `ethernity kit` directly."
        ),
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
