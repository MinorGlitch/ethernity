"""Workflow step composition and navigation widgets."""

from __future__ import annotations

from textual.containers import VerticalGroup
from textual.widget import Widget

from ethernity.app.widgets.form import FormScroll, FormSection
from ethernity.app.widgets.workflow.controls import InlineNotice, child_id, merge_classes
from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.app.widgets.workflow.paths import DestinationEditor, PathSelectionEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.tasks.presentation.models import (
    CompositeBodyPresentation,
    ControlBodyPresentation,
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
    "WorkflowStepStack",
]


class CompositeStepBody(VerticalGroup):
    """Combine several groups of controls in one workflow step."""

    def __init__(
        self,
        presentation: CompositeBodyPresentation,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._presentation = presentation
        self._parts = tuple(
            _control_body_widget(
                child_id(id, part.key),
                part.body,
                classes="guided-composite-part",
            )
            for part in presentation.parts
        )
        self._sections = tuple(
            FormSection(part.title, widget)
            for widget, part in zip(self._parts, presentation.parts, strict=True)
        )
        super().__init__(
            *self._sections,
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
        for widget, section, part in zip(
            self._parts, self._sections, presentation.parts, strict=True
        ):
            _sync_control_body_widget(widget, part.body)
            section.display = widget.display


class WorkflowStep(VerticalGroup):
    def __init__(
        self,
        step: StepPresentation,
        *,
        expanded: bool,
        widget_prefix: str,
    ) -> None:
        self.step_key = step.key
        self.body = _body_widget(f"{widget_prefix}-{step.key}", step.body)
        self.issue = InlineNotice(step.issue, classes="guided-step-issue")
        content = (
            self.body
            if isinstance(step.body, CompositeBodyPresentation)
            else FormSection(step.title, self.body)
        )
        super().__init__(content, self.issue, id=f"workflow-{widget_prefix}-{step.key}")
        self.sync_presentation(step, expanded=expanded)

    def sync_presentation(
        self,
        step: StepPresentation,
        *,
        expanded: bool,
    ) -> None:
        if step.key != self.step_key:
            raise ValueError("workflow step keys cannot change after composition")
        self.display = step.visible and expanded
        _sync_body_widget(self.body, step.body)
        self.body.display = expanded
        self.issue.sync_presentation(step.issue)
        self.issue.display = expanded and step.issue is not None


class WorkflowStepStack(VerticalGroup):
    """Keep step editors mounted while presenting the active step."""

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
                expanded=step.key == presentation.active_step,
                widget_prefix=presentation.task_key,
            )
            for step in presentation.steps
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
        for widget, step in zip(self._steps, presentation.steps, strict=True):
            widget.sync_presentation(
                step,
                expanded=step.key == presentation.active_step,
            )

    def focus_active(self) -> None:
        step = next(step for step in self._steps if step.step_key == self.active_step)
        control = next(
            (
                widget
                for widget in step.body.query("*")
                if widget.can_focus and not widget.disabled and widget.region.area > 0
            ),
            None,
        )
        if control is not None:
            form = next(
                (parent for parent in self.ancestors if isinstance(parent, FormScroll)), None
            )
            if form is not None:
                form.focus_start(control)
            else:
                control.focus(scroll_visible=True)


def _body_widget(widget_prefix: str, body: StepBodyPresentation) -> Widget:
    widget_id = f"workflow-{widget_prefix}-body"
    if isinstance(body, CompositeBodyPresentation):
        return CompositeStepBody(body, id=widget_id)
    return _control_body_widget(widget_id, body)


def _control_body_widget(
    widget_id: str | None,
    body: ControlBodyPresentation,
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
        _sync_control_body_widget(widget, body)
    else:
        raise ValueError("workflow step body kind cannot change after composition")


def _sync_control_body_widget(widget: Widget, body: ControlBodyPresentation) -> None:
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
