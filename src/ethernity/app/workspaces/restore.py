from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Select, Static

from ethernity.app.widgets.collapsible import panel_title
from ethernity.app.widgets.guided_workflow import WorkflowStepStack
from ethernity.app.workflow_presenter import restore_workflow_placeholder
from ethernity.app.workspaces.common import (
    AUTH_MATERIAL_OPTIONS,
    RESTORE_AUTH_OPTIONS,
    BaseWorkspace,
    advanced_panel,
    button_row,
    control_value,
    group,
    group_label,
    labeled_select_row,
    section,
    set_select,
    status_note,
    update_buttons,
    update_status_note,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction

RESTORE_ADVANCED_PANEL_ID = "restore-advanced-panel"


class RestoreWorkspace(BaseWorkspace):
    task_key = "restore"
    advanced_panel_id = RESTORE_ADVANCED_PANEL_ID

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            yield WorkflowStepStack(
                restore_workflow_placeholder(),
                id="restore-step-stack",
            )
            with section():
                with advanced_panel(
                    RESTORE_ADVANCED_PANEL_ID,
                    "Verification",
                ):
                    yield group_label("Latest backup")
                    yield button_row(
                        WorkspaceAction(
                            "workspace-restore-expected-head",
                            "Set expected latest fingerprint...",
                        )
                    )
                    yield group_label("Signature verification")
                    yield status_note("restore-authentication-status")
                    yield labeled_select_row(
                        "Policy",
                        "workspace-restore-auth-policy",
                        RESTORE_AUTH_OPTIONS,
                    )
                    yield labeled_select_row(
                        "Verification source",
                        "workspace-restore-auth-material",
                        AUTH_MATERIAL_OPTIONS,
                    )
                    yield Static(
                        (
                            "Trusted signatures confirm that the supplied material belongs to "
                            "one signed backup. Allow unsigned legacy backups only when the "
                            "original backup has no signatures."
                        ),
                        id="restore-authentication-help",
                        classes="workspace-field-note",
                    )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        if presentation.workflow is None:
            raise ValueError("restore workspace requires a guided workflow presentation")
        self.query_one("#restore-step-stack", WorkflowStepStack).sync_presentation(
            presentation.workflow
        )
        auth = group(presentation, "authentication")
        update_status_note(self, "restore-authentication-status", auth)
        self.query_one("#restore-authentication-status").display = False
        set_select(
            self.query_one("#workspace-restore-auth-policy", Select),
            control_value(auth, "allow-unsigned"),
        )
        set_select(
            self.query_one("#workspace-restore-auth-material", Select),
            control_value(auth, "auth-material"),
        )
        update_buttons(self, auth.actions)
        advanced_summary = (
            "Unsigned legacy backups allowed"
            if auth.status == "warning"
            else "Trusted signatures required"
        )
        self.sync_advanced_panel(panel_title("Verification", advanced_summary))
