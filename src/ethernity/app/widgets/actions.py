from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.containers import HorizontalGroup
from textual.content import Content
from textual.widget import Widget
from textual.widgets import Button, Static

ButtonVariant = Literal["default", "primary", "success", "warning", "error"]


@dataclass(frozen=True)
class ActionButton:
    label: str
    id: str
    variant: ButtonVariant = "default"
    disabled: bool = False
    classes: str = ""


def modal_action_row(
    row_id: str,
    *actions: ActionButton,
    align_end: bool = True,
    equal_width: bool = False,
) -> HorizontalGroup:
    classes = ["modal-action-row"]
    if equal_width:
        classes.append("equal-actions")

    widgets: list[Widget] = []
    if align_end:
        widgets.append(Static("", classes="modal-action-spacer"))
    for index, action in enumerate(actions):
        if index > 0:
            widgets.append(Static("", classes="modal-action-gap"))
        widgets.append(
            Button(
                Content.from_text(action.label, markup=False),
                id=action.id,
                variant=action.variant,
                disabled=action.disabled,
                compact=True,
                classes=_button_classes(action),
            )
        )
    return HorizontalGroup(*widgets, id=row_id, classes=" ".join(classes))


def inline_action_group(
    *actions: ActionButton,
    group_id: str | None = None,
    classes: str = "",
) -> HorizontalGroup:
    group_classes = "inline-action-group"
    if classes:
        group_classes = f"{group_classes} {classes}"

    widgets: list[Widget] = []
    for index, action in enumerate(actions):
        if index > 0:
            widgets.append(Static("", classes="inline-action-gap"))
        widgets.append(
            Button(
                Content.from_text(action.label, markup=False),
                id=action.id,
                variant=action.variant,
                disabled=action.disabled,
                compact=True,
                classes=_inline_button_classes(action),
            )
        )
    return HorizontalGroup(*widgets, id=group_id, classes=group_classes)


def _button_classes(action: ActionButton) -> str:
    classes = ["modal-action", f"{action.variant}-modal-action"]
    if action.classes:
        classes.append(action.classes)
    return " ".join(classes)


def _inline_button_classes(action: ActionButton) -> str:
    classes = ["inline-action", f"{action.variant}-inline-action"]
    if action.classes:
        classes.append(action.classes)
    return " ".join(classes)
