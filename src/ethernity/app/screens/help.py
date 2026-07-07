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

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


@dataclass(frozen=True)
class HelpMode:
    key: str
    label: str
    description: str
    use_when: str
    avoid_when: str
    needs: tuple[str, ...]


@dataclass(frozen=True)
class HelpContent:
    title: str
    intro: str
    mode: HelpMode


class HelpScreen(ModalScreen[None]):
    """Contextual help for the active workflow."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, content: HelpContent) -> None:
        super().__init__()
        self._content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="help-modal"):
            yield Static(self._content.title, id="help-title")
            yield Static(self._content.intro, id="help-intro")
            with Vertical(id="help-body"):
                yield Static("What it does", classes="help-section-title")
                yield Static(self._content.mode.description, id="help-description")
                yield Static("Use it when", classes="help-section-title")
                yield Static(self._content.mode.use_when, id="help-use-when")
                yield Static("Do not use it when", classes="help-section-title")
                yield Static(self._content.mode.avoid_when, id="help-avoid-when")
                yield Static("You will choose", classes="help-section-title")
                yield Static(_needs_text(self._content.mode.needs), id="help-needs")
            with Horizontal(id="help-actions"):
                yield Static("", id="help-action-spacer")
                yield Button("Close", id="help-close", compact=True)

    def on_mount(self) -> None:
        self.query_one("#help-close", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "help-close":
            return
        event.stop()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


def _needs_text(needs: tuple[str, ...]) -> str:
    return "\n".join(f"- {need}" for need in needs)
