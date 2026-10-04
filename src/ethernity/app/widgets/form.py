"""Shared form controls and measured popup choices."""

from __future__ import annotations

from typing import TypeVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.visual import Padding, Visual
from textual.widget import Widget
from textual.widgets import Button, Label, Select, Static
from textual.widgets._select import SelectCurrent, SelectOverlay
from textual.widgets.option_list import Option

SelectValue = TypeVar("SelectValue")


class FormSection(VerticalGroup):
    """An open group of related fields with one heading and a section divider."""

    def __init__(self, title: str, *children: Widget, id: str | None = None) -> None:
        super().__init__(Label(title, classes="form-section-title"), *children, id=id)


class FormRow(HorizontalGroup):
    """A shared label column and adjacent controls, stacked in narrow terminals."""

    def __init__(self, label: str | Label, *controls: Widget, id: str | None = None) -> None:
        label_widget = Label(label) if isinstance(label, str) else label
        label_widget.add_class("field-text", "form-label")
        self._controls = HorizontalGroup(*controls, classes="form-controls")
        super().__init__(label_widget, self._controls, id=id)

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 60, "stacked")
        self.call_after_refresh(self._fit_value)

    def _fit_value(self) -> None:
        # Keep short values content-sized, but reserve the adjacent action for long paths.
        action_width = sum(
            child.region.width + child.styles.margin.width
            for child in self._controls.children
            if isinstance(child, Button) and child.display
        )
        available = max(1, self._controls.content_size.width - action_width)
        for child in self._controls.children:
            if isinstance(child, Static) and child.has_class("form-value"):
                child.styles.max_width = available


class FormScroll(VerticalScroll, can_focus=False):
    """Let fields handle editing keys, then use arrows to move between controls."""

    def focus_start(self, control: Widget) -> None:
        """Enter a step with its heading visible, without centering its first control."""
        control.focus(scroll_visible=False)
        self.scroll_home(animate=False, immediate=True)

    BINDINGS = [
        Binding("up", "app.move_up", "Previous control", show=False),
        Binding("down", "app.move_down", "Next control", show=False),
        Binding("left", "app.move_left", "Navigation", show=False),
        Binding("right", "app.move_right", "Workspace", show=False),
    ]


class FormSelectOverlay(SelectOverlay):
    """Include choice padding in native option measurement, painting and hit testing."""

    COMPONENT_CLASSES = {"popup-choice"}

    def _get_visual(self, option: Option) -> Visual:
        # Textual 8 measures the prompt but omits vertical option component padding.
        # Pad the visual instead, preserving the original prompt for type-to-search.
        return Padding(
            super()._get_visual(option), self.get_component_styles("popup-choice").padding
        )


class FormSelect(Select[SelectValue], inherit_bindings=False):
    """Padded native choices; open explicitly and leave the whole field with Tab."""

    BINDINGS = [
        Binding("enter,space", "show_overlay", "Choose", show=False),
        Binding("tab", "leave(1)", "Next control", show=False),
        Binding("shift+tab", "leave(-1)", "Previous control", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield SelectCurrent(self.prompt)
        yield FormSelectOverlay(type_to_search=self._type_to_search).data_bind(
            compact=Select.compact
        )

    def action_leave(self, direction: int) -> None:
        self.expanded = False
        # Anchor traversal on the field, not its temporary option-list child.
        self.screen.set_focus(self, scroll_visible=False)
        if direction > 0:
            self.screen.focus_next()
        else:
            self.screen.focus_previous()
