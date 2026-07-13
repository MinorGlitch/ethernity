"""Shared controls and presentation-sync helpers for guided workflows."""

from __future__ import annotations

from textual.binding import Binding
from textual.content import Content
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

from ethernity.app.widgets.workflow.styles import GUIDED_WORKFLOW_CSS
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    InlineNoticePresentation,
    WorkspaceAction,
)

__all__ = [
    "InlineNotice",
    "KeyedRadioSet",
    "WorkflowIntegerInput",
    "child_id",
    "merge_classes",
    "sync_action",
    "sync_static",
]


class InlineNotice(Static):
    """A literal, non-color-only status message with one presentation owner."""

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS
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
    """Native RadioSet adapter that retains semantic keys and supports no selection."""

    def __init__(
        self,
        choices: tuple[ChoicePresentation, ...],
        *,
        id: str | None,
    ) -> None:
        self._empty_button = RadioButton(
            "",
            value=not any(choice.selected for choice in choices),
            disabled=True,
            classes="guided-choice-empty",
        )
        self._buttons = {
            choice.key: RadioButton(
                Content.from_text(choice.label, markup=False),
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
            classes="guided-choice-set workspace-control",
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
        return
    button.label = Content.from_text(action.label, markup=False)
    button.disabled = not action.enabled


def child_id(owner_id: str | None, suffix: str) -> str | None:
    return f"{owner_id}-{suffix}" if owner_id is not None else None


def merge_classes(required: str, optional: str | None) -> str:
    return required if not optional else f"{required} {optional}"
