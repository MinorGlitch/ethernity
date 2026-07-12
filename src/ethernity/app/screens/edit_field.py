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
from textual.widgets import Button, Input, Label, MaskedInput, Static

from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, modal_action_row


class EditFieldScreen(EthernityModalScreen[str | None]):
    """Small modal for editing one task field."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        *,
        title: str,
        prompt: str,
        value: str = "",
        placeholder: str = "",
        password: bool = False,
        mask_template: str | None = None,
    ) -> None:
        super().__init__()
        self._field_title = title
        self._prompt = prompt
        self._value = value
        self._placeholder = placeholder
        self._password = password
        self._mask_template = mask_template

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-field-modal"):
            yield Static(self._field_title, id="edit-field-title")
            yield Label(self._prompt, id="edit-field-prompt")
            if self._mask_template is None:
                yield Input(
                    self._value,
                    placeholder=self._placeholder,
                    password=self._password,
                    id="edit-field-input",
                )
            else:
                yield MaskedInput(
                    self._mask_template,
                    value=self._value,
                    placeholder=self._placeholder,
                    valid_empty=True,
                    id="edit-field-input",
                )
            yield modal_action_row(
                "edit-field-actions",
                ActionButton("Apply", "edit-field-save", variant="primary"),
                ActionButton("Clear", "edit-field-clear"),
                ActionButton("Cancel", "edit-field-cancel"),
            )

    def on_mount(self) -> None:
        self.query_one("#edit-field-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(self._normalized_input_value(event.input))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "edit-field-save":
            self.dismiss(self._normalized_input_value(self.query_one("#edit-field-input", Input)))
        elif button_id == "edit-field-clear":
            self.dismiss("")
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _normalized_input_value(self, field: Input) -> str:
        value = field.value
        if isinstance(field, MaskedInput):
            return value.replace(" ", "")
        return value
