"""Unlock-method editor for guided workflows."""

from __future__ import annotations

from textual.containers import VerticalGroup
from textual.message import Message
from textual.widgets import Button, Input, RadioSet, Static

from ethernity.app.widgets.workflow.controls import (
    InlineNotice,
    KeyedRadioSet,
    WorkspaceActionRequested,
    child_id,
    merge_classes,
    sync_action,
    sync_static,
)
from ethernity.tasks.presentation.models import UnlockBodyPresentation

__all__ = ["UnlockEditor"]


class UnlockEditor(VerticalGroup):
    """Choose an unlock method and show its input controls."""

    class MethodChanged(Message):
        def __init__(self, editor: UnlockEditor, method_key: str) -> None:
            super().__init__()
            self.editor = editor
            self.method_key = method_key

        @property
        def control(self) -> UnlockEditor:
            return self.editor

    class ValueChanged(Message):
        def __init__(self, editor: UnlockEditor, value: str) -> None:
            super().__init__()
            self.editor = editor
            self.value = value

        @property
        def control(self) -> UnlockEditor:
            return self.editor

    def __init__(
        self,
        presentation: UnlockBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._passphrase_dirty = False
        self._pending_value: str | None = None
        self._methods = KeyedRadioSet(
            presentation.methods,
            id=child_id(id, "methods"),
        )
        self._input_summary = Static("", classes="guided-detail", markup=False)
        self._passphrase = Input(
            password=True,
            placeholder="Enter backup passphrase",
            id=child_id(id, "passphrase"),
            classes="workspace-control",
        )
        self._action = Button(
            "",
            id=child_id(id, "action"),
            classes="workspace-control",
        )
        self._notice = InlineNotice(presentation.notice)
        super().__init__(
            self._methods,
            self._passphrase,
            self._input_summary,
            self._action,
            self._notice,
            id=id,
            classes=merge_classes("guided-step-body", classes),
        )
        self.sync_presentation(presentation)

    @property
    def selected_method(self) -> str | None:
        return self._methods.selected_key

    def sync_presentation(self, presentation: UnlockBodyPresentation) -> None:
        self._presentation = presentation
        self._methods.sync_choices(presentation.methods)
        sync_static(self._input_summary, presentation.input_summary)
        self._passphrase.display = self.selected_method == "passphrase"
        self._passphrase.placeholder = (
            "Passphrase set; enter to replace"
            if presentation.passphrase_set
            else "Enter backup passphrase"
        )
        sync_action(self._action, presentation.method_action)
        self._notice.sync_presentation(presentation.notice)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set is not self._methods:
            return
        event.stop()
        method_key = self._methods.key_for_button(event.pressed)
        if method_key is not None:
            self._passphrase.display = method_key == "passphrase"
            self.post_message(self.MethodChanged(self, method_key))

    def focus_passphrase(self) -> None:
        if self._passphrase.display:
            self._passphrase.focus(scroll_visible=True)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is self._passphrase:
            event.stop()
            self._passphrase_dirty = True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._commit_passphrase(event)

    def on_input_blurred(self, event: Input.Blurred) -> None:
        self._commit_passphrase(event)

    def _commit_passphrase(self, event: Input.Submitted | Input.Blurred) -> None:
        if event.input is not self._passphrase:
            return
        event.stop()
        if not self._passphrase_dirty:
            return
        self._passphrase_dirty = False
        self._pending_value = event.value
        self.post_message(self.ValueChanged(self, event.value))
        with self._passphrase.prevent(Input.Changed):
            self._passphrase.value = ""

    def take_pending_change(self) -> ValueChanged | None:
        """Return an uncommitted phrase without exposing it in presentation text."""
        if self._pending_value is not None:
            value = self._pending_value
            self._pending_value = None
            return self.ValueChanged(self, value)
        if not self._passphrase_dirty and not self._passphrase.value:
            return None
        self._passphrase_dirty = False
        value = self._passphrase.value
        with self._passphrase.prevent(Input.Changed):
            self._passphrase.value = ""
        return self.ValueChanged(self, value)

    def accept_value(self, value: str) -> None:
        if self._pending_value == value:
            self._pending_value = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is not self._action or self._presentation.method_action is None:
            return
        event.stop()
        self.post_message(WorkspaceActionRequested(self, self._presentation.method_action))
