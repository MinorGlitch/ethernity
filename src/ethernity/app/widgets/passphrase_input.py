"""A masked entry that retains unhandled edits without displaying a stored secret."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Input


class PassphraseInput(Input):
    class Committed(Message):
        def __init__(self, input: PassphraseInput) -> None:
            super().__init__()
            self.input = input

    def __init__(self, *, id: str | None = None, placeholder: str = "Enter passphrase") -> None:
        super().__init__(password=True, id=id, placeholder=placeholder, classes="workspace-control")
        self._dirty = False
        self._pending_value: str | None = None

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is self:
            event.stop()
            if event.value == self.value:
                self._dirty = True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._commit(event)

    def on_input_blurred(self, event: Input.Blurred) -> None:
        self._commit(event)

    def _commit(self, event: Input.Submitted | Input.Blurred) -> None:
        if event.input is not self:
            return
        event.stop()
        if not self._dirty and not self.value:
            return
        self._dirty = False
        self._pending_value = self.value
        self.post_message(self.Committed(self))
        self._clear_display()

    def take_pending_value(self) -> str | None:
        """Drain the current edit before a keyboard shortcut captures task state."""
        if self._dirty or self.value:
            value = self.value
            self._dirty = False
            self._pending_value = None
            self._clear_display()
            return value
        value = self._pending_value
        self._pending_value = None
        return value

    def discard_edit(self) -> None:
        """Forget uncommitted input when its task is explicitly reset."""
        self._dirty = False
        self._pending_value = None
        self._clear_display()

    def _clear_display(self) -> None:
        with self.prevent(Input.Changed):
            self.value = ""
