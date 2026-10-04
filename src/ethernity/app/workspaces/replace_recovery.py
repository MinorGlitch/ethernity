from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Select, Static

from ethernity.app.widgets.form import FormScroll, FormSection
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.workflow_presenter import replace_recovery_workflow_placeholder
from ethernity.app.workspaces.workspace_controls import (
    SIGNING_KEY_RECOVERY_OPTIONS,
    BaseWorkspace,
    field_row,
    group,
    labeled_select_row,
    selected_choice,
    set_select,
    update_buttons,
    update_issue_note,
    value,
)
from ethernity.tasks.presentation.models import (
    TaskPresentation,
    WorkspaceAction,
)


class ReplaceRecoveryWorkspace(BaseWorkspace):
    task_key = "replace_recovery_docs"

    step_sections = {"recovery": ("replace-signing-section",)}

    def compose(self) -> ComposeResult:
        with FormScroll(classes="task-workspace"):
            yield WorkflowStepStack(
                replace_recovery_workflow_placeholder(), id="replace-recovery-step-stack"
            )
            with FormSection("Signing-key recovery", id="replace-signing-section"):
                yield labeled_select_row(
                    "Key sheets",
                    "workspace-replace-signing-key-select",
                    SIGNING_KEY_RECOVERY_OPTIONS,
                )
                yield field_row(
                    "Quorum",
                    "replace-signing-key-quorum-value",
                    WorkspaceAction("workspace-replace-signing-key-quorum", "Set quorum..."),
                    row_id="replace-signing-key-quorum-row",
                )
                yield field_row(
                    "Replace",
                    "replace-signing-key-count-value",
                    WorkspaceAction("workspace-replace-signing-key-count", "Set sheets..."),
                    row_id="replace-signing-key-count-row",
                )
                yield field_row(
                    "Key payloads",
                    "replace-signing-key-payloads-value",
                    WorkspaceAction("workspace-replace-signing-key-payloads", "Key payloads..."),
                    row_id="replace-signing-key-payloads-row",
                )
                yield InlineNotice(id="replace-signing-notice")

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        if presentation.workflow is None:
            raise ValueError("replacement workspace requires a guided workflow presentation")
        self.query_one("#replace-recovery-step-stack", WorkflowStepStack).sync_presentation(
            presentation.workflow
        )

        signing_key = group(presentation, "signing-key-recovery")
        update_issue_note(
            self,
            "replace-signing-notice",
            presentation,
            "REPLACE_RECOVERY_SIGNING_KEY_QUORUM_REQUIRED",
            "REPLACE_RECOVERY_SIGNING_KEY_REPLACEMENT_INPUT_REQUIRED",
            "REPLACE_RECOVERY_SIGNING_KEY_RECOVERY_OFF",
        )
        mode = selected_choice(signing_key.choices)
        set_select(
            self.query_one("#workspace-replace-signing-key-select", Select),
            mode,
        )
        update_static_text(
            self.query_one("#replace-signing-key-quorum-value", Static),
            value(signing_key, "signing-key"),
        )
        update_static_text(
            self.query_one("#replace-signing-key-count-value", Static),
            value(signing_key, "signing-key"),
        )
        update_static_text(
            self.query_one("#replace-signing-key-payloads-value", Static),
            value(signing_key, "signing-key-payloads"),
        )
        update_buttons(self, signing_key.actions)
        self.query_one("#replace-signing-key-quorum-row").display = mode == "custom"
        self.query_one("#replace-signing-key-count-row").display = mode == "replace"
        self.query_one("#replace-signing-key-payloads-row").display = mode == "replace"
