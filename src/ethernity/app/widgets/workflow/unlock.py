"""Unlock-method editor for guided workflows."""

from __future__ import annotations

from textual.containers import VerticalGroup
from textual.message import Message
from textual.widgets import Button, RadioSet, Static

from ethernity.app.widgets.workflow.controls import (
    InlineNotice,
    KeyedRadioSet,
    child_id,
    merge_classes,
    sync_action,
    sync_static,
)
from ethernity.app.widgets.workflow.styles import GUIDED_WORKFLOW_CSS
from ethernity.tasks.presentation.models import UnlockBodyPresentation, WorkspaceAction

__all__ = ["UnlockEditor"]


class UnlockEditor(VerticalGroup):
    """Choose one unlock method and reveal only its contextual local action."""

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS

    class MethodChanged(Message):
        def __init__(self, editor: UnlockEditor, method_key: str) -> None:
            super().__init__()
            self.editor = editor
            self.method_key = method_key

        @property
        def control(self) -> UnlockEditor:
            return self.editor

    class ActionRequested(Message):
        def __init__(self, editor: UnlockEditor, action: WorkspaceAction) -> None:
            super().__init__()
            self.editor = editor
            self.action = action

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
        self._methods = KeyedRadioSet(
            presentation.methods,
            id=child_id(id, "methods"),
        )
        self._material = Static("", classes="guided-detail", markup=False)
        self._action = Button(
            "",
            id=child_id(id, "action"),
            compact=True,
            classes="workspace-control",
        )
        self._notice = InlineNotice(presentation.notice)
        super().__init__(
            self._methods,
            self._material,
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
        sync_static(self._material, presentation.material_summary)
        sync_action(self._action, presentation.contextual_action)
        self._notice.sync_presentation(presentation.notice)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set is not self._methods:
            return
        event.stop()
        method_key = self._methods.key_for_button(event.pressed)
        if method_key is not None:
            self.post_message(self.MethodChanged(self, method_key))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is not self._action or self._presentation.contextual_action is None:
            return
        event.stop()
        self.post_message(self.ActionRequested(self, self._presentation.contextual_action))
