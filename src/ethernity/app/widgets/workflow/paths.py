"""Path-selection and destination editors for guided workflows."""

from __future__ import annotations

from textual.app import RenderResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.events import Resize
from textual.message import Message
from textual.widgets import Button, Label, SelectionList, Static

from ethernity.app.widgets.workflow.controls import (
    InlineNotice,
    child_id,
    merge_classes,
    sync_action,
    sync_static,
)
from ethernity.app.widgets.workflow.styles import GUIDED_WORKFLOW_CSS
from ethernity.tasks.presentation.models import (
    DestinationBodyPresentation,
    PathSelectionBodyPresentation,
    WorkspaceAction,
)

__all__ = ["DestinationEditor", "PathSelectionEditor"]


class PathSelectionEditor(VerticalGroup):
    """Compact selectable path summary with explicit local actions."""

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS

    class SelectionChanged(Message):
        def __init__(self, editor: PathSelectionEditor, selected_keys: tuple[str, ...]) -> None:
            super().__init__()
            self.editor = editor
            self.selected_keys = selected_keys

        @property
        def control(self) -> PathSelectionEditor:
            return self.editor

    class ActionRequested(Message):
        def __init__(self, editor: PathSelectionEditor, action: WorkspaceAction) -> None:
            super().__init__()
            self.editor = editor
            self.action = action

        @property
        def control(self) -> PathSelectionEditor:
            return self.editor

    def __init__(
        self,
        presentation: PathSelectionBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._summary = Static("", classes="guided-summary", markup=False)
        self._paths: SelectionList[str] = SelectionList(
            id=child_id(id, "paths"),
            classes="guided-path-list workspace-control",
            compact=True,
        )
        self._empty = Static("", classes="guided-empty", markup=False)
        self._action_buttons = tuple(
            Button(
                Content.from_text(action.label, markup=False),
                id=action.key,
                compact=True,
                classes="workspace-control",
            )
            for action in presentation.actions
        )
        self._actions = HorizontalGroup(*self._action_buttons, classes="guided-actions")
        self._notice = InlineNotice(presentation.notice)
        super().__init__(
            self._summary,
            self._paths,
            self._empty,
            self._actions,
            self._notice,
            id=id,
            classes=merge_classes("guided-step-body", classes),
        )
        self.sync_presentation(presentation)

    @property
    def selected_keys(self) -> tuple[str, ...]:
        return tuple(self._paths.selected)

    def sync_presentation(self, presentation: PathSelectionBodyPresentation) -> None:
        if tuple(action.key for action in self._presentation.actions) != tuple(
            action.key for action in presentation.actions
        ):
            raise ValueError("path action keys cannot change after composition")
        self._presentation = presentation
        sync_static(self._summary, presentation.count_summary)
        options = tuple(
            (
                Content.from_text(
                    f"{item.label}: {item.display_path}",
                    markup=False,
                ),
                item.key,
                item.selected,
            )
            for item in presentation.items
        )
        with self._paths.prevent(SelectionList.SelectedChanged):
            self._paths.clear_options()
            self._paths.add_options(options)
        self._paths.display = bool(options)
        self._empty.display = not options
        self._empty.update(presentation.empty_label if not options else "")
        for button, action in zip(self._action_buttons, presentation.actions, strict=True):
            sync_action(button, action)
        self._actions.display = any(action.visible for action in presentation.actions)
        self._sync_selection_actions()
        self._notice.sync_presentation(presentation.notice)

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        if event.selection_list is not self._paths:
            return
        event.stop()
        self._sync_selection_actions()
        self.post_message(self.SelectionChanged(self, self.selected_keys))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        try:
            index = self._action_buttons.index(event.button)
        except ValueError:
            return
        event.stop()
        self.post_message(self.ActionRequested(self, self._presentation.actions[index]))

    def _sync_selection_actions(self) -> None:
        has_selection = bool(self.selected_keys)
        for button, action in zip(
            self._action_buttons,
            self._presentation.actions,
            strict=True,
        ):
            button.disabled = not action.enabled or (
                action.requires_selection and not has_selection
            )


class _OneLinePathValue(Static):
    """Render a path on one line while retaining its unabridged presentation value."""

    def __init__(self, *, classes: str) -> None:
        self._path_text = ""
        super().__init__("", classes=classes, markup=False)

    def update_path(self, text: str) -> None:
        self._path_text = text
        self.update(text)

    def render(self) -> RenderResult:
        return Content.from_text(
            _middle_ellipsize(self._path_text, self.content_size.width),
            markup=False,
        )

    def on_resize(self, event: Resize) -> None:
        self.refresh()


def _middle_ellipsize(text: str, max_width: int) -> str:
    if max_width <= 0:
        return ""
    if len(text) <= max_width:
        return text
    if max_width <= 3:
        return "." * max_width

    separator_index = max(text.rfind("/"), text.rfind("\\"))
    if separator_index >= 0:
        separator = text[separator_index]
        name = text[separator_index + 1 :]
        marker = f"...{separator}"
        prefix_width = max_width - len(marker) - len(name)
        if name and prefix_width > 0:
            return f"{text[:prefix_width]}{marker}{name}"

    retained = max_width - 3
    left = retained // 2
    right = retained - left
    return f"{text[:left]}...{text[-right:]}"


class DestinationEditor(VerticalGroup):
    """Destination value, local edit action, and its single owned warning surface."""

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS

    class ActionRequested(Message):
        def __init__(self, editor: DestinationEditor, action: WorkspaceAction) -> None:
            super().__init__()
            self.editor = editor
            self.action = action

        @property
        def control(self) -> DestinationEditor:
            return self.editor

    def __init__(
        self,
        presentation: DestinationBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._label = Label(
            Content.from_text(presentation.label, markup=False),
            classes="guided-field-label",
        )
        self._value = _OneLinePathValue(classes="guided-field-value")
        self._action = Button(
            "",
            id=child_id(id, "action"),
            compact=True,
            classes="workspace-control",
        )
        self._notice = InlineNotice(presentation.notice)
        row = HorizontalGroup(
            self._label,
            self._value,
            self._action,
            classes="guided-field-row",
        )
        super().__init__(
            row,
            self._notice,
            id=id,
            classes=merge_classes("guided-step-body", classes),
        )
        self.sync_presentation(presentation)

    @property
    def display_path(self) -> str:
        return self._presentation.display_path

    def sync_presentation(self, presentation: DestinationBodyPresentation) -> None:
        self._presentation = presentation
        self._label.update(Content.from_text(presentation.label, markup=False))
        self._value.update_path(presentation.display_path or presentation.empty_label)
        self._value.tooltip = presentation.display_path or None
        sync_action(self._action, presentation.action)
        self._notice.sync_presentation(presentation.notice)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is not self._action or self._presentation.action is None:
            return
        event.stop()
        self.post_message(self.ActionRequested(self, self._presentation.action))
