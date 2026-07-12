from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Static

from ethernity.app.screens.modal import EthernityModalScreen
from ethernity.app.widgets.actions import ActionButton, modal_action_row


class ConfirmActionScreen(EthernityModalScreen[bool]):
    """Confirmation for a destructive action with no implicit default."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, *, title: str, message: str, confirm_label: str) -> None:
        super().__init__()
        self._confirmation_title = title
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-action-modal"):
            yield Static(self._confirmation_title, id="confirm-action-title", markup=False)
            yield Static(self._message, id="confirm-action-message", markup=False)
            yield modal_action_row(
                "confirm-action-actions",
                ActionButton("Cancel", "confirm-action-cancel", variant="primary"),
                ActionButton(self._confirm_label, "confirm-action-confirm", variant="warning"),
            )

    def on_mount(self) -> None:
        self.query_one("#confirm-action-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-action-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)
