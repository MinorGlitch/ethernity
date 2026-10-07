"""Shared state and cancellation for single- and multiline text-entry modals."""

from __future__ import annotations

from ethernity.app.screens.modal import EthernityModalScreen


class TextEntryScreen(EthernityModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, *, title: str, prompt: str, value: str = "", placeholder: str = "") -> None:
        super().__init__()
        self._field_title = title
        self._prompt = prompt
        self._value = value
        self._placeholder = placeholder

    def action_cancel(self) -> None:
        self.dismiss(None)
