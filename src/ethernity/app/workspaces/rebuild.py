from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Select, Static

from ethernity.app.widgets.form import FormScroll, FormSection
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.workflow_presenter import rebuild_workflow_placeholder
from ethernity.app.workspaces.workspace_controls import (
    QR_DENSITY_HELP,
    SIGNATURE_SOURCE_OPTIONS,
    BaseWorkspace,
    control_value,
    field_row,
    group,
    labeled_select_row,
    set_select,
    update_buttons,
    update_issue_note,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class RebuildWorkspace(BaseWorkspace):
    task_key = "rebuild"

    step_sections = {
        "source": ("rebuild-verification-section",),
        "output": ("rebuild-qr-section",),
    }

    def compose(self) -> ComposeResult:
        with FormScroll(classes="task-workspace"):
            yield WorkflowStepStack(rebuild_workflow_placeholder(), id="rebuild-step-stack")
            with FormSection("Verification", id="rebuild-verification-section"):
                yield labeled_select_row(
                    "Signatures from",
                    "workspace-rebuild-signature-source",
                    SIGNATURE_SOURCE_OPTIONS,
                )
                yield InlineNotice(id="rebuild-verification-notice")
            with FormSection("QR codes", id="rebuild-qr-section"):
                yield field_row(
                    "Density",
                    "rebuild-qr-chunk-size-value",
                    WorkspaceAction("workspace-rebuild-qr-chunk-size", "Set QR density..."),
                    tooltip=QR_DENSITY_HELP,
                )
                yield InlineNotice(id="rebuild-qr-notice")

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        if presentation.workflow is None:
            raise ValueError("rebuild workspace requires a guided workflow presentation")
        self.query_one("#rebuild-step-stack", WorkflowStepStack).sync_presentation(
            presentation.workflow
        )
        advanced = group(presentation, "advanced")
        update_issue_note(self, "rebuild-qr-notice", presentation, "REBUILD_CUSTOM_QR_DENSITY")

        set_select(
            self.query_one("#workspace-rebuild-signature-source", Select),
            control_value(advanced, "signature-source"),
        )
        update_static_text(
            self.query_one("#rebuild-qr-chunk-size-value", Static),
            value(advanced, "qr-chunk-size"),
        )
        update_issue_note(
            self, "rebuild-verification-notice", presentation, "REBUILD_SIGNATURE_SOURCE_CONFLICT"
        )
        update_buttons(self, advanced.actions)
