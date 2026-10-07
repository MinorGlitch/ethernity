from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.widgets import Button, Collapsible, Select, Static

from ethernity.app.widgets.collapsible import AppCollapsible, sync_collapsible_panel
from ethernity.app.widgets.form import FormScroll, FormSection
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.workflow.controls import InlineNotice, KeyedRadioSet
from ethernity.app.workspaces.workspace_controls import (
    BACKUP_PASSPHRASE_WORD_OPTIONS,
    BACKUP_SIGNING_KEY_OPTIONS,
    DESIGN_OPTIONS,
    PAPER_OPTIONS,
    QR_DENSITY_HELP,
    BaseWorkspace,
    WorkspacePathList,
    button_row,
    choice_group,
    control_value,
    field_row,
    group,
    labeled_select_row,
    path_selection_list,
    select_row,
    selected_choice,
    set_select,
    status_note,
    update_buttons,
    update_issue_note,
    update_path_selection_list,
    update_status_note,
    value,
)
from ethernity.page_sizes import paper_size_display_name
from ethernity.render.designs import load_design_definition_by_name, supported_paper_size_names
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.page_layout import BACKUP_RENDER_DOC_TYPES
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class BackupWorkspace(BaseWorkspace):
    task_key = "backup"
    _files_expanded = True
    step_sections = {
        "files": ("backup-files-section", "backup-paths-section"),
        "recovery": (
            "backup-recovery-section",
            "backup-passphrase-section",
            "backup-signing-section",
        ),
        "print": ("backup-print-section", "backup-qr-section", "backup-output-section"),
    }

    def compose(self) -> ComposeResult:
        with FormScroll(classes="task-workspace"):
            with FormSection("Files", id="backup-files-section"):
                with HorizontalGroup(classes="workspace-button-row"):
                    yield Button(
                        "Choose files...",
                        id="workspace-backup-files",
                        variant="primary",
                        classes="workspace-control",
                    )
                    yield Static("", classes="action-gap")
                    yield Static(
                        "", id="backup-files-value", classes="field-text detail-label", markup=False
                    )
                with AppCollapsible(
                    id="backup-files-panel",
                    title="Selected files",
                    collapsed=False,
                    collapsed_symbol="+",
                    expanded_symbol="-",
                ):
                    yield path_selection_list("backup-files-list")
                    yield button_row(WorkspaceAction("workspace-backup-clear-files", "Clear files"))
            with FormSection("File paths", id="backup-paths-section"):
                yield field_row(
                    "Base folder",
                    "backup-base-dir-value",
                    WorkspaceAction("workspace-backup-base-dir", "Choose base folder..."),
                )
            with FormSection("Recovery method", id="backup-recovery-section"):
                yield status_note("backup-recovery-status")
                yield choice_group(
                    "workspace-backup-recovery",
                    tuple(
                        (option.key, option.label)
                        for option in BackupTaskState().facts().recovery_options
                    ),
                )
                yield field_row(
                    "Quorum",
                    "backup-quorum-value",
                    WorkspaceAction("workspace-backup-recovery-quorum", "Change quorum..."),
                    row_id="backup-custom-quorum-row",
                )
                yield Static(
                    "", id="backup-recovery-help", classes="workspace-field-note", markup=False
                )
            with FormSection("Passphrase", id="backup-passphrase-section"):
                yield field_row(
                    "Source",
                    "backup-passphrase-value",
                    WorkspaceAction("workspace-backup-passphrase", "Set passphrase..."),
                )
                yield labeled_select_row(
                    "Phrase length",
                    "workspace-backup-passphrase-words",
                    BACKUP_PASSPHRASE_WORD_OPTIONS,
                    row_id="backup-words-row",
                )
            with FormSection("Signing-key recovery", id="backup-signing-section"):
                yield labeled_select_row(
                    "Store key",
                    "workspace-backup-signing-key-mode",
                    BACKUP_SIGNING_KEY_OPTIONS,
                )
                yield field_row(
                    "Quorum",
                    "backup-signing-key-shards-value",
                    WorkspaceAction("workspace-backup-signing-key-shards", "Set quorum..."),
                    row_id="backup-key-sheets-row",
                )
                yield InlineNotice(id="backup-signing-notice")
            with FormSection("Page layout", id="backup-print-section"):
                yield select_row("Paper size", "workspace-backup-paper-size", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-backup-design", DESIGN_OPTIONS)
            with FormSection("QR codes", id="backup-qr-section"):
                yield field_row(
                    "Density",
                    "backup-qr-chunk-size-value",
                    WorkspaceAction("workspace-backup-qr-chunk-size", "Set QR density..."),
                    tooltip=QR_DENSITY_HELP,
                )
                yield InlineNotice(id="backup-qr-notice")
                yield Static(
                    "",
                    id="backup-estimate-error",
                    classes="workspace-field-note workspace-status-warning",
                    markup=False,
                )
            with FormSection("Destination", id="backup-output-section"):
                yield field_row(
                    "Save to",
                    "backup-output-value",
                    WorkspaceAction("workspace-backup-output", "Choose folder..."),
                )
                yield status_note("backup-destination-status")
                yield Static(
                    "",
                    id="backup-output-summary",
                    classes="backup-output-summary workspace-field-note",
                    markup=False,
                )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        files = group(presentation, "files")
        files_summary = self.query_one("#backup-files-value", Static)
        update_static_text(files_summary, files.status_summary if files.values else "")
        files_summary.display = bool(files.values)
        self.query_one("#backup-files-panel").display = bool(files.values)
        update_path_selection_list(
            self.query_one("#backup-files-list", WorkspacePathList),
            files,
        )
        update_buttons(self, files.actions)
        sync_collapsible_panel(
            self,
            "backup-files-panel",
            expanded=self._files_expanded,
            title="Selected files",
        )
        recovery = group(presentation, "recovery")
        update_status_note(self, "backup-recovery-status", recovery)
        self.query_one("#backup-recovery-status").display = recovery.status == "blocked"
        self.query_one("#workspace-backup-recovery-method", KeyedRadioSet).sync_choices(
            recovery.choices
        )
        custom_quorum = selected_choice(recovery.choices) == "custom_shards"
        self.query_one("#backup-custom-quorum-row").display = custom_quorum
        update_static_text(self.query_one("#backup-quorum-value", Static), recovery.status_summary)
        update_buttons(self, recovery.actions)
        update_static_text(
            self.query_one("#backup-recovery-help", Static),
            value(recovery, "storage-note"),
        )
        print_setup = group(presentation, "print")
        paper_select = self.query_one("#workspace-backup-paper-size", Select)
        design = value(print_setup, "design")
        definition = load_design_definition_by_name(design)
        names = supported_paper_size_names(
            design, doc_types=definition.documents & BACKUP_RENDER_DOC_TYPES
        )
        with paper_select.prevent(Select.Changed):
            paper_select.set_options([(paper_size_display_name(name), name) for name in names])
        set_select(paper_select, value(print_setup, "paper"))
        set_select(self.query_one("#workspace-backup-design", Select), design)
        documents = group(presentation, "documents")
        update_static_text(
            self.query_one("#backup-output-summary", Static),
            value(documents, "inventory"),
        )
        error = value(documents, "estimate-error")
        estimate_note = self.query_one("#backup-estimate-error", Static)
        estimate_note.display = bool(error)
        update_static_text(estimate_note, f"Print estimate unavailable: {error}" if error else "")
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
        update_issue_note(self, "backup-qr-notice", presentation, "BACKUP_CUSTOM_QR_DENSITY")

        self.sync_values(
            advanced,
            {
                "passphrase": "#backup-passphrase-value",
                "base-dir": "#backup-base-dir-value",
                "qr-chunk-size": "#backup-qr-chunk-size-value",
                "signing-key": "#backup-signing-key-shards-value",
            },
        )
        self.sync_selects(
            advanced,
            {
                "passphrase-words": "#workspace-backup-passphrase-words",
                "signing-key": "#workspace-backup-signing-key-mode",
            },
        )

        update_issue_note(
            self,
            "backup-signing-notice",
            presentation,
            "BACKUP_SIGNING_KEY_QUORUM_INCOMPLETE",
            "BACKUP_SIGNING_KEY_QUORUM_MODE_REQUIRED",
        )
        update_buttons(self, advanced.actions)
        self.query_one("#backup-words-row").display = (
            control_value(advanced, "passphrase") == "generated"
        )
        self.query_one("#backup-key-sheets-row").display = (
            control_value(advanced, "signing-key") == "sharded"
        )

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible.id == "backup-files-panel":
            event.stop()
            self._files_expanded = True
            return

    def on_collapsible_collapsed(self, event: Collapsible.Collapsed) -> None:
        if event.collapsible.id == "backup-files-panel":
            event.stop()
            self._files_expanded = False
            return
