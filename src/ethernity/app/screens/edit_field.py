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

from collections.abc import Callable

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
        validator: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__()
        self._field_title = title
        self._prompt = prompt
        self._value = value
        self._placeholder = placeholder
        self._password = password
        self._mask_template = mask_template
        self._validator = validator

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-field-modal", classes="dialog dialog-small"):
            yield Static(self._field_title, id="edit-field-title", classes="screen-title")
            yield Label(self._prompt, id="edit-field-prompt", classes="dialog-prompt")
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
            yield Static("", id="edit-field-error", markup=False)
            yield modal_action_row(
                "edit-field-actions",
                ActionButton("Apply", "edit-field-save", variant="primary"),
                ActionButton("Clear", "edit-field-clear"),
                ActionButton("Cancel", "edit-field-cancel"),
            )

    def on_mount(self) -> None:
        field = self.query_one("#edit-field-input", Input)
        field.focus()
        self._refresh_input_state(field)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "edit-field-input":
            self._refresh_input_state(event.input)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "edit-field-input":
            event.stop()
            self.action_apply()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        event.stop()
        if button_id == "edit-field-save":
            self.action_apply()
        elif button_id == "edit-field-clear":
            self.dismiss("")
        elif button_id == "edit-field-cancel":
            self.dismiss(None)

    def action_apply(self) -> None:
        field = self.query_one("#edit-field-input", Input)
        if self._refresh_input_state(field):
            self.dismiss(self._normalized_input_value(field))
        else:
            field.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _refresh_input_state(self, field: Input) -> bool:
        value = self._normalized_input_value(field)
        message = None
        if isinstance(field, MaskedInput) and value:
            result = field.validate(field.value)
            if result is not None and not result.is_valid:
                message = "Complete the value or clear it."
        if message is None and self._validator is not None:
            message = self._validator(value)
        valid = message is None
        error = self.query_one("#edit-field-error", Static)
        error.update(message or "")
        error.display = not valid
        self.query_one("#edit-field-save", Button).disabled = not valid
        return valid

    def _normalized_input_value(self, field: Input) -> str:
        value = field.value
        if isinstance(field, MaskedInput):
            return value.replace(" ", "")
        return value
