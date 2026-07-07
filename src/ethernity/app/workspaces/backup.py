from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll
from textual.widgets import Button, DataTable, RadioButton, RadioSet, Select, Static

from ethernity.app.workspaces.common import (
    BACKUP_PASSPHRASE_WORD_OPTIONS,
    DESIGN_OPTIONS,
    PAPER_OPTIONS,
    BaseWorkspace,
    button_row,
    field_row,
    group,
    group_label,
    labeled_select_row,
    path_table,
    section,
    select_row,
    set_select,
    status_note,
    update_buttons,
    update_radio,
    update_status_note,
    update_table,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction, WorkspaceGroup


class BackupWorkspace(BaseWorkspace):
    task_key = "backup"
    _advanced_row_ids = (
        "backup-advanced-passphrase-row",
        "backup-advanced-words-row",
        "backup-advanced-base-row",
        "backup-advanced-qr-row",
        "backup-advanced-signing-row",
        "backup-advanced-key-sheets-row",
    )

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Files to back up")
                yield status_note("backup-files-status")
                yield path_table("backup-files-table")
                yield button_row(WorkspaceAction("workspace-backup-files", "Choose files..."))
            with section():
                yield group_label("Recovery method")
                yield status_note("backup-recovery-status")
                with RadioSet(
                    id="workspace-backup-recovery-method",
                    classes="workspace-control",
                    compact=True,
                ):
                    yield RadioButton(
                        "Recommended: 3 recovery sheets; any 2 can restore",
                        id="workspace-backup-recovery-recommended_shards",
                    )
                    yield RadioButton(
                        "Single recovery phrase",
                        id="workspace-backup-recovery-single_phrase",
                    )
                    yield RadioButton(
                        "Custom recovery sheets",
                        id="workspace-backup-recovery-custom_shards",
                    )
            with section():
                yield group_label("Save backup documents to")
                yield status_note("backup-destination-status")
                yield field_row(
                    "Save documents to",
                    "backup-output-value",
                    WorkspaceAction("workspace-backup-output", "Choose output folder..."),
                )
            with section():
                yield group_label("Print options")
                yield status_note("backup-layout-status")
                yield select_row("Paper size", "workspace-backup-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-backup-design", DESIGN_OPTIONS)
            with section():
                yield group_label("Advanced")
                yield status_note("backup-advanced-status")
                with HorizontalGroup(
                    id="backup-advanced-summary-row", classes="workspace-field-row"
                ):
                    yield Static(
                        "Advanced: using saved defaults",
                        id="backup-advanced-summary",
                        classes="workspace-field-value",
                    )
                    yield Button(
                        "Show advanced",
                        id="backup-advanced-toggle",
                        compact=True,
                        classes="workspace-control",
                    )
                yield field_row(
                    "Passphrase",
                    "backup-passphrase-value",
                    WorkspaceAction("workspace-backup-passphrase", "Set passphrase..."),
                    row_id="backup-advanced-passphrase-row",
                )
                yield labeled_select_row(
                    "Generated words",
                    "workspace-backup-passphrase-words",
                    BACKUP_PASSPHRASE_WORD_OPTIONS,
                    row_id="backup-advanced-words-row",
                )
                yield field_row(
                    "Base folder",
                    "backup-base-dir-value",
                    WorkspaceAction("workspace-backup-base-dir", "Choose base folder..."),
                    row_id="backup-advanced-base-row",
                )
                yield field_row(
                    "QR density",
                    "backup-qr-chunk-size-value",
                    WorkspaceAction("workspace-backup-qr-chunk-size", "Set QR density..."),
                    row_id="backup-advanced-qr-row",
                )
                yield select_row(
                    "Signing key",
                    "workspace-backup-signing-key-mode",
                    ("embedded", "sharded"),
                    row_id="backup-advanced-signing-row",
                )
                yield field_row(
                    "Key sheets",
                    "backup-signing-key-shards-value",
                    WorkspaceAction("workspace-backup-signing-key-shards", "Set key sheets..."),
                    row_id="backup-advanced-key-sheets-row",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "backup-advanced-toggle":
            return
        event.stop()
        self._advanced_expanded = not getattr(self, "_advanced_expanded", False)
        self._sync_advanced_visibility()

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        files = group(presentation, "files")
        update_status_note(self, "backup-files-status", files)
        update_table(
            self.query_one("#backup-files-table", DataTable),
            files,
        )
        recovery = group(presentation, "recovery")
        update_status_note(self, "backup-recovery-status", recovery)
        update_radio(self, "workspace-backup-recovery", recovery.choices)
        destination = group(presentation, "destination")
        update_status_note(self, "backup-destination-status", destination)
        self.query_one("#backup-output-value", Static).update(value(destination, "output"))
        layout = group(presentation, "layout")
        update_status_note(self, "backup-layout-status", layout)
        set_select(self.query_one("#workspace-backup-paper", Select), value(layout, "paper"))
        set_select(
            self.query_one("#workspace-backup-design", Select),
            value(layout, "design"),
        )
        advanced = group(presentation, "advanced")
        update_status_note(self, "backup-advanced-status", advanced)
        self.query_one("#backup-passphrase-value", Static).update(value(advanced, "passphrase"))
        passphrase_words = value(advanced, "passphrase-words")
        set_select(
            self.query_one("#workspace-backup-passphrase-words", Select),
            "default" if passphrase_words == "Default: saved setting" else passphrase_words,
        )
        self.query_one("#backup-base-dir-value", Static).update(value(advanced, "base-dir"))
        self.query_one("#backup-qr-chunk-size-value", Static).update(
            value(advanced, "qr-chunk-size")
        )
        set_select(
            self.query_one("#workspace-backup-signing-key-mode", Select),
            "sharded"
            if value(advanced, "signing-key").lower().startswith("sharded")
            else "embedded",
        )
        self.query_one("#backup-signing-key-shards-value", Static).update(
            value(advanced, "signing-key")
        )
        update_buttons(self, advanced.actions)
        self.query_one("#backup-advanced-summary", Static).update(
            _backup_advanced_summary(advanced)
        )
        self._sync_advanced_visibility()

    def _sync_advanced_visibility(self) -> None:
        expanded = getattr(self, "_advanced_expanded", False)
        for row_id in self._advanced_row_ids:
            self.query_one(f"#{row_id}").display = expanded
        self.query_one("#backup-advanced-toggle", Button).label = (
            "Hide advanced" if expanded else "Show advanced"
        )


def _backup_advanced_summary(advanced_group: WorkspaceGroup) -> str:
    return (
        "Advanced: using saved defaults | "
        f"QR density: {value(advanced_group, 'qr-chunk-size')} | "
        f"Signature: {value(advanced_group, 'signing-key')}"
    )
