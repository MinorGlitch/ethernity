from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, RadioButton, RadioSet, Select, Static

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
    update_buttons,
    update_radio,
    update_table,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class BackupWorkspace(BaseWorkspace):
    task_key = "backup"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Files to back up")
                yield path_table("backup-files-table")
                yield button_row(WorkspaceAction("workspace-backup-files", "Choose files..."))
            with section():
                yield group_label("Recovery method")
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
                yield field_row(
                    "Save documents to",
                    "backup-output-value",
                    WorkspaceAction("workspace-backup-output", "Choose output folder..."),
                )
                yield select_row("Paper size", "workspace-backup-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-backup-design", DESIGN_OPTIONS)
            with section():
                yield group_label("Advanced")
                yield field_row(
                    "Passphrase",
                    "backup-passphrase-value",
                    WorkspaceAction("workspace-backup-passphrase", "Set passphrase..."),
                )
                yield labeled_select_row(
                    "Generated words",
                    "workspace-backup-passphrase-words",
                    BACKUP_PASSPHRASE_WORD_OPTIONS,
                )
                yield field_row(
                    "Base folder",
                    "backup-base-dir-value",
                    WorkspaceAction("workspace-backup-base-dir", "Choose base folder..."),
                )
                yield field_row(
                    "QR density",
                    "backup-qr-chunk-size-value",
                    WorkspaceAction("workspace-backup-qr-chunk-size", "Set QR density..."),
                )
                yield select_row(
                    "Signing key", "workspace-backup-signing-key-mode", ("embedded", "sharded")
                )
                yield field_row(
                    "Key sheets",
                    "backup-signing-key-shards-value",
                    WorkspaceAction("workspace-backup-signing-key-shards", "Set key sheets..."),
                )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        update_table(
            self.query_one("#backup-files-table", DataTable),
            group(presentation, "files"),
        )
        recovery = group(presentation, "recovery")
        update_radio(self, "workspace-backup-recovery", recovery.choices)
        destination = group(presentation, "destination")
        self.query_one("#backup-output-value", Static).update(value(destination, "output"))
        set_select(self.query_one("#workspace-backup-paper", Select), value(destination, "paper"))
        set_select(
            self.query_one("#workspace-backup-design", Select),
            value(destination, "design"),
        )
        advanced = group(presentation, "advanced")
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
