from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, RadioButton, RadioSet, Select, Static

from ethernity.app.workspaces.common import (
    DESIGN_OPTIONS,
    PAPER_OPTIONS,
    PASSPHRASE_RECOVERY_OPTIONS,
    SIGNING_KEY_RECOVERY_OPTIONS,
    BaseWorkspace,
    button_row,
    field_row,
    first_value,
    group,
    group_label,
    labeled_select_row,
    path_table,
    replace_passphrase_recovery_select_value,
    section,
    select_row,
    select_summary_row,
    selected_choice,
    set_select,
    status_note,
    update_buttons,
    update_radio,
    update_status_note,
    update_table,
    value,
    value_row,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class ReplaceRecoveryWorkspace(BaseWorkspace):
    task_key = "replace_recovery_docs"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Existing backup")
                yield status_note("replace-source-status")
                yield path_table("replace-source-table")
                yield button_row(
                    WorkspaceAction("workspace-replace-source", "Load scanned pages..."),
                )
                yield button_row(
                    WorkspaceAction("workspace-replace-recovery-text", "Paste recovery text..."),
                )
                yield button_row(
                    WorkspaceAction("workspace-replace-payloads", "Load payload files..."),
                )
                yield button_row(
                    WorkspaceAction("workspace-replace-freshness", "Use this backup"),
                )
                yield button_row(
                    WorkspaceAction("workspace-replace-fingerprint", "Show fingerprint..."),
                )
            with section():
                yield group_label("Unlock existing backup")
                yield status_note("replace-unlock-status")
                with RadioSet(
                    id="workspace-replace-unlock-method",
                    classes="workspace-control",
                    compact=True,
                ):
                    yield RadioButton(
                        "Enter passphrase",
                        id="workspace-replace-unlock-passphrase",
                    )
                    yield RadioButton(
                        "Use current recovery sheets",
                        id="workspace-replace-unlock-recovery_documents",
                    )
                    yield RadioButton(
                        "Use recovery payload files",
                        id="workspace-replace-unlock-recovery_payloads",
                    )
                yield Static("", id="replace-unlock-summary", classes="workspace-field-note")
                yield button_row(
                    WorkspaceAction("workspace-replace-unlock", "Set unlock method...")
                )
            with section():
                yield group_label("New recovery method")
                yield status_note("replace-recovery-status")
                with RadioSet(
                    id="workspace-replace-recovery-method",
                    classes="workspace-control",
                    compact=True,
                ):
                    yield RadioButton(
                        "3 new recovery sheets; any 2 can restore",
                        id="workspace-replace-recovery-recommended",
                    )
                    yield RadioButton(
                        "Custom recovery sheets",
                        id="workspace-replace-recovery-custom",
                    )
                yield Static("", id="replace-recovery-summary", classes="workspace-field-note")
                yield button_row(
                    WorkspaceAction("workspace-replace-recovery", "Change recovery method...")
                )
                yield select_summary_row(
                    "Passphrase sheets",
                    "workspace-replace-passphrase-select",
                    PASSPHRASE_RECOVERY_OPTIONS,
                    "replace-passphrase-value",
                )
                yield field_row(
                    "Passphrase sheet count",
                    "replace-passphrase-count-value",
                    WorkspaceAction("workspace-replace-passphrase-count", "Set sheets..."),
                )
            with section():
                yield group_label("Save replacement sheets to")
                yield status_note("replace-output-status")
                yield field_row(
                    "Save documents to",
                    "replace-output-value",
                    WorkspaceAction("workspace-replace-output", "Choose output folder..."),
                )
                yield value_row("Safety", "replace-safety-value")
            with section():
                yield group_label("Print options")
                yield status_note("replace-layout-status")
                yield select_row("Paper size", "workspace-replace-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-replace-design", DESIGN_OPTIONS)
            with section():
                yield group_label("Signature")
                yield status_note("replace-signing-key-status")
                yield labeled_select_row(
                    "Signing key recovery",
                    "workspace-replace-signing-key-select",
                    SIGNING_KEY_RECOVERY_OPTIONS,
                )
                yield field_row(
                    "Signing sheet count",
                    "replace-signing-key-count-value",
                    WorkspaceAction("workspace-replace-signing-key-count", "Set sheets..."),
                )
                yield field_row(
                    "Key payload files",
                    "replace-signing-key-payloads-value",
                    WorkspaceAction(
                        "workspace-replace-signing-key-payloads",
                        "Load key payloads...",
                    ),
                )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        source = group(presentation, "source")
        update_status_note(self, "replace-source-status", source)
        update_table(self.query_one("#replace-source-table", DataTable), source)
        update_buttons(self, source.actions)
        unlock = group(presentation, "unlock")
        update_status_note(self, "replace-unlock-status", unlock)
        update_radio(self, "workspace-replace-unlock", unlock.choices)
        self.query_one("#replace-unlock-summary", Static).update(first_value(unlock))
        recovery = group(presentation, "recovery")
        update_status_note(self, "replace-recovery-status", recovery)
        update_radio(self, "workspace-replace-recovery", recovery.choices)
        self.query_one("#replace-recovery-summary", Static).update(first_value(recovery))
        self.query_one("#replace-passphrase-value", Static).update(
            value(recovery, "passphrase-recovery")
        )
        self.query_one("#replace-passphrase-count-value", Static).update(
            value(recovery, "passphrase-recovery")
        )
        set_select(
            self.query_one("#workspace-replace-passphrase-select", Select),
            replace_passphrase_recovery_select_value(value(recovery, "passphrase-recovery")),
        )
        output = group(presentation, "output")
        update_status_note(self, "replace-output-status", output)
        self.query_one("#replace-output-value", Static).update(value(output, "output"))
        self.query_one("#replace-safety-value", Static).update(value(output, "safety"))
        layout = group(presentation, "layout")
        update_status_note(self, "replace-layout-status", layout)
        set_select(self.query_one("#workspace-replace-paper", Select), value(layout, "paper"))
        set_select(self.query_one("#workspace-replace-design", Select), value(layout, "design"))
        signing_key = group(presentation, "signing-key-recovery")
        update_status_note(self, "replace-signing-key-status", signing_key)
        set_select(
            self.query_one("#workspace-replace-signing-key-select", Select),
            selected_choice(signing_key.choices),
        )
        self.query_one("#replace-signing-key-count-value", Static).update(
            value(signing_key, "signing-key")
        )
        self.query_one("#replace-signing-key-payloads-value", Static).update(
            value(signing_key, "signing-key-payloads")
        )
