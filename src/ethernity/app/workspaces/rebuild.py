from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Select, Static

from ethernity.app.widgets.collapsible import panel_title
from ethernity.app.widgets.guided_workflow import WorkflowStepStack
from ethernity.app.workflow_presenter import rebuild_workflow_placeholder
from ethernity.app.workspaces.common import (
    AUTH_MATERIAL_OPTIONS,
    BaseWorkspace,
    advanced_panel,
    control_value,
    field_row,
    group,
    labeled_select_row,
    section,
    set_select,
    status_note,
    update_buttons,
    update_static_text,
    update_status_note,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction, WorkspaceGroup


class RebuildWorkspace(BaseWorkspace):
    task_key = "rebuild"
    advanced_panel_id = "rebuild-advanced-panel"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            yield WorkflowStepStack(
                rebuild_workflow_placeholder(),
                id="rebuild-step-stack",
            )
            with section():
                with advanced_panel(
                    "rebuild-advanced-panel",
                    "Advanced - QR from settings",
                ):
                    yield status_note("rebuild-advanced-status")
                    yield labeled_select_row(
                        "Verification source",
                        "workspace-rebuild-auth-material",
                        AUTH_MATERIAL_OPTIONS,
                        row_id="rebuild-advanced-auth-row",
                    )
                    yield field_row(
                        "QR density",
                        "rebuild-qr-chunk-size-value",
                        WorkspaceAction("workspace-rebuild-qr-chunk-size", "Set QR density..."),
                        row_id="rebuild-advanced-qr-row",
                    )
                    yield Static(
                        (
                            "Higher QR density can reduce page count, but may make the rebuilt "
                            "backup harder to scan. Leave the value blank to use the setting."
                        ),
                        id="rebuild-advanced-qr-help",
                        classes="workspace-field-note",
                    )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        if presentation.workflow is None:
            raise ValueError("rebuild workspace requires a guided workflow presentation")
        self.query_one("#rebuild-step-stack", WorkflowStepStack).sync_presentation(
            presentation.workflow
        )
        advanced = group(presentation, "advanced")
        update_status_note(self, "rebuild-advanced-status", advanced)
        self.query_one("#rebuild-advanced-status").display = advanced.status in {
            "warning",
            "blocked",
        }
        set_select(
            self.query_one("#workspace-rebuild-auth-material", Select),
            control_value(advanced, "auth-material"),
        )
        update_static_text(
            self.query_one("#rebuild-qr-chunk-size-value", Static),
            value(advanced, "qr-chunk-size"),
        )
        update_buttons(self, advanced.actions)
        self.sync_advanced_panel(panel_title("Advanced", _rebuild_advanced_summary(advanced)))


def _rebuild_advanced_summary(advanced_group: WorkspaceGroup) -> str:
    trust_source = value(advanced_group, "auth-material")
    qr_density = value(advanced_group, "qr-chunk-size")
    if (
        control_value(advanced_group, "auth-material") == "auto"
        and control_value(advanced_group, "qr-chunk-size") == "default"
    ):
        if control_value(advanced_group, "source-context") == "empty":
            return "QR from settings"
        return "Verification from backup; QR from settings"
    return f"Verification: {trust_source}; QR: {qr_density}"
