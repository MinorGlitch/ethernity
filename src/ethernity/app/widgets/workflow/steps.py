"""Workflow step composition and navigation widgets."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.events import Click
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label

from ethernity.app.widgets.workflow.controls import InlineNotice, child_id, merge_classes
from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.app.widgets.workflow.paths import DestinationEditor, PathSelectionEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.styles import GUIDED_WORKFLOW_CSS
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.tasks.presentation.models import (
    AtomicStepBodyPresentation,
    CompositeBodyPresentation,
    DestinationBodyPresentation,
    OptionsBodyPresentation,
    PathSelectionBodyPresentation,
    QuorumBodyPresentation,
    SourceBodyPresentation,
    StepBodyPresentation,
    StepPresentation,
    UnlockBodyPresentation,
    WorkflowPresentation,
)

__all__ = [
    "CompositeStepBody",
    "WorkflowStep",
    "WorkflowStepHeader",
    "WorkflowStepStack",
]


class CompositeStepBody(VerticalGroup):
    """Compose several stable, keyed atomic editors into one semantic step body."""

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS

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
                child_id(id, part.key),
                part.body,
                classes="guided-composite-part",
            )
            for part in presentation.parts
        )
        super().__init__(
            *self._parts,
            id=id,
            classes=merge_classes("guided-step-body guided-composite-body", classes),
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

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS
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
    DEFAULT_CSS = GUIDED_WORKFLOW_CSS

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

    DEFAULT_CSS = GUIDED_WORKFLOW_CSS

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
