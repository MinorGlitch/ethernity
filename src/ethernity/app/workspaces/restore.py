from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.widgets import Select

from ethernity.app.widgets.collapsible import AppCollapsible
from ethernity.app.widgets.form import FormScroll
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.workflow_presenter import restore_workflow_placeholder
from ethernity.app.workspaces.workspace_controls import (
    RESTORE_AUTH_OPTIONS,
    SIGNATURE_SOURCE_OPTIONS,
    BaseWorkspace,
    button_row,
    control_value,
    group,
    labeled_select_row,
    set_select,
    update_buttons,
)
from ethernity.tasks.presentation.models import (
    InlineNoticePresentation,
    TaskPresentation,
    WorkspaceAction,
)


class RestoreWorkspace(BaseWorkspace):
    task_key = "restore"

    step_sections = {
        "source": ("restore-verification-section",),
    }

    def compose(self) -> ComposeResult:
        with FormScroll(classes="task-workspace"):
            yield WorkflowStepStack(restore_workflow_placeholder(), id="restore-step-stack")
            with VerticalGroup(id="restore-verification-section", classes="workspace-options"):
                with AppCollapsible(
                    title="Verification",
                    id="restore-verification-options",
                ):
                    yield labeled_select_row(
                        "Signatures",
                        "workspace-restore-auth-policy",
                        RESTORE_AUTH_OPTIONS,
                        tooltip="Allow unsigned backups only when the original has no signatures.",
                    )
                    yield labeled_select_row(
                        "Source", "workspace-restore-signature-source", SIGNATURE_SOURCE_OPTIONS
                    )
                    yield button_row(
                        WorkspaceAction(
                            "workspace-restore-expected-head", "Set latest fingerprint..."
                        )
                    )
                yield InlineNotice(id="restore-signature-notice")

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        if presentation.workflow is None:
            raise ValueError("restore workspace requires a guided workflow presentation")
        self.query_one("#restore-step-stack", WorkflowStepStack).sync_presentation(
            presentation.workflow
        )
        auth = group(presentation, "authentication")
        self.query_one("#restore-verification-options", AppCollapsible).set_heading(
            "Verification", auth.status_summary
        )
        set_select(
            self.query_one("#workspace-restore-auth-policy", Select),
            control_value(auth, "allow-unsigned"),
        )
        set_select(
            self.query_one("#workspace-restore-signature-source", Select),
            control_value(auth, "signature-source"),
        )
        update_buttons(self, auth.actions)
        self.query_one("#restore-signature-notice", InlineNotice).sync_presentation(
            InlineNoticePresentation("Unsigned backups will not be authenticated.", tone="warning")
            if control_value(auth, "allow-unsigned") == "allow-unsigned"
            else None
        )
