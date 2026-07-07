from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, RadioButton, RadioSet, Select, Static

from ethernity.app.workspaces.common import (
    ADD_FILES_RECOVERY_OPTIONS,
    ADD_FILES_SIGNING_KEY_OPTIONS,
    ADD_FILES_UNLOCK_POLICY_OPTIONS,
    DESIGN_OPTIONS,
    PAPER_OPTIONS,
    BaseWorkspace,
    add_files_recovery_select_value,
    add_files_signing_key_select_value,
    button_row,
    field_row,
    first_value,
    group,
    group_label,
    labeled_select_row,
    path_table,
    section,
    select_row,
    select_summary_row,
    set_select,
    update_buttons,
    update_radio,
    update_table,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class AddFilesWorkspace(BaseWorkspace):
    task_key = "add_files"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Existing backup")
                yield field_row(
                    "Existing backup",
                    "add-files-backup-value",
                    WorkspaceAction("workspace-add-files-backup", "Choose backup folder..."),
                )
                yield field_row(
                    "Loaded backup source",
                    "add-files-source-value",
                    WorkspaceAction("workspace-add-files-source", "Load scanned pages..."),
                )
                yield button_row(
                    WorkspaceAction("workspace-add-files-freshness", "Use this backup"),
                    WorkspaceAction("workspace-add-files-fingerprint", "Show fingerprint..."),
                )
            with section():
                yield group_label("Files to add")
                yield path_table("add-files-table")
                yield button_row(WorkspaceAction("workspace-add-files-files", "Choose files..."))
            with section():
                yield group_label("Unlock backup")
                with RadioSet(
                    id="workspace-add-files-unlock-method",
                    classes="workspace-control",
                    compact=True,
                ):
                    yield RadioButton(
                        "Enter passphrase",
                        id="workspace-add-files-unlock-passphrase",
                    )
                    yield RadioButton(
                        "Use recovery sheets",
                        id="workspace-add-files-unlock-recovery_documents",
                    )
                    yield RadioButton(
                        "Use recovery payload files",
                        id="workspace-add-files-unlock-recovery_payloads",
                    )
                yield Static("", id="add-files-unlock-summary", classes="workspace-field-note")
                yield button_row(
                    WorkspaceAction("workspace-add-files-unlock", "Set unlock method...")
                )
            with section():
                yield group_label("Print options")
                yield select_row("Paper size", "workspace-add-files-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-add-files-design", DESIGN_OPTIONS)
                yield field_row(
                    "Base folder",
                    "add-files-base-dir-value",
                    WorkspaceAction("workspace-add-files-base-dir", "Choose base folder..."),
                )
                yield field_row(
                    "QR density",
                    "add-files-qr-chunk-size-value",
                    WorkspaceAction("workspace-add-files-qr-chunk-size", "Set QR density..."),
                )
                yield labeled_select_row(
                    "Unlock policy",
                    "workspace-add-files-unlock-policy",
                    ADD_FILES_UNLOCK_POLICY_OPTIONS,
                )
                yield select_summary_row(
                    "Recovery sheets",
                    "workspace-add-files-recovery-docs",
                    ADD_FILES_RECOVERY_OPTIONS,
                    "add-files-recovery-value",
                )
                yield select_summary_row(
                    "Signing key",
                    "workspace-add-files-signing-key-mode",
                    ADD_FILES_SIGNING_KEY_OPTIONS,
                    "add-files-signing-key-value",
                )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        backup = group(presentation, "backup")
        self.query_one("#add-files-backup-value", Static).update(value(backup, "backup"))
        self.query_one("#add-files-source-value", Static).update(value(backup, "source"))
        update_buttons(self, backup.actions)
        update_table(self.query_one("#add-files-table", DataTable), group(presentation, "files"))
        unlock = group(presentation, "unlock")
        update_radio(self, "workspace-add-files-unlock", unlock.choices)
        self.query_one("#add-files-unlock-summary", Static).update(first_value(unlock))
        options = group(presentation, "options")
        set_select(
            self.query_one("#workspace-add-files-paper", Select),
            value(options, "paper"),
        )
        set_select(
            self.query_one("#workspace-add-files-design", Select),
            value(options, "design"),
        )
        advanced = group(presentation, "advanced")
        self.query_one("#add-files-base-dir-value", Static).update(value(advanced, "base-dir"))
        self.query_one("#add-files-qr-chunk-size-value", Static).update(
            value(advanced, "qr-chunk-size")
        )
        set_select(
            self.query_one("#workspace-add-files-unlock-policy", Select),
            "reuse-root"
            if value(advanced, "unlock-policy").lower().startswith("reuse")
            else "self-contained",
        )
        set_select(
            self.query_one("#workspace-add-files-recovery-docs", Select),
            add_files_recovery_select_value(value(advanced, "recovery-docs")),
        )
        self.query_one("#add-files-recovery-value", Static).update(value(advanced, "recovery-docs"))
        set_select(
            self.query_one("#workspace-add-files-signing-key-mode", Select),
            add_files_signing_key_select_value(value(advanced, "signing-key")),
        )
        self.query_one("#add-files-signing-key-value", Static).update(
            value(advanced, "signing-key")
        )
        update_buttons(self, advanced.actions)
