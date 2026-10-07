from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from ethernity.app.widgets.form import FormRow, FormScroll, FormSection
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.workflow_presenter import add_files_workflow_placeholder
from ethernity.app.workspaces.workspace_controls import (
    QR_DENSITY_HELP,
    SIGNATURE_SOURCE_OPTIONS,
    BaseWorkspace,
    control_value,
    field_row,
    group,
    labeled_select_row,
    update_buttons,
    update_issue_note,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class AddFilesWorkspace(BaseWorkspace):
    task_key = "add_files"

    step_sections = {
        "source": ("add-files-verification-section",),
        "files": ("add-files-series-section", "add-files-paths-section"),
        "output": ("add-files-qr-section", "add-files-recovery-section"),
    }

    def compose(self) -> ComposeResult:
        with FormScroll(classes="task-workspace"):
            yield WorkflowStepStack(add_files_workflow_placeholder(), id="add-files-step-stack")
            with FormSection("Verification", id="add-files-verification-section"):
                yield labeled_select_row(
                    "Signatures from",
                    "workspace-add-files-signature-source",
                    SIGNATURE_SOURCE_OPTIONS,
                )
                yield InlineNotice(id="add-files-verification-notice")
            with FormSection("File paths", id="add-files-paths-section"):
                yield field_row(
                    "Base folder",
                    "add-files-base-dir-value",
                    WorkspaceAction("workspace-add-files-base-dir", "Choose base folder..."),
                )
            with FormSection("Update series", id="add-files-series-section"):
                yield labeled_select_row(
                    "Mode",
                    "workspace-add-files-update-mode",
                    (
                        ("Cumulative (recommended)", "cumulative"),
                        ("Incremental (smaller updates)", "incremental"),
                    ),
                    row_id="add-files-update-mode-choice",
                    tooltip=(
                        "Cumulative needs the original and latest update. Incremental can print "
                        "less but needs every update. Fixed after the first update; "
                        "use Rebuild to change."
                    ),
                )
                yield FormRow(
                    "Mode",
                    Static(
                        "",
                        id="add-files-update-mode-value",
                        classes="field-text form-value",
                        markup=False,
                    ),
                    id="add-files-update-mode-summary",
                )
            with FormSection("QR codes", id="add-files-qr-section"):
                yield field_row(
                    "Density",
                    "add-files-qr-chunk-size-value",
                    WorkspaceAction("workspace-add-files-qr-chunk-size", "Set QR density..."),
                    tooltip=QR_DENSITY_HELP,
                )
                yield InlineNotice(id="add-files-qr-notice")
            with FormSection("Recovery sheets", id="add-files-recovery-section"):
                yield field_row(
                    "New sheets",
                    "add-files-recovery-sheets-value",
                    WorkspaceAction(
                        "workspace-add-files-recovery-sheets", "Configure recovery sheets..."
                    ),
                )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        if presentation.workflow is None:
            raise ValueError("add-files workspace requires a guided workflow presentation")
        self.query_one("#add-files-step-stack", WorkflowStepStack).sync_presentation(
            presentation.workflow
        )
        advanced = group(presentation, "advanced")
        locked = control_value(advanced, "update-mode-locked") == "locked"
        self.query_one("#add-files-update-mode-choice").display = not locked
        mode_label = self.query_one("#add-files-update-mode-value", Static)
        self.query_one("#add-files-update-mode-summary").display = locked
        update_static_text(mode_label, value(advanced, "update-mode"))
        self.sync_selects(
            advanced,
            {
                "update-mode": "#workspace-add-files-update-mode",
                "signature-source": "#workspace-add-files-signature-source",
            },
        )
        update_issue_note(self, "add-files-qr-notice", presentation, "ADD_FILES_CUSTOM_QR_DENSITY")

        self.sync_values(
            advanced,
            {
                "base-dir": "#add-files-base-dir-value",
                "qr-chunk-size": "#add-files-qr-chunk-size-value",
                "recovery-sheets": "#add-files-recovery-sheets-value",
            },
        )

        update_issue_note(
            self,
            "add-files-verification-notice",
            presentation,
            "ADD_FILES_SIGNATURE_SOURCE_CONFLICT",
        )
        update_buttons(self, advanced.actions)
