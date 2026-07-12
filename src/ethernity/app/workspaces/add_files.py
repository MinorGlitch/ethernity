from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Select, Static

from ethernity.app.widgets.collapsible import panel_title
from ethernity.app.widgets.guided_workflow import WorkflowStepStack
from ethernity.app.workflow_presenter import add_files_workflow_placeholder
from ethernity.app.workspaces.common import (
    ADD_FILES_RECOVERY_OPTIONS,
    ADD_FILES_SIGNING_KEY_OPTIONS,
    ADD_FILES_UNLOCK_POLICY_OPTIONS,
    BaseWorkspace,
    advanced_panel,
    control_value,
    field_row,
    group,
    labeled_select_row,
    section,
    select_summary_row,
    set_select,
    status_note,
    update_buttons,
    update_static_text,
    update_status_note,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction, WorkspaceGroup


class AddFilesWorkspace(BaseWorkspace):
    task_key = "add_files"
    advanced_panel_id = "add-files-advanced-panel"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            yield WorkflowStepStack(
                add_files_workflow_placeholder(),
                id="add-files-step-stack",
            )
            with section():
                with advanced_panel("add-files-advanced-panel", "Advanced - From settings"):
                    yield status_note("add-files-advanced-status")
                    yield field_row(
                        "Base folder",
                        "add-files-base-dir-value",
                        WorkspaceAction("workspace-add-files-base-dir", "Choose base folder..."),
                        row_id="add-files-advanced-base-row",
                    )
                    yield field_row(
                        "QR density",
                        "add-files-qr-chunk-size-value",
                        WorkspaceAction("workspace-add-files-qr-chunk-size", "Set QR density..."),
                        row_id="add-files-advanced-qr-row",
                    )
                    yield Static(
                        (
                            "Higher QR density can reduce page count, but may make the update "
                            "harder to scan. Leave the value blank to use the setting."
                        ),
                        id="add-files-advanced-qr-help",
                        classes="workspace-field-note",
                    )
                    yield labeled_select_row(
                        "Recovery scope",
                        "workspace-add-files-unlock-policy",
                        ADD_FILES_UNLOCK_POLICY_OPTIONS,
                        row_id="add-files-advanced-unlock-row",
                    )
                    yield Static(
                        (
                            "Self-contained updates include their own recovery material. Reusing "
                            "original recovery requires the original backup's recovery material."
                        ),
                        id="add-files-advanced-unlock-help",
                        classes="workspace-field-note",
                    )
                    yield select_summary_row(
                        "Recovery sheets",
                        "workspace-add-files-recovery-docs",
                        ADD_FILES_RECOVERY_OPTIONS,
                        "add-files-recovery-value",
                        row_id="add-files-advanced-recovery-row",
                    )
                    yield Static(
                        "",
                        id="add-files-advanced-recovery-help",
                        classes="workspace-field-note",
                        markup=False,
                    )
                    yield select_summary_row(
                        "Signing-key recovery",
                        "workspace-add-files-signing-key-mode",
                        ADD_FILES_SIGNING_KEY_OPTIONS,
                        "add-files-signing-key-value",
                        row_id="add-files-advanced-signing-row",
                    )
                    yield Static(
                        "",
                        id="add-files-advanced-signing-help",
                        classes="workspace-field-note",
                        markup=False,
                    )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        if presentation.workflow is None:
            raise ValueError("add-files workspace requires a guided workflow presentation")
        self.query_one("#add-files-step-stack", WorkflowStepStack).sync_presentation(
            presentation.workflow
        )
        advanced = group(presentation, "advanced")
        update_status_note(self, "add-files-advanced-status", advanced)
        self.query_one("#add-files-advanced-status").display = advanced.status in {
            "warning",
            "blocked",
        }
        update_static_text(
            self.query_one("#add-files-base-dir-value", Static),
            value(advanced, "base-dir"),
        )
        update_static_text(
            self.query_one("#add-files-qr-chunk-size-value", Static),
            value(advanced, "qr-chunk-size"),
        )
        set_select(
            self.query_one("#workspace-add-files-unlock-policy", Select),
            control_value(advanced, "unlock-policy"),
        )
        set_select(
            self.query_one("#workspace-add-files-recovery-docs", Select),
            control_value(advanced, "recovery-docs"),
        )
        update_static_text(
            self.query_one("#add-files-recovery-value", Static),
            value(advanced, "recovery-docs"),
        )
        update_static_text(
            self.query_one("#add-files-advanced-recovery-help", Static),
            _add_files_recovery_help(control_value(advanced, "recovery-docs")),
        )
        set_select(
            self.query_one("#workspace-add-files-signing-key-mode", Select),
            control_value(advanced, "signing-key"),
        )
        update_static_text(
            self.query_one("#add-files-signing-key-value", Static),
            value(advanced, "signing-key"),
        )
        update_static_text(
            self.query_one("#add-files-advanced-signing-help", Static),
            _add_files_signing_key_help(control_value(advanced, "signing-key")),
        )
        update_buttons(self, advanced.actions)
        self.sync_advanced_panel(panel_title("Advanced", _add_files_advanced_summary(advanced)))


def _add_files_advanced_summary(advanced_group: WorkspaceGroup) -> str:
    custom: list[str] = []
    if control_value(advanced_group, "base-dir") == "custom":
        custom.append("custom base folder")
    if control_value(advanced_group, "qr-chunk-size") not in {"", "default"}:
        custom.append(f"QR {value(advanced_group, 'qr-chunk-size')}")
    if control_value(advanced_group, "unlock-policy") not in {"", "default"}:
        custom.append(value(advanced_group, "unlock-policy"))
    if control_value(advanced_group, "recovery-docs") not in {"", "default"}:
        custom.append(value(advanced_group, "recovery-docs"))
    if control_value(advanced_group, "signing-key") not in {"", "default"}:
        custom.append(value(advanced_group, "signing-key"))
    if not custom:
        return "From settings"
    return "; ".join(custom)


def _add_files_recovery_help(control: str) -> str:
    if control == "none":
        return "This update will rely on existing recovery material; no new sheets are created."
    if control == "custom":
        return "The quorum sets how many new sheets you need to recover this update."
    return "Uses the recovery policy from Settings."


def _add_files_signing_key_help(control: str) -> str:
    if control == "not-stored":
        return "No separate key sheets are created. The update remains signed."
    if control == "custom":
        return "The quorum sets how many sheets you need to recover the signing key."
    if control == "sharded":
        return "Key sheets recover the signing key; they do not add an approval step."
    return (
        "Uses the policy from Settings. Key sheets recover the signing key; they do not add "
        "an approval step."
    )
