"""Path-selection and destination editors for guided workflows."""

from __future__ import annotations

from textual.containers import VerticalGroup
from textual.content import Content
from textual.message import Message
from textual.widgets import Button, Input, Label, SelectionList, Static

from ethernity.app.widgets.form import FormRow
from ethernity.app.widgets.workflow.controls import (
    ActionEditor,
    EditorValueChanged,
    InlineNotice,
    child_id,
    merge_classes,
    post_workspace_action,
    sync_action,
    sync_static,
    workspace_action_button,
)
from ethernity.tasks.presentation.models import (
    DestinationBodyPresentation,
    PathSelectionBodyPresentation,
)

__all__ = ["DestinationEditor", "PathSelectionEditor"]


class PathSelectionEditor(ActionEditor[PathSelectionBodyPresentation]):
    """Compact selectable path summary with explicit local actions."""

    class SelectionChanged(Message):
        def __init__(self, editor: PathSelectionEditor, selected_keys: tuple[str, ...]) -> None:
            super().__init__()
            self.editor = editor
            self.selected_keys = selected_keys

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
        self._summary = Static("", classes="guided-summary", markup=False)
        self._paths: SelectionList[str] = SelectionList(
            id=child_id(id, "paths"),
            classes="guided-path-list workspace-control",
            compact=True,
        )
        self._empty = Static("", classes="guided-empty", markup=False)
        super().__init__(
            presentation,
            self._summary,
            self._paths,
            self._empty,
            id=id,
            classes=classes,
        )

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


class DestinationEditor(VerticalGroup):
    """Editable destination path with optional browsing and one warning region."""

    class ValueChanged(EditorValueChanged["DestinationEditor"]):
        pass

    def __init__(
        self,
        presentation: DestinationBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._dirty = False
        self._label = Label(
            Content.from_text(presentation.label, markup=False),
            classes="field-text form-label",
        )
        self._value = Input(
            placeholder=presentation.empty_label,
            id=child_id(id, "value"),
            classes="workspace-control",
        )
        self._action = workspace_action_button(id)
        self._notice = InlineNotice(presentation.notice)
        row = FormRow(self._label, self._value, self._action)
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

    def on_mount(self) -> None:
        self.sync_presentation(self._presentation)

    def sync_presentation(self, presentation: DestinationBodyPresentation) -> None:
        self._presentation = presentation
        self._label.update(Content.from_text(presentation.label, markup=False))
        if (
            not self._dirty
            and self._value.is_attached
            and self._value.value != presentation.display_path
        ):
            with self._value.prevent(Input.Changed):
                self._value.value = presentation.display_path
                self._value.cursor_position = len(presentation.display_path)
        self._value.placeholder = presentation.empty_label
        self._value.tooltip = presentation.display_path or None
        sync_action(self._action, presentation.action)
        self._notice.sync_presentation(presentation.notice)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is self._value:
            event.stop()
            self._dirty = event.value != self._presentation.display_path

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._commit_value(event)

    def on_input_blurred(self, event: Input.Blurred) -> None:
        self._commit_value(event)

    def _commit_value(self, event: Input.Submitted | Input.Blurred) -> None:
        if event.input is not self._value:
            return
        event.stop()
        change = self.take_pending_change()
        if change is not None:
            self.post_message(change)

    def take_pending_change(self) -> ValueChanged | None:
        """Commit the current draft before review, including keyboard submission."""
        if not self._dirty and self._value.value == self._presentation.display_path:
            return None
        self._dirty = False
        return self.ValueChanged(self, self._value.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is not self._action or self._presentation.action is None:
            return
        post_workspace_action(
            self,
            event,
            (self._action,),
            (self._presentation.action,),
        )
