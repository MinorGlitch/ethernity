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

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Label, Static, TextArea

from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, modal_action_row


class PasteTextScreen(EthernityModalScreen[str | None]):
    """Modal for pasting multiline recovery text."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str,
        prompt: str,
        value: str = "",
        placeholder: str = "",
    ) -> None:
        super().__init__()
        self._field_title = title
        self._prompt = prompt
        self._value = value
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="paste-text-modal"):
            yield Static(self._field_title, id="paste-text-title")
            yield Label(self._prompt, id="paste-text-prompt")
            yield TextArea(
                self._value,
                placeholder=self._placeholder,
                soft_wrap=True,
                show_line_numbers=False,
                id="paste-text-input",
            )
            yield modal_action_row(
                "paste-text-actions",
                ActionButton("Use text", "paste-text-save", variant="primary"),
                ActionButton("Clear", "paste-text-clear"),
                ActionButton("Cancel", "paste-text-cancel"),
            )

    def on_mount(self) -> None:
        self.query_one("#paste-text-input", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "paste-text-save":
            self.dismiss(self.query_one("#paste-text-input", TextArea).text)
        elif button_id == "paste-text-clear":
            self.dismiss("")
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
