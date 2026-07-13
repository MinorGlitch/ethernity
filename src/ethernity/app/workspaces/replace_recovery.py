from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Select, Static

from ethernity.app.widgets.collapsible import panel_title
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.workflow_presenter import replace_recovery_workflow_placeholder
from ethernity.app.workspaces.common import (
    SIGNING_KEY_RECOVERY_OPTIONS,
    BaseWorkspace,
    advanced_panel,
    field_row,
    group,
    labeled_select_row,
    section,
    selected_choice,
    set_select,
    status_note,
    update_buttons,
    update_status_note,
    value,
)
from ethernity.tasks.presentation.models import (
    TaskPresentation,
    WorkspaceAction,
    WorkspaceGroup,
)

REPLACE_SIGNATURE_PANEL_ID = "replace-signature-panel"


class ReplaceRecoveryWorkspace(BaseWorkspace):
    task_key = "replace_recovery_docs"
    advanced_panel_id = REPLACE_SIGNATURE_PANEL_ID

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            yield WorkflowStepStack(
                replace_recovery_workflow_placeholder(),
                id="replace-recovery-step-stack",
            )
            with section():
                with advanced_panel(
                    REPLACE_SIGNATURE_PANEL_ID,
                    "Signing-key sheets",
                ):
                    yield status_note("replace-signing-key-status")
                    yield labeled_select_row(
                        "Key sheets",
                        "workspace-replace-signing-key-select",
                        SIGNING_KEY_RECOVERY_OPTIONS,
                        allow_blank=False,
                    )
                    yield field_row(
                        "Key-sheet quorum",
                        "replace-signing-key-quorum-value",
                        WorkspaceAction(
                            "workspace-replace-signing-key-quorum",
                            "Set quorum...",
                        ),
                        row_id="replace-signing-key-quorum-row",
                    )
                    yield field_row(
                        "Sheets to replace",
                        "replace-signing-key-count-value",
                        WorkspaceAction(
                            "workspace-replace-signing-key-count",
                            "Set sheets...",
                        ),
                        row_id="replace-signing-key-count-row",
                    )
                    yield field_row(
                        "Existing key payloads",
                        "replace-signing-key-payloads-value",
                        WorkspaceAction(
                            "workspace-replace-signing-key-payloads",
                            "Load key payloads...",
                        ),
                        row_id="replace-signing-key-payloads-row",
                    )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        if presentation.workflow is None:
            raise ValueError("replacement workspace requires a guided workflow presentation")
        self.query_one("#replace-recovery-step-stack", WorkflowStepStack).sync_presentation(
            presentation.workflow
        )

        signing_key = group(presentation, "signing-key-recovery")
        update_status_note(self, "replace-signing-key-status", signing_key)
        self.query_one("#replace-signing-key-status").display = False
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
        self.sync_advanced_panel(
            panel_title(
                "Signing-key sheets",
                _signing_key_panel_summary(signing_key, mode),
            )
        )


def _signing_key_panel_summary(signing_key: WorkspaceGroup, mode: str) -> str:
    mode_summary = {
        "off": "No separate key sheets",
        "same": "Matches recovery sheets",
        "custom": "Custom quorum",
        "replace": "Replace existing sheets",
    }.get(mode, "Choose an option")
    if signing_key.status == "blocked":
        return f"Needs attention: {mode_summary}"
    if signing_key.status == "warning":
        return f"Warning: {mode_summary}"
    return mode_summary
