"""Event-recording app and presentation samples for workflow widget tests."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.widget import Widget

from ethernity.app.styling import StyledApp
from ethernity.app.widgets.workflow.controls import WorkspaceActionRequested
from ethernity.app.widgets.workflow.options import OptionsEditor, QuorumEditor
from ethernity.app.widgets.workflow.paths import DestinationEditor, PathSelectionEditor
from ethernity.app.widgets.workflow.source import SourceChooser
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.tasks.presentation.models import (
    SourceBodyPresentation,
    StepPresentation,
    SummaryPresentation,
    WorkflowPresentation,
    WorkspaceAction,
)

__all__ = ["WorkflowWidgetHarness", "sample_restore_workflow", "sample_source_body"]


class WorkflowWidgetHarness(StyledApp):
    def __init__(self, widget: Widget) -> None:
        super().__init__()
        self.widget = widget
        self.source_actions: list[str] = []
        self.unlock_methods: list[str] = []
        self.unlock_actions: list[str] = []
        self.unlock_values: list[str] = []
        self.quorum_values: list[tuple[int | None, int | None]] = []
        self.destination_actions: list[str] = []
        self.destination_values: list[str] = []
        self.path_actions: list[str] = []
        self.option_selects: list[tuple[str, str | None]] = []
        self.option_actions: list[str] = []

    def compose(self) -> ComposeResult:
        yield self.widget

    @on(UnlockEditor.MethodChanged)
    def record_unlock_method(self, event: UnlockEditor.MethodChanged) -> None:
        self.unlock_methods.append(event.method_key)

    @on(UnlockEditor.ValueChanged)
    def record_unlock_value(self, event: UnlockEditor.ValueChanged) -> None:
        self.unlock_values.append(event.value)

    @on(DestinationEditor.ValueChanged)
    def record_destination_value(self, event: DestinationEditor.ValueChanged) -> None:
        self.destination_values.append(event.value)

    @on(QuorumEditor.Changed)
    def record_quorum(self, event: QuorumEditor.Changed) -> None:
        self.quorum_values.append((event.threshold, event.count))

    @on(OptionsEditor.SelectChanged)
    def record_option_select(self, event: OptionsEditor.SelectChanged) -> None:
        self.option_selects.append((event.select_key, event.value))

    @on(WorkspaceActionRequested)
    def record_workspace_action(self, event: WorkspaceActionRequested) -> None:
        if isinstance(event.control, SourceChooser):
            self.source_actions.append(event.action.key)
        elif isinstance(event.control, UnlockEditor):
            self.unlock_actions.append(event.action.key)
        elif isinstance(event.control, DestinationEditor):
            self.destination_actions.append(event.action.key)
        elif isinstance(event.control, PathSelectionEditor):
            self.path_actions.append(event.action.key)
        elif isinstance(event.control, OptionsEditor):
            self.option_actions.append(event.action.key)


def sample_source_body(selected: str | None = None) -> SourceBodyPresentation:
    return SourceBodyPresentation(
        primary_action=WorkspaceAction("load", "Load backup documents..."),
        secondary_actions=(
            WorkspaceAction("text", "Paste printed text..."),
            WorkspaceAction("payloads", "Load exported data..."),
        ),
    )


def sample_restore_workflow(
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
