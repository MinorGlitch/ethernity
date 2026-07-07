from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll
from textual.widgets import Button, DataTable, RadioButton, RadioSet, Select, Static

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
    status_note,
    update_buttons,
    update_radio,
    update_status_note,
    update_table,
    value,
    value_row,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction, WorkspaceGroup


class AddFilesWorkspace(BaseWorkspace):
    task_key = "add_files"
    _advanced_row_ids = (
        "add-files-advanced-base-row",
        "add-files-advanced-qr-row",
        "add-files-advanced-unlock-row",
        "add-files-advanced-recovery-row",
        "add-files-advanced-signing-row",
    )

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Existing backup")
                yield status_note("add-files-backup-status")
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
                )
                yield button_row(
                    WorkspaceAction("workspace-add-files-fingerprint", "Show fingerprint..."),
                )
            with section():
                yield group_label("Files to add")
                yield status_note("add-files-files-status")
                yield path_table("add-files-table")
                yield button_row(WorkspaceAction("workspace-add-files-files", "Choose files..."))
            with section():
                yield group_label("Unlock backup")
                yield status_note("add-files-unlock-status")
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
                yield group_label("Save updated backup documents to")
                yield status_note("add-files-output-status")
                yield value_row(
                    "Save documents to",
                    "add-files-output-value",
                )
            with section():
                yield group_label("Print options")
                yield status_note("add-files-options-status")
                yield select_row("Paper size", "workspace-add-files-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-add-files-design", DESIGN_OPTIONS)
            with section():
                yield group_label("Advanced")
                yield status_note("add-files-advanced-status")
                with HorizontalGroup(
                    id="add-files-advanced-summary-row",
                    classes="workspace-field-row",
                ):
                    yield Static(
                        "Advanced: using saved defaults",
                        id="add-files-advanced-summary",
                        classes="workspace-field-value",
                    )
                    yield Button(
                        "Show advanced",
                        id="add-files-advanced-toggle",
                        compact=True,
                        classes="workspace-control",
                    )
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
                yield labeled_select_row(
                    "Unlock policy",
                    "workspace-add-files-unlock-policy",
                    ADD_FILES_UNLOCK_POLICY_OPTIONS,
                    row_id="add-files-advanced-unlock-row",
                )
                yield select_summary_row(
                    "Recovery sheets",
                    "workspace-add-files-recovery-docs",
                    ADD_FILES_RECOVERY_OPTIONS,
                    "add-files-recovery-value",
                    row_id="add-files-advanced-recovery-row",
                )
                yield select_summary_row(
                    "Signing key",
                    "workspace-add-files-signing-key-mode",
                    ADD_FILES_SIGNING_KEY_OPTIONS,
                    "add-files-signing-key-value",
                    row_id="add-files-advanced-signing-row",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "add-files-advanced-toggle":
            return
        event.stop()
        self._advanced_expanded = not getattr(self, "_advanced_expanded", False)
        self._sync_advanced_visibility()

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        backup = group(presentation, "backup")
        update_status_note(self, "add-files-backup-status", backup)
        self.query_one("#add-files-backup-value", Static).update(value(backup, "backup"))
        self.query_one("#add-files-source-value", Static).update(value(backup, "source"))
        update_buttons(self, backup.actions)
        files = group(presentation, "files")
        update_status_note(self, "add-files-files-status", files)
        update_table(self.query_one("#add-files-table", DataTable), files)
        unlock = group(presentation, "unlock")
        update_status_note(self, "add-files-unlock-status", unlock)
        update_radio(self, "workspace-add-files-unlock", unlock.choices)
        self.query_one("#add-files-unlock-summary", Static).update(first_value(unlock))
        output = group(presentation, "output")
        update_status_note(self, "add-files-output-status", output)
        self.query_one("#add-files-output-value", Static).update(first_value(output))
        options = group(presentation, "options")
        update_status_note(self, "add-files-options-status", options)
        set_select(
            self.query_one("#workspace-add-files-paper", Select),
            value(options, "paper"),
        )
        set_select(
            self.query_one("#workspace-add-files-design", Select),
            value(options, "design"),
        )
        advanced = group(presentation, "advanced")
        update_status_note(self, "add-files-advanced-status", advanced)
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
        self.query_one("#add-files-advanced-summary", Static).update(
            _add_files_advanced_summary(advanced)
        )
        self._sync_advanced_visibility()

    def _sync_advanced_visibility(self) -> None:
        expanded = getattr(self, "_advanced_expanded", False)
        for row_id in self._advanced_row_ids:
            self.query_one(f"#{row_id}").display = expanded
        self.query_one("#add-files-advanced-toggle", Button).label = (
            "Hide advanced" if expanded else "Show advanced"
        )


def _add_files_advanced_summary(advanced_group: WorkspaceGroup) -> str:
    return (
        "Advanced: using saved defaults | "
        f"QR density: {value(advanced_group, 'qr-chunk-size')} | "
        f"Recovery: {value(advanced_group, 'recovery-docs')}"
    )
