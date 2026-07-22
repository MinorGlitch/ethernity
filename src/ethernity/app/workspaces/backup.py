from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Select, Static

from ethernity.app.widgets.collapsible import panel_title
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.workspaces.common import (
    BACKUP_PASSPHRASE_WORD_OPTIONS,
    BACKUP_SIGNING_KEY_OPTIONS,
    BaseWorkspace,
    WorkspacePathList,
    advanced_panel,
    button_row,
    choice_group,
    control_value,
    field_row,
    group,
    group_label,
    labeled_select_row,
    path_selection_list,
    section,
    selected_choice,
    set_select,
    status_note,
    update_buttons,
    update_choice_list,
    update_path_selection_list,
    update_status_note,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction, WorkspaceGroup


class BackupWorkspace(BaseWorkspace):
    task_key = "backup"
    advanced_panel_id = "backup-advanced-panel"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Files to back up")
                yield status_note("backup-files-status")
                yield path_selection_list("backup-files-list")
                yield button_row(
                    WorkspaceAction("workspace-backup-files", "Choose files..."),
                    WorkspaceAction("workspace-backup-clear-files", "Clear files"),
                )
            with section():
                yield group_label("Recovery method")
                yield status_note("backup-recovery-status")
                yield choice_group(
                    "workspace-backup-recovery",
                    (
                        (
                            "recommended_shards",
                            "3 recovery sheets; any 2 can restore (recommended)",
                        ),
                        ("single_phrase", "Single recovery phrase"),
                        ("custom_shards", "Custom quorum"),
                    ),
                )
                yield Static(
                    "",
                    id="backup-recovery-help",
                    classes="workspace-field-note",
                    markup=False,
                )
            with section():
                yield group_label("Destination")
                yield status_note("backup-destination-status")
                yield field_row(
                    "Folder",
                    "backup-output-value",
                    WorkspaceAction("workspace-backup-output", "Choose folder..."),
                )
            with section():
                with advanced_panel(
                    "backup-advanced-panel",
                    "Advanced - QR from settings; key embedded",
                ):
                    yield status_note("backup-advanced-status")
                    yield field_row(
                        "Passphrase",
                        "backup-passphrase-value",
                        WorkspaceAction("workspace-backup-passphrase", "Set passphrase..."),
                        row_id="backup-advanced-passphrase-row",
                    )
                    yield labeled_select_row(
                        "Generated passphrase",
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
                    yield Static(
                        (
                            "Higher QR density can reduce page count, but may make codes harder "
                            "to scan. Leave the value blank to use the setting."
                        ),
                        id="backup-advanced-qr-help",
                        classes="workspace-field-note",
                    )
                    yield labeled_select_row(
                        "Signing-key recovery",
                        "workspace-backup-signing-key-mode",
                        BACKUP_SIGNING_KEY_OPTIONS,
                        row_id="backup-advanced-signing-row",
                    )
                    yield field_row(
                        "Key-sheet quorum",
                        "backup-signing-key-shards-value",
                        WorkspaceAction("workspace-backup-signing-key-shards", "Set quorum..."),
                        row_id="backup-advanced-key-sheets-row",
                    )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        files = group(presentation, "files")
        update_status_note(self, "backup-files-status", files)
        self.query_one("#backup-files-status").display = files.status != "missing"
        update_path_selection_list(
            self.query_one("#backup-files-list", WorkspacePathList),
            files,
        )
        update_buttons(self, files.actions)
        recovery = group(presentation, "recovery")
        update_status_note(self, "backup-recovery-status", recovery)
        self.query_one("#backup-recovery-status").display = recovery.status in {
            "warning",
            "blocked",
        }
        update_choice_list(self, "workspace-backup-recovery", recovery.choices)
        update_static_text(
            self.query_one("#backup-recovery-help", Static),
            _backup_recovery_help(selected_choice(recovery.choices)),
        )
        destination = group(presentation, "destination")
        update_status_note(self, "backup-destination-status", destination)
        self.query_one("#backup-destination-status").display = destination.status in {
            "warning",
            "blocked",
        }
        update_static_text(
            self.query_one("#backup-output-value", Static),
            value(destination, "output"),
        )
        advanced = group(presentation, "advanced")
        update_status_note(self, "backup-advanced-status", advanced)
        self.query_one("#backup-advanced-status").display = advanced.status in {
            "warning",
            "blocked",
        }
        update_static_text(
            self.query_one("#backup-passphrase-value", Static),
            value(advanced, "passphrase"),
        )
        set_select(
            self.query_one("#workspace-backup-passphrase-words", Select),
            control_value(advanced, "passphrase-words"),
        )
        update_static_text(
            self.query_one("#backup-base-dir-value", Static),
            value(advanced, "base-dir"),
        )
        update_static_text(
            self.query_one("#backup-qr-chunk-size-value", Static),
            value(advanced, "qr-chunk-size"),
        )
        set_select(
            self.query_one("#workspace-backup-signing-key-mode", Select),
            control_value(advanced, "signing-key"),
        )
        update_static_text(
            self.query_one("#backup-signing-key-shards-value", Static),
            value(advanced, "signing-key"),
        )
        update_buttons(self, advanced.actions)
        self.sync_advanced_panel(panel_title("Advanced", _backup_advanced_summary(advanced)))


def _backup_advanced_summary(advanced_group: WorkspaceGroup) -> str:
    custom: list[str] = []
    if control_value(advanced_group, "passphrase") == "custom":
        custom.append("custom passphrase")
    words = control_value(advanced_group, "passphrase-words")
    if words not in {"", "default"}:
        custom.append(f"{words}-word passphrase")
    if control_value(advanced_group, "base-dir") == "custom":
        custom.append("custom base folder")
    if control_value(advanced_group, "qr-chunk-size") not in {"", "default"}:
        custom.append(f"QR {value(advanced_group, 'qr-chunk-size')}")
    if control_value(advanced_group, "signing-key") not in {"", "embedded"}:
        custom.append(value(advanced_group, "signing-key"))
    if not custom:
        return "QR from settings; key embedded"
    return "; ".join(custom)


def _backup_recovery_help(recovery_method: str) -> str:
    if recovery_method == "single_phrase":
        return "A single phrase has no spare copy. Store it securely."
    if recovery_method == "custom_shards":
        return "A custom quorum changes how many sheets you must gather to restore the backup."
    return "Store the sheets separately. Any 2 can restore the backup if one is lost."
