from __future__ import annotations

from textual.app import RenderResult
from textual.binding import Binding
from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.events import Click, Resize
from textual.message import Message
from textual.widget import Widget
from textual.widgets import (
    Button,
    Input,
    Label,
    LoadingIndicator,
    RadioButton,
    RadioSet,
    Select,
    SelectionList,
    Static,
)

from ethernity.tasks.presentation.models import (
    AtomicStepBodyPresentation,
    ChoicePresentation,
    CompositeBodyPresentation,
    DestinationBodyPresentation,
    InlineNoticePresentation,
    OptionsBodyPresentation,
    PathSelectionBodyPresentation,
    QuorumBodyPresentation,
    SelectFieldPresentation,
    SourceBodyPresentation,
    StepBodyPresentation,
    StepPresentation,
    UnlockBodyPresentation,
    WorkflowPresentation,
    WorkspaceAction,
)

_GUIDED_WORKFLOW_CSS = """
WorkflowStepStack {
    height: auto;
    width: 1fr;
}

WorkflowStep {
    height: auto;
    width: 1fr;
}

WorkflowStepHeader {
    height: 2;
    min-height: 2;
    width: 1fr;
    padding: 0 1;
    color: $text-muted;
}

WorkflowStepHeader.step-compact {
    height: 1;
    min-height: 1;
}

WorkflowStepHeader.step-compact .workflow-step-copy {
    height: 1;
}

.workflow-step-marker {
    width: 4;
    height: 1;
}

.workflow-step-number {
    width: 3;
    height: 1;
}

.workflow-step-copy {
    width: 1fr;
    height: 2;
}

.workflow-step-title,
.workflow-step-summary {
    width: 1fr;
    height: 1;
    text-wrap: nowrap;
    text-overflow: ellipsis;
}

.workflow-step-title {
    color: $text;
}

.workflow-step-status {
    width: auto;
    max-width: 19;
    height: 1;
    margin-left: 1;
    content-align: right middle;
    text-wrap: nowrap;
    text-overflow: ellipsis;
}

WorkflowStepHeader:focus {
    background: $surface-active;
    color: $text;
    text-style: bold;
}

WorkflowStepHeader.step-current {
    color: $text;
    text-style: bold;
}

WorkflowStepHeader.step-warning {
    color: $text-warning;
}

WorkflowStepHeader.step-error {
    color: $text-error;
}

.guided-step-body {
    height: auto;
    width: 1fr;
    padding: 1 2 1 4;
    background: $surface;
}

.guided-choice-set {
    height: auto;
    width: 1fr;
}

.guided-choice-empty {
    display: none;
}

.guided-actions,
.guided-field-row,
.guided-loading,
.guided-quorum-fields,
.guided-select-row,
.guided-selects {
    height: auto;
    width: 1fr;
}

.guided-loading LoadingIndicator {
    width: 4;
    height: 1;
    color: $text-primary;
}

.guided-loading-label {
    width: 1fr;
    height: 1;
    color: $text-muted;
}

.guided-actions Button {
    margin-right: 1;
}

.guided-summary,
.guided-empty,
.guided-detail {
    height: auto;
    width: 1fr;
    color: $text-muted;
}

.guided-field-value {
    height: 1;
    min-height: 1;
    width: 1fr;
    color: $text-muted;
    text-wrap: nowrap;
    text-overflow: ellipsis;
}

.guided-field-label {
    width: 16;
    margin-right: 1;
    color: $text;
}

.guided-select-label {
    width: 16;
    color: $text;
    content-align: left middle;
}

.guided-select-row Select {
    width: 1fr;
    max-width: 48;
}

CompositeStepBody {
    height: auto;
    width: 1fr;
}

CompositeStepBody > .guided-step-body {
    margin: 0 0 1 0;
    padding: 0;
    background: transparent;
}

.guided-path-list {
    height: auto;
    max-height: 6;
    width: 1fr;
}

InlineNotice {
    height: auto;
    width: 1fr;
    margin-top: 1;
    padding: 0 1;
}

InlineNotice.notice-info {
    color: $text-muted;
}

InlineNotice.notice-warning {
    color: $text-warning;
}

InlineNotice.notice-error {
    color: $text-error;
}

InlineNotice.notice-success {
    color: $text-success;
}

.guided-quorum-notice {
    margin-bottom: 1;
}

QuorumEditor Input {
    width: 10;
    margin-right: 2;
}

.guided-quorum-label {
    width: 12;
    content-align: left middle;
}

.guided-quorum-field {
    height: auto;
    width: 1fr;
}

Screen.-ethernity-narrow .guided-select-row {
    layout: vertical;
}

Screen.-ethernity-narrow .guided-select-label,
Screen.-ethernity-narrow .guided-select-row Select {
    width: 1fr;
    max-width: 100%;
}

Screen.-ethernity-narrow CompositeStepBody > .guided-step-body {
    padding: 0;
}
"""


class InlineNotice(Static):
    """A literal, non-color-only status message with one presentation owner."""

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS
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


class _WorkflowIntegerInput(Input):
    """Numeric guided input that keeps the app's j/k control traversal."""

    BINDINGS = [
        Binding("j", "app.move_down", "Next control", show=False, priority=True),
        Binding("k", "app.move_up", "Previous control", show=False, priority=True),
    ]


class _KeyedRadioSet(RadioSet):
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


class SourceChooser(VerticalGroup):
    """Select a source method and show typed source assessment facts."""

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS

    class MethodChanged(Message):
        def __init__(self, chooser: SourceChooser, method_key: str) -> None:
            super().__init__()
            self.chooser = chooser
            self.method_key = method_key

        @property
        def control(self) -> SourceChooser:
            return self.chooser

    class ActionRequested(Message):
        def __init__(self, chooser: SourceChooser, action: WorkspaceAction) -> None:
            super().__init__()
            self.chooser = chooser
            self.action = action

        @property
        def control(self) -> SourceChooser:
            return self.chooser

    def __init__(
        self,
        presentation: SourceBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._choosing_method = False
        self._methods = _KeyedRadioSet(
            presentation.methods,
            id=_child_id(id, "methods"),
        )
        self._loading = LoadingIndicator(id=_child_id(id, "loading"))
        self._loading_status = HorizontalGroup(
            self._loading,
            Static("Inspecting backup source...", classes="guided-loading-label", markup=False),
            classes="guided-loading",
        )
        self._source_type = Static("", classes="guided-detail", markup=False)
        self._material = Static("", classes="guided-detail", markup=False)
        self._identity = Static("", classes="guided-detail", markup=False)
        self._version = Static("", classes="guided-detail", markup=False)
        self._assessment = VerticalGroup(
            self._source_type,
            self._material,
            self._identity,
            self._version,
            classes="guided-summary",
        )
        self._change = Button(
            "",
            id=_child_id(id, "change"),
            compact=True,
            classes="workspace-control",
        )
        self._notice = InlineNotice(presentation.notice)
        super().__init__(
            self._methods,
            self._loading_status,
            self._assessment,
            self._change,
            self._notice,
            id=id,
            classes=_classes("guided-step-body", classes),
        )
        self.sync_presentation(presentation)

    @property
    def selected_method(self) -> str | None:
        return self._methods.selected_key

    def sync_presentation(self, presentation: SourceBodyPresentation) -> None:
        if presentation.loading or presentation.assessment != self._presentation.assessment:
            self._choosing_method = False
        self._presentation = presentation
        self._methods.sync_choices(presentation.methods)
        if self._choosing_method:
            self._methods.clear_selection()
        self._loading_status.display = presentation.loading
        assessment = presentation.assessment
        _sync_static(
            self._source_type,
            f"Source: {assessment.source_label}" if assessment else "",
        )
        _sync_static(
            self._material,
            f"Material: {assessment.material_summary}" if assessment else "",
        )
        _sync_static(
            self._identity,
            f"Backup: {assessment.backup_identity}"
            if assessment and assessment.backup_identity
            else "",
        )
        _sync_static(
            self._version,
            f"Version: {assessment.version_summary}"
            if assessment and assessment.version_summary
            else "",
        )
        _sync_action(self._change, presentation.change_action)
        self._notice.sync_presentation(presentation.notice)
        self._sync_mode()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set is not self._methods:
            return
        event.stop()
        method_key = self._methods.key_for_button(event.pressed)
        if method_key is not None:
            self._choosing_method = False
            self._sync_mode()
            self.post_message(self.MethodChanged(self, method_key))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is not self._change or self._presentation.change_action is None:
            return
        event.stop()
        if self._presentation.assessment is None:
            self.post_message(self.ActionRequested(self, self._presentation.change_action))
            return
        self._choosing_method = True
        self._methods.clear_selection()
        self._sync_mode()
        self._methods.focus()

    def _sync_mode(self) -> None:
        loading = self._presentation.loading
        assessed = self._presentation.assessment is not None
        choosing = assessed and self._choosing_method and not loading
        self._methods.display = (not assessed and not loading) or choosing
        self._assessment.display = assessed and not loading and not choosing
        action = self._presentation.change_action
        self._change.display = action is not None and action.visible and not choosing
        notice = self._presentation.notice
        self._notice.display = notice is not None and bool(notice.message) and not choosing


class UnlockEditor(VerticalGroup):
    """Choose one unlock method and reveal only its contextual local action."""

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS

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
        self._methods = _KeyedRadioSet(
            presentation.methods,
            id=_child_id(id, "methods"),
        )
        self._material = Static("", classes="guided-detail", markup=False)
        self._action = Button(
            "",
            id=_child_id(id, "action"),
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
            classes=_classes("guided-step-body", classes),
        )
        self.sync_presentation(presentation)

    @property
    def selected_method(self) -> str | None:
        return self._methods.selected_key

    def sync_presentation(self, presentation: UnlockBodyPresentation) -> None:
        self._presentation = presentation
        self._methods.sync_choices(presentation.methods)
        _sync_static(self._material, presentation.material_summary)
        _sync_action(self._action, presentation.contextual_action)
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


class PathSelectionEditor(VerticalGroup):
    """Compact selectable path summary with explicit local actions."""

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS

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
            id=_child_id(id, "paths"),
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
            classes=_classes("guided-step-body", classes),
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
        _sync_static(self._summary, presentation.count_summary)
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
            _sync_action(button, action)
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

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS

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
            id=_child_id(id, "action"),
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
            classes=_classes("guided-step-body", classes),
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
        _sync_action(self._action, presentation.action)
        self._notice.sync_presentation(presentation.notice)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is not self._action or self._presentation.action is None:
            return
        event.stop()
        self.post_message(self.ActionRequested(self, self._presentation.action))


class QuorumEditor(VerticalGroup):
    """Threshold and total inputs with a live, plain-language recovery sentence."""

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS

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
        self._threshold = _WorkflowIntegerInput(
            "",
            type="integer",
            id=_child_id(id, "threshold"),
            compact=True,
            classes="workspace-control",
        )
        self._count_label = Label(
            Content.from_text(presentation.count_label, markup=False),
            classes="guided-quorum-label",
        )
        self._count = _WorkflowIntegerInput(
            "",
            type="integer",
            id=_child_id(id, "count"),
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
            classes=_classes("guided-step-body", classes),
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

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS

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
        self._choice_set = _KeyedRadioSet(
            presentation.choices,
            id=_child_id(id, "choices"),
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
            classes=_classes("guided-step-body", classes),
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
            _sync_static(static, f"{value.label}: {value.value}" if value.value else "")
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
            _sync_action(button, action)
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


class CompositeStepBody(VerticalGroup):
    """Compose several stable, keyed atomic editors into one semantic step body."""

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS

    def __init__(
        self,
        presentation: CompositeBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._parts = tuple(
            _atomic_body_widget(
                _child_id(id, part.key),
                part.body,
                classes="guided-composite-part",
            )
            for part in presentation.parts
        )
        super().__init__(
            *self._parts,
            id=id,
            classes=_classes("guided-step-body guided-composite-body", classes),
        )
        self.sync_presentation(presentation)

    def sync_presentation(self, presentation: CompositeBodyPresentation) -> None:
        if tuple(part.key for part in self._presentation.parts) != tuple(
            part.key for part in presentation.parts
        ):
            raise ValueError("composite body part keys cannot change after composition")
        for previous, current in zip(
            self._presentation.parts,
            presentation.parts,
            strict=True,
        ):
            if previous.body.kind != current.body.kind:
                raise ValueError("composite body part kinds cannot change after composition")
        self._presentation = presentation
        for widget, part in zip(self._parts, presentation.parts, strict=True):
            _sync_atomic_body_widget(widget, part.body)


class WorkflowStepHeader(HorizontalGroup, can_focus=True):
    """Focusable, structured step summary with independent progress and severity cues."""

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS
    BINDINGS = [Binding("enter,space", "activate", "Open step", show=False)]
    _STATES = ("locked", "available", "current", "complete")
    _SEVERITIES = ("warning", "error")

    class Activated(Message):
        def __init__(self, header: WorkflowStepHeader, step_key: str) -> None:
            super().__init__()
            self.header = header
            self.step_key = step_key

        @property
        def control(self) -> WorkflowStepHeader:
            return self.header

    def __init__(
        self,
        step: StepPresentation,
        number: int,
        *,
        id: str | None = None,
    ) -> None:
        self.step_key = step.key
        self.number = number
        self._marker = Label("", classes="workflow-step-marker")
        self._number = Label("", classes="workflow-step-number")
        self._title = Label("", classes="workflow-step-title")
        self._summary = Label("", classes="workflow-step-summary")
        self._copy = VerticalGroup(
            self._title,
            self._summary,
            classes="workflow-step-copy",
        )
        self._status = Label("", classes="workflow-step-status")
        super().__init__(
            self._marker,
            self._number,
            self._copy,
            self._status,
            id=id,
            classes="workspace-control",
        )
        self.sync_presentation(step, number)

    def sync_presentation(self, step: StepPresentation, number: int) -> None:
        self.step_key = step.key
        self.number = number
        for state in self._STATES:
            self.remove_class(f"step-{state}")
        for severity in self._SEVERITIES:
            self.remove_class(f"step-{severity}")
        self.add_class(f"step-{step.state}")
        if step.severity != "none":
            self.add_class(f"step-{step.severity}")
        compact = step.state in {"locked", "available"}
        self.set_class(compact, "step-compact")
        self.disabled = step.state == "locked"
        marker, state_label = {
            "locked": ("[ ]", "Locked"),
            "available": ("[ ]", "Ready"),
            "current": ("[>]", "Current"),
            "complete": ("[x]", "Complete"),
        }[step.state]
        if step.severity != "none":
            state_label = f"{state_label} / {step.severity.title()}"
        self._marker.update(Content.from_text(marker, markup=False))
        self._number.update(Content.from_text(str(number), markup=False))
        self._title.update(Content.from_text(step.title, markup=False))
        self._summary.update(Content.from_text(step.summary, markup=False))
        self._summary.display = bool(step.summary) and not compact
        self._status.update(Content.from_text(state_label, markup=False))

    def action_activate(self) -> None:
        if not self.disabled:
            self.post_message(self.Activated(self, self.step_key))

    def on_click(self, event: Click) -> None:
        event.stop()
        self.focus()
        self.action_activate()


class WorkflowStep(VerticalGroup):
    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS

    def __init__(
        self,
        step: StepPresentation,
        number: int,
        *,
        expanded: bool,
        widget_prefix: str,
    ) -> None:
        self.step_key = step.key
        self.header = WorkflowStepHeader(
            step,
            number,
            id=f"workflow-{widget_prefix}-{step.key}-header",
        )
        self.body = _body_widget(f"{widget_prefix}-{step.key}", step.body)
        self.issue = InlineNotice(step.issue, classes="guided-step-issue")
        super().__init__(self.header, self.body, self.issue)
        self.sync_presentation(step, number, expanded=expanded)

    def sync_presentation(
        self,
        step: StepPresentation,
        number: int,
        *,
        expanded: bool,
    ) -> None:
        if step.key != self.step_key:
            raise ValueError("workflow step keys cannot change after composition")
        self.header.sync_presentation(step, number)
        _sync_body_widget(self.body, step.body)
        self.body.display = expanded
        self.issue.sync_presentation(step.issue)
        self.issue.display = expanded and step.issue is not None


class WorkflowStepStack(VerticalGroup):
    """Render every step header while expanding only the active step body."""

    DEFAULT_CSS = _GUIDED_WORKFLOW_CSS

    class StepRequested(Message):
        def __init__(self, stack: WorkflowStepStack, step_key: str) -> None:
            super().__init__()
            self.stack = stack
            self.step_key = step_key

        @property
        def control(self) -> WorkflowStepStack:
            return self.stack

    def __init__(
        self,
        presentation: WorkflowPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._steps = tuple(
            WorkflowStep(
                step,
                number,
                expanded=step.key == presentation.active_step,
                widget_prefix=presentation.task_key,
            )
            for number, step in enumerate(presentation.steps, start=1)
        )
        super().__init__(*self._steps, id=id, classes=classes)

    @property
    def active_step(self) -> str:
        return self._presentation.active_step

    def sync_presentation(self, presentation: WorkflowPresentation) -> None:
        if presentation.task_key != self._presentation.task_key:
            raise ValueError("a step stack cannot switch workflow task")
        if tuple(step.key for step in presentation.steps) != tuple(
            step.step_key for step in self._steps
        ):
            raise ValueError("workflow step keys cannot change after composition")
        self._presentation = presentation
        for number, (widget, step) in enumerate(
            zip(self._steps, presentation.steps, strict=True),
            start=1,
        ):
            widget.sync_presentation(
                step,
                number,
                expanded=step.key == presentation.active_step,
            )

    def focus_active(self) -> None:
        step = next(step for step in self._steps if step.step_key == self.active_step)
        step.header.focus(scroll_visible=True)

    def on_workflow_step_header_activated(self, event: WorkflowStepHeader.Activated) -> None:
        event.stop()
        self.post_message(self.StepRequested(self, event.step_key))


def _body_widget(widget_prefix: str, body: StepBodyPresentation) -> Widget:
    widget_id = f"workflow-{widget_prefix}-body"
    if isinstance(body, CompositeBodyPresentation):
        return CompositeStepBody(body, id=widget_id)
    return _atomic_body_widget(widget_id, body)


def _atomic_body_widget(
    widget_id: str | None,
    body: AtomicStepBodyPresentation,
    *,
    classes: str | None = None,
) -> Widget:
    if isinstance(body, SourceBodyPresentation):
        return SourceChooser(body, id=widget_id, classes=classes)
    if isinstance(body, UnlockBodyPresentation):
        return UnlockEditor(body, id=widget_id, classes=classes)
    if isinstance(body, PathSelectionBodyPresentation):
        return PathSelectionEditor(body, id=widget_id, classes=classes)
    if isinstance(body, DestinationBodyPresentation):
        return DestinationEditor(body, id=widget_id, classes=classes)
    if isinstance(body, QuorumBodyPresentation):
        return QuorumEditor(body, id=widget_id, classes=classes)
    return OptionsEditor(body, id=widget_id, classes=classes)


def _sync_body_widget(widget: Widget, body: StepBodyPresentation) -> None:
    if isinstance(widget, CompositeStepBody) and isinstance(body, CompositeBodyPresentation):
        widget.sync_presentation(body)
    elif not isinstance(body, CompositeBodyPresentation):
        _sync_atomic_body_widget(widget, body)
    else:
        raise ValueError("workflow step body kind cannot change after composition")


def _sync_atomic_body_widget(widget: Widget, body: AtomicStepBodyPresentation) -> None:
    if isinstance(widget, SourceChooser) and isinstance(body, SourceBodyPresentation):
        widget.sync_presentation(body)
    elif isinstance(widget, UnlockEditor) and isinstance(body, UnlockBodyPresentation):
        widget.sync_presentation(body)
    elif isinstance(widget, PathSelectionEditor) and isinstance(
        body, PathSelectionBodyPresentation
    ):
        widget.sync_presentation(body)
    elif isinstance(widget, DestinationEditor) and isinstance(body, DestinationBodyPresentation):
        widget.sync_presentation(body)
    elif isinstance(widget, QuorumEditor) and isinstance(body, QuorumBodyPresentation):
        widget.sync_presentation(body)
    elif isinstance(widget, OptionsEditor) and isinstance(body, OptionsBodyPresentation):
        widget.sync_presentation(body)
    else:
        raise ValueError("workflow step body kind cannot change after composition")


def _sync_static(widget: Static, value: str) -> None:
    widget.display = bool(value)
    widget.update(value)


def _sync_action(button: Button, action: WorkspaceAction | None) -> None:
    button.display = action is not None and action.visible
    if action is None:
        button.label = Content.from_text("", markup=False)
        button.disabled = True
        return
    button.label = Content.from_text(action.label, markup=False)
    button.disabled = not action.enabled


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


def _child_id(owner_id: str | None, suffix: str) -> str | None:
    return f"{owner_id}-{suffix}" if owner_id is not None else None


def _classes(required: str, optional: str | None) -> str:
    return required if not optional else f"{required} {optional}"
