from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, RadioButton, RadioSet, Select, Static

from ethernity.app.workspaces.common import (
    AUTH_MATERIAL_OPTIONS,
    RESTORE_AUTH_OPTIONS,
    BaseWorkspace,
    auth_material_select_value,
    button_row,
    field_row,
    first_value,
    group,
    group_label,
    labeled_select_row,
    path_table,
    section,
    set_select,
    status_note,
    update_radio,
    update_status_note,
    update_table,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class RestoreWorkspace(BaseWorkspace):
    task_key = "restore"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Backup to restore")
                yield status_note("restore-source-status")
                yield path_table("restore-source-table")
                yield button_row(
                    WorkspaceAction("workspace-restore-source", "Load scanned pages..."),
                )
                yield button_row(
                    WorkspaceAction("workspace-restore-recovery-text", "Paste recovery text..."),
                )
                yield button_row(
                    WorkspaceAction("workspace-restore-payloads", "Load payload files..."),
                )
                yield button_row(
                    WorkspaceAction("workspace-restore-expected-head", "Show fingerprint..."),
                )
            with section():
                yield group_label("Unlock backup")
                yield status_note("restore-unlock-status")
                with RadioSet(
                    id="workspace-restore-unlock-method",
                    classes="workspace-control",
                    compact=True,
                ):
                    yield RadioButton(
                        "Enter passphrase",
                        id="workspace-restore-unlock-passphrase",
                    )
                    yield RadioButton(
                        "Use recovery sheets",
                        id="workspace-restore-unlock-recovery_documents",
                    )
                    yield RadioButton(
                        "Use recovery payload files",
                        id="workspace-restore-unlock-recovery_payloads",
                    )
                yield Static("", id="restore-unlock-summary", classes="workspace-field-note")
                yield button_row(
                    WorkspaceAction("workspace-restore-unlock", "Set unlock method...")
                )
            with section():
                yield group_label("Choose version to restore")
                yield status_note("restore-target-status")
                with RadioSet(
                    id="workspace-restore-target-method",
                    classes="workspace-control",
                    compact=True,
                ):
                    yield RadioButton(
                        "Newest loaded version",
                        id="workspace-restore-target-latest",
                    )
                    yield RadioButton(
                        "Initial backup only",
                        id="workspace-restore-target-original",
                    )
                    yield RadioButton(
                        "Specific version/update",
                        id="workspace-restore-target-specific_update",
                    )
                yield Static("", id="restore-target-summary", classes="workspace-field-note")
                yield button_row(
                    WorkspaceAction("workspace-restore-target", "Set version/update..."),
                    WorkspaceAction("workspace-restore-target-fingerprint", "Show fingerprint..."),
                )
            with section():
                yield group_label("Signature check")
                yield status_note("restore-authentication-status")
                yield labeled_select_row(
                    "Signature check",
                    "workspace-restore-auth-policy",
                    RESTORE_AUTH_OPTIONS,
                )
                yield labeled_select_row(
                    "Trust source",
                    "workspace-restore-auth-material",
                    AUTH_MATERIAL_OPTIONS,
                )
            with section():
                yield group_label("Choose restore destination")
                yield status_note("restore-output-status")
                yield field_row(
                    "Restore files to",
                    "restore-output-value",
                    WorkspaceAction("workspace-restore-output", "Choose restore folder..."),
                )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        source = group(presentation, "source")
        update_status_note(self, "restore-source-status", source)
        update_table(
            self.query_one("#restore-source-table", DataTable),
            source,
        )
        unlock = group(presentation, "unlock")
        update_status_note(self, "restore-unlock-status", unlock)
        update_radio(self, "workspace-restore-unlock", unlock.choices)
        self.query_one("#restore-unlock-summary", Static).update(first_value(unlock))
        target = group(presentation, "target")
        update_status_note(self, "restore-target-status", target)
        update_radio(self, "workspace-restore-target", target.choices)
        self.query_one("#restore-target-summary", Static).update(first_value(target))
        auth = group(presentation, "authentication")
        update_status_note(self, "restore-authentication-status", auth)
        set_select(
            self.query_one("#workspace-restore-auth-policy", Select),
            "allow-unsigned"
            if value(auth, "allow-unsigned").lower().startswith("allow")
            else "require-signed",
        )
        set_select(
            self.query_one("#workspace-restore-auth-material", Select),
            auth_material_select_value(value(auth, "auth-material")),
        )
        output = group(presentation, "output")
        update_status_note(self, "restore-output-status", output)
        self.query_one("#restore-output-value", Static).update(first_value(output))
