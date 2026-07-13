"""Quorum and option editors for guided workflows."""

from __future__ import annotations

from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.message import Message
from textual.widgets import Button, Input, Label, RadioSet, Select, Static

from ethernity.app.widgets.workflow.controls import (
    InlineNotice,
    KeyedRadioSet,
    WorkflowIntegerInput,
    child_id,
    merge_classes,
    sync_action,
    sync_static,
)
from ethernity.app.widgets.workflow.styles import GUIDED_WORKFLOW_CSS
from ethernity.tasks.presentation.models import (
    InlineNoticePresentation,
    OptionsBodyPresentation,
    QuorumBodyPresentation,
    SelectFieldPresentation,
    WorkspaceAction,
)

__all__ = ["OptionsEditor", "QuorumEditor"]


class QuorumEditor(VerticalGroup):
    """Threshold and total inputs with a live, plain-language recovery sentence."""

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS

    class Changed(Message):
        def __init__(
            self,
            editor: QuorumEditor,
            threshold: int | None,
            count: int | None,
            *,
            threshold_text: str,
            count_text: str,
            valid: bool,
            error_message: str,
        ) -> None:
            super().__init__()
            self.editor = editor
            self.threshold = threshold
            self.count = count
            self.threshold_text = threshold_text
            self.count_text = count_text
            self.valid = valid
            self.error_message = error_message

        @property
        def control(self) -> QuorumEditor:
            return self.editor

    def __init__(
        self,
        presentation: QuorumBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._draft_dirty = False
        self._threshold_label = Label(
            Content.from_text(presentation.threshold_label, markup=False),
            classes="guided-quorum-label",
        )
        self._threshold = WorkflowIntegerInput(
            "",
            type="integer",
            id=child_id(id, "threshold"),
            compact=True,
            classes="workspace-control",
        )
        self._count_label = Label(
            Content.from_text(presentation.count_label, markup=False),
            classes="guided-quorum-label",
        )
        self._count = WorkflowIntegerInput(
            "",
            type="integer",
            id=child_id(id, "count"),
            compact=True,
            classes="workspace-control",
        )
        self._summary = Static("", classes="guided-summary", markup=False)
        self._notice = InlineNotice(presentation.notice, classes="guided-quorum-notice")
        threshold_field = HorizontalGroup(
            self._threshold_label,
            self._threshold,
            classes="guided-quorum-field",
        )
        count_field = HorizontalGroup(
            self._count_label,
            self._count,
            classes="guided-quorum-field",
        )
        fields = HorizontalGroup(
            threshold_field,
            count_field,
            classes="guided-quorum-fields",
        )
        super().__init__(
            fields,
            self._summary,
            self._notice,
            id=id,
            classes=merge_classes("guided-step-body", classes),
        )
        self.sync_presentation(presentation)

    @property
    def values(self) -> tuple[int | None, int | None]:
        return _optional_int(self._threshold.value), _optional_int(self._count.value)

    def sync_presentation(self, presentation: QuorumBodyPresentation) -> None:
        self._presentation = presentation
        self.display = presentation.visible
        self._threshold_label.update(Content.from_text(presentation.threshold_label, markup=False))
        self._count_label.update(Content.from_text(presentation.count_label, markup=False))
        if not presentation.visible:
            self._draft_dirty = False
        if self.is_attached and not self._draft_dirty:
            self._sync_inputs()
        self._refresh_feedback()

    def on_mount(self) -> None:
        self._sync_inputs()
        self._refresh_feedback()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input not in {self._threshold, self._count}:
            return
        event.stop()
        self._draft_dirty = True
        error = self._refresh_feedback()
        threshold, count = self.values
        self.post_message(
            self.Changed(
                self,
                threshold,
                count,
                threshold_text=self._threshold.value,
                count_text=self._count.value,
                valid=threshold is not None and count is not None and error is None,
                error_message=error.message if error is not None else "",
            )
        )
        if error is not None:
            self.call_after_refresh(self.ensure_feedback_visible)

    def commit_draft(self) -> None:
        self._draft_dirty = False

    def ensure_feedback_visible(self) -> None:
        if self._notice.display:
            self._notice.scroll_visible(animate=False, force=True)

    def _refresh_feedback(self) -> InlineNoticePresentation | None:
        threshold, count = self.values
        error = self._draft_error(threshold, count)
        if threshold is None or count is None:
            self._summary.update("Enter the required and total sheet counts")
        elif error is None:
            self._summary.update(self._presentation.copy.describe(threshold, count))
        else:
            self._summary.update("Choose a valid quorum")
        self._notice.sync_presentation(error or self._presentation.notice)
        return error

    def _draft_error(
        self,
        threshold: int | None,
        count: int | None,
    ) -> InlineNoticePresentation | None:
        if self._draft_dirty and (threshold is None or count is None):
            return InlineNoticePresentation(
                "Enter both required and total sheet counts.",
                tone="error",
            )
        return _quorum_error(self._presentation, threshold, count)

    def _sync_inputs(self) -> None:
        with self._threshold.prevent(Input.Changed), self._count.prevent(Input.Changed):
            self._threshold.value = _input_value(self._presentation.threshold)
            self._count.value = _input_value(self._presentation.count)


class OptionsEditor(VerticalGroup):
    """Compact renderer for values, choices, native Select fields, and local actions."""

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS

    class ChoiceChanged(Message):
        def __init__(self, editor: OptionsEditor, choice_key: str) -> None:
            super().__init__()
            self.editor = editor
            self.choice_key = choice_key

        @property
        def control(self) -> OptionsEditor:
            return self.editor

    class ActionRequested(Message):
        def __init__(self, editor: OptionsEditor, action: WorkspaceAction) -> None:
            super().__init__()
            self.editor = editor
            self.action = action

        @property
        def control(self) -> OptionsEditor:
            return self.editor

    class SelectChanged(Message):
        def __init__(
            self,
            editor: OptionsEditor,
            select_key: str,
            value: str | None,
        ) -> None:
            super().__init__()
            self.editor = editor
            self.select_key = select_key
            self.value = value

        @property
        def control(self) -> OptionsEditor:
            return self.editor

    def __init__(
        self,
        presentation: OptionsBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._values = tuple(
            Static("", classes="guided-detail", markup=False) for _ in presentation.values
        )
        self._choice_set = KeyedRadioSet(
            presentation.choices,
            id=child_id(id, "choices"),
        )
        self._select_labels = tuple(
            Label(
                Content.from_text(select.label, markup=False),
                classes="guided-select-label",
            )
            for select in presentation.selects
        )
        self._select_widgets = tuple(
            Select[str](
                _select_options(select),
                prompt=select.prompt,
                allow_blank=select.allow_blank,
                # Let Textual mount with its neutral value, then synchronize below. Passing the
                # first option here leaves SelectCurrent blank in Textual 8.2.x.
                value=Select.NULL,
                id=select.key,
                disabled=not select.enabled,
                tooltip=(
                    Content.from_text(select.description, markup=False)
                    if select.description
                    else None
                ),
                compact=True,
                classes="workspace-control",
            )
            for select in presentation.selects
        )
        self._select_rows = tuple(
            HorizontalGroup(label, widget, classes="guided-select-row")
            for label, widget in zip(
                self._select_labels,
                self._select_widgets,
                strict=True,
            )
        )
        self._selects = VerticalGroup(*self._select_rows, classes="guided-selects")
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
            *self._values,
            self._choice_set,
            self._selects,
            self._actions,
            self._notice,
            id=id,
            classes=merge_classes("guided-step-body", classes),
        )
        self.sync_presentation(presentation)

    def on_mount(self) -> None:
        self.sync_presentation(self._presentation)

    def sync_presentation(self, presentation: OptionsBodyPresentation) -> None:
        if tuple(value.key for value in self._presentation.values) != tuple(
            value.key for value in presentation.values
        ):
            raise ValueError("option value keys cannot change after composition")
        if tuple(action.key for action in self._presentation.actions) != tuple(
            action.key for action in presentation.actions
        ):
            raise ValueError("option action keys cannot change after composition")
        if tuple(select.key for select in self._presentation.selects) != tuple(
            select.key for select in presentation.selects
        ):
            raise ValueError("option select keys cannot change after composition")
        for previous, current in zip(
            self._presentation.selects,
            presentation.selects,
            strict=True,
        ):
            if previous.allow_blank != current.allow_blank:
                raise ValueError("option select blank policy cannot change after composition")
            if tuple(option.key for option in previous.options) != tuple(
                option.key for option in current.options
            ):
                raise ValueError("option select choice keys cannot change after composition")
        self._presentation = presentation
        for static, value in zip(self._values, presentation.values, strict=True):
            sync_static(static, f"{value.label}: {value.value}" if value.value else "")
        self._choice_set.sync_choices(presentation.choices)
        self._choice_set.display = bool(presentation.choices)
        for label, select_widget, row, select in zip(
            self._select_labels,
            self._select_widgets,
            self._select_rows,
            presentation.selects,
            strict=True,
        ):
            label.update(Content.from_text(select.label, markup=False))
            if select_widget.is_attached:
                with select_widget.prevent(Select.Changed):
                    select_widget.set_options(_select_options(select))
                    select_widget.value = select.value if select.value is not None else Select.NULL
                    # set_options() selects the first option internally. Force the watcher even
                    # when that is also the desired value so SelectCurrent receives its label.
                    select_widget.mutate_reactive(Select.value)
            select_widget.disabled = not select.enabled
            select_widget.tooltip = (
                Content.from_text(select.description, markup=False) if select.description else None
            )
            row.display = select.visible
        self._selects.display = any(select.visible for select in presentation.selects)
        for button, action in zip(self._action_buttons, presentation.actions, strict=True):
            sync_action(button, action)
        self._actions.display = any(action.visible for action in presentation.actions)
        self._notice.sync_presentation(presentation.notice)
        self.display = _options_have_visible_content(presentation)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set is not self._choice_set:
            return
        event.stop()
        choice_key = self._choice_set.key_for_button(event.pressed)
        if choice_key is not None:
            self.post_message(self.ChoiceChanged(self, choice_key))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        try:
            index = self._action_buttons.index(event.button)
        except ValueError:
            return
        event.stop()
        self.post_message(self.ActionRequested(self, self._presentation.actions[index]))

    def on_select_changed(self, event: Select.Changed) -> None:
        try:
            index = self._select_widgets.index(event.select)
        except ValueError:
            return
        event.stop()
        field = self._presentation.selects[index]
        value = None if event.value == Select.NULL else str(event.value)
        if value == field.value:
            return
        self.post_message(self.SelectChanged(self, field.key, value))


def _select_options(
    field: SelectFieldPresentation,
) -> tuple[tuple[Content, str], ...]:
    return tuple(
        (Content.from_text(option.label, markup=False), option.key) for option in field.options
    )


def _options_have_visible_content(presentation: OptionsBodyPresentation) -> bool:
    return bool(
        any(value.value for value in presentation.values)
        or presentation.choices
        or any(select.visible for select in presentation.selects)
        or any(action.visible for action in presentation.actions)
        or (presentation.notice is not None and presentation.notice.message)
    )


def _quorum_error(
    presentation: QuorumBodyPresentation,
    threshold: int | None,
    count: int | None,
) -> InlineNoticePresentation | None:
    values = tuple(value for value in (threshold, count) if value is not None)
    if any(value < presentation.minimum or value > presentation.maximum for value in values):
        return InlineNoticePresentation(
            f"Use values from {presentation.minimum} to {presentation.maximum}.",
            tone="error",
        )
    if threshold is not None and count is not None and threshold > count:
        return InlineNoticePresentation(
            "Required sheets cannot exceed the total sheet count.",
            tone="error",
        )
    return None


def _input_value(value: int | None) -> str:
    return "" if value is None else str(value)


def _optional_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None
