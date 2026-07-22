"""Shared harness and presentation factories for workflow widget tests."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.widget import Widget

from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.app.widgets.workflow.paths import DestinationEditor, PathSelectionEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.tasks.presentation.models import (
    ChoicePresentation,
    SourceBodyPresentation,
    StepPresentation,
    SummaryPresentation,
    WorkflowPresentation,
    WorkspaceAction,
)

__all__ = ["PrimitiveHarness", "make_source_body", "make_workflow"]


class PrimitiveHarness(App[None]):
    def __init__(self, widget: Widget) -> None:
        super().__init__()
        self.widget = widget
        self.source_methods: list[str] = []
        self.unlock_methods: list[str] = []
        self.unlock_actions: list[str] = []
        self.step_requests: list[str] = []
        self.quorum_values: list[tuple[int | None, int | None]] = []
        self.destination_actions: list[str] = []
        self.path_actions: list[str] = []
        self.option_selects: list[tuple[str, str | None]] = []
        self.option_actions: list[str] = []

    def compose(self) -> ComposeResult:
        yield self.widget

    @on(SourceChooser.MethodChanged)
    def record_source_method(self, event: SourceChooser.MethodChanged) -> None:
        self.source_methods.append(event.method_key)

    @on(UnlockEditor.MethodChanged)
    def record_unlock_method(self, event: UnlockEditor.MethodChanged) -> None:
        self.unlock_methods.append(event.method_key)

    @on(UnlockEditor.ActionRequested)
    def record_unlock_action(self, event: UnlockEditor.ActionRequested) -> None:
        self.unlock_actions.append(event.action.key)

    @on(WorkflowStepStack.StepRequested)
    def record_step_request(self, event: WorkflowStepStack.StepRequested) -> None:
        self.step_requests.append(event.step_key)

    @on(QuorumEditor.Changed)
    def record_quorum(self, event: QuorumEditor.Changed) -> None:
        self.quorum_values.append((event.threshold, event.count))

    @on(DestinationEditor.ActionRequested)
    def record_destination_action(self, event: DestinationEditor.ActionRequested) -> None:
        self.destination_actions.append(event.action.key)

    @on(PathSelectionEditor.ActionRequested)
    def record_path_action(self, event: PathSelectionEditor.ActionRequested) -> None:
        self.path_actions.append(event.action.key)

    @on(OptionsEditor.SelectChanged)
    def record_option_select(self, event: OptionsEditor.SelectChanged) -> None:
        self.option_selects.append((event.select_key, event.value))

    @on(OptionsEditor.ActionRequested)
    def record_option_action(self, event: OptionsEditor.ActionRequested) -> None:
        self.option_actions.append(event.action.key)


def make_source_body(selected: str | None = None) -> SourceBodyPresentation:
    return SourceBodyPresentation(
        methods=(
            ChoicePresentation("scans", "Scanned pages", selected=selected == "scans"),
            ChoicePresentation("text", "Paste recovery text", selected=selected == "text"),
            ChoicePresentation("payloads", "Payload files", selected=selected == "payloads"),
        )
    )


def make_workflow(
    *,
    active_step: str,
    steps: tuple[StepPresentation, ...],
) -> WorkflowPresentation:
    return WorkflowPresentation(
        task_key="restore",
        title="Restore files",
        active_step=active_step,
        steps=steps,
        primary_action=WorkspaceAction("continue", "Continue"),
        review_summary=SummaryPresentation(
            title="Review restore",
            items=(),
            blockers=(),
            warnings=(),
        ),
    )
