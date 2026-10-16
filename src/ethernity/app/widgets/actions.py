from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual import events
from textual.containers import Grid, HorizontalGroup
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

    def build(self) -> Button:
        return Button(
            Content.from_text(self.label, markup=False),
            id=self.id,
            variant=self.variant,
            disabled=self.disabled,
            classes=self.classes,
        )


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
            widgets.append(Static("", classes="action-gap"))
        widgets.append(action.build())
    return HorizontalGroup(*widgets, id=row_id, classes=" ".join(classes))


def button_min_width(button: Button) -> int:
    """Readable button width in terminal cells, including its horizontal inset."""
    return max(10, Content.from_text(str(button.label), markup=False).cell_length + 4)


class ResponsiveActions(Grid):
    """Fit complete button labels, preserving source-action hierarchy when wrapping."""

    def __init__(self, *buttons: Button, id: str | None = None, classes: str = "") -> None:
        super().__init__(*buttons, id=id, classes=f"responsive-actions {classes}")

    def on_mount(self) -> None:
        self.reflow()

    def on_resize(self, event: events.Resize) -> None:
        self.reflow()

    def reflow(self) -> None:
        buttons = [child for child in self.children if isinstance(child, Button) and child.display]
        if not buttons:
            return
        minimum = max(button_min_width(button) for button in buttons)
        width = self.content_size.width
        capacity = max(1, min(len(buttons), (width + 1) // (minimum + 1)))
        rows = (len(buttons) + capacity - 1) // capacity
        columns = (len(buttons) + rows - 1) // rows
        self.styles.grid_size_columns = columns
        for button in buttons:
            button.styles.column_span = 1
            button.styles.max_width = max(34, minimum) if len(buttons) == 1 else None
        if len(buttons) == 3 and columns == 2 and buttons[0].variant == "primary":
            buttons[0].styles.column_span = 2


def inline_action_group(
    *actions: ActionButton,
    group_id: str | None = None,
    classes: str = "",
) -> ResponsiveActions:
    return ResponsiveActions(
        *(action.build() for action in actions),
        id=group_id,
        classes=f"inline-action-group {classes}",
    )


def action_grid(*actions: ActionButton, id: str) -> ResponsiveActions:
    return ResponsiveActions(*(action.build() for action in actions), id=id)
