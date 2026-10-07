"""Guided-workflow controls and presentation synchronization."""

from __future__ import annotations

from typing import Generic, TypeVar

from textual.binding import Binding
from textual.containers import VerticalGroup
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

from ethernity.app.widgets.actions import ResponsiveActions
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    InlineNoticePresentation,
    WorkspaceAction,
)

__all__ = [
    "ActionEditor",
    "EditorValueChanged",
    "WorkspaceActionGroup",
    "workspace_action_button",
    "InlineNotice",
    "KeyedRadioSet",
    "WorkspaceActionRequested",
    "WorkflowIntegerInput",
    "child_id",
    "merge_classes",
    "post_workspace_action",
    "sync_action",
    "sync_static",
]


class WorkspaceActionRequested(Message):
    """One action event shared by every guided-workflow editor."""

    def __init__(self, control: Widget, action: WorkspaceAction) -> None:
        super().__init__()
        self._control = control
        self.action = action

    @property
    def control(self) -> Widget:
        return self._control


def post_workspace_action(
    control: Widget,
    event: Button.Pressed,
    buttons: tuple[Button, ...],
    actions: tuple[WorkspaceAction, ...],
) -> None:
    """Post the action paired with a button from a stable presentation tuple."""

    try:
        index = buttons.index(event.button)
    except ValueError:
        return
    event.stop()
    control.post_message(WorkspaceActionRequested(control, actions[index]))


class InlineNotice(Static):
    """A literal, non-color-only status message with one presentation owner."""

    _TONES = ("info", "warning", "error", "success")

    def __init__(
        self,
        notice: InlineNoticePresentation | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__("", id=id, classes=classes, markup=False)
        self.sync_presentation(notice)

    def sync_presentation(self, notice: InlineNoticePresentation | None) -> None:
        for tone in self._TONES:
            self.remove_class(f"notice-{tone}")
        if notice is None or not notice.message:
            self.display = False
            self.update("")
            return
        self.display = True
        self.add_class(f"notice-{notice.tone}")
        label = {
            "info": "Note",
            "warning": "Warning",
            "error": "Error",
            "success": "Success",
        }[notice.tone]
        self.update(f"{label}: {notice.message}")


class WorkflowIntegerInput(Input):
    """Numeric guided input that keeps the app's j/k control traversal."""

    BINDINGS = [
        Binding("j", "app.move_down", "Next control", show=False, priority=True),
        Binding("k", "app.move_up", "Previous control", show=False, priority=True),
    ]


class KeyedRadioSet(RadioSet):
    """Native RadioSet adapter that retains option keys and supports no selection."""

    def __init__(
        self,
        choices: tuple[ChoicePresentation, ...],
        *,
        id: str | None,
        classes: str = "guided-choice-set workspace-control",
        button_id_prefix: str | None = None,
        empty_classes: str = "guided-choice-empty",
        routes_to_app: bool = False,
    ) -> None:
        self.routes_to_app = routes_to_app
        self._empty_button = RadioButton(
            "",
            value=not any(choice.selected for choice in choices),
            disabled=True,
            classes=empty_classes,
        )
        self._buttons = {
            choice.key: RadioButton(
                Content.from_text(choice.label, markup=False),
                id=(f"{button_id_prefix}-{choice.key}" if button_id_prefix is not None else None),
                value=choice.selected,
                disabled=not choice.enabled,
                tooltip=choice.description or None,
            )
            for choice in choices
        }
        super().__init__(
            self._empty_button,
            *self._buttons.values(),
            id=id,
            classes=classes,
            compact=True,
        )

    @property
    def selected_key(self) -> str | None:
        return next((key for key, button in self._buttons.items() if button.value), None)

    def key_for_button(self, button: RadioButton) -> str | None:
        return next((key for key, candidate in self._buttons.items() if candidate is button), None)

    def clear_selection(self) -> None:
        with self.prevent(RadioSet.Changed):
            self._empty_button.value = True

    def sync_choices(self, choices: tuple[ChoicePresentation, ...]) -> None:
        if tuple(self._buttons) != tuple(choice.key for choice in choices):
            raise ValueError("radio choice keys cannot change after composition")

        selected = next((choice.key for choice in choices if choice.selected), None)
        for choice in choices:
            button = self._buttons[choice.key]
            button.label = Content.from_text(choice.label, markup=False)
            button.disabled = not choice.enabled
            button.tooltip = choice.description or None

        target = self._empty_button if selected is None else self._buttons[selected]
        with self.prevent(RadioSet.Changed):
            target.value = True


def sync_static(widget: Static, value: str) -> None:
    widget.display = bool(value)
    widget.update(value)


def sync_action(button: Button, action: WorkspaceAction | None) -> None:
    button.display = action is not None and action.visible
    if action is None:
        button.label = Content.from_text("", markup=False)
        button.disabled = True
    else:
        button.label = Content.from_text(action.label, markup=False)
        button.disabled = not action.enabled
    if isinstance(button.parent, ResponsiveActions):
        button.parent.reflow()


def child_id(owner_id: str | None, suffix: str) -> str | None:
    return f"{owner_id}-{suffix}" if owner_id is not None else None


def merge_classes(required: str, optional: str | None) -> str:
    return required if not optional else f"{required} {optional}"


_Editor = TypeVar("_Editor", bound=Widget)


class EditorValueChanged(Message, Generic[_Editor]):
    def __init__(self, editor: _Editor, value: str) -> None:
        super().__init__()
        self.editor = editor
        self.value = value

    @property
    def control(self) -> _Editor:
        return self.editor


class WorkspaceActionGroup(ResponsiveActions):
    """Buttons created from one stable sequence of local workspace actions."""

    def __init__(self, actions: tuple[WorkspaceAction, ...]) -> None:
        self.buttons = tuple(
            Button(
                Content.from_text(action.label, markup=False),
                id=action.key,
                classes="workspace-control",
            )
            for action in actions
        )
        super().__init__(*self.buttons, classes="guided-actions")


class ActionEditor(VerticalGroup):
    _actions: WorkspaceActionGroup

    @property
    def _action_buttons(self) -> tuple[Button, ...]:
        return self._actions.buttons

    def action_presentations(self) -> tuple[WorkspaceAction, ...]:
        raise NotImplementedError

    def on_button_pressed(self, event: Button.Pressed) -> None:
        post_workspace_action(self, event, self._action_buttons, self.action_presentations())


def workspace_action_button(owner_id: str | None) -> Button:
    return Button("", id=child_id(owner_id, "action"), classes="workspace-control")
