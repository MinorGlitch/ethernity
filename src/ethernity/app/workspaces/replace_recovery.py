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
    update_buttons,
    update_radio,
    update_table,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class ReplaceRecoveryWorkspace(BaseWorkspace):
    task_key = "replace_recovery_docs"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Existing backup")
                yield path_table("replace-source-table")
                yield button_row(
                    WorkspaceAction("workspace-replace-source", "Load scanned pages..."),
                    WorkspaceAction("workspace-replace-recovery-text", "Paste recovery text..."),
                    WorkspaceAction("workspace-replace-payloads", "Load payload files..."),
                )
                yield button_row(
                    WorkspaceAction("workspace-replace-freshness", "Use this backup"),
                    WorkspaceAction("workspace-replace-fingerprint", "Show fingerprint..."),
                )
            with section():
                yield group_label("Unlock existing backup")
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
                yield labeled_select_row(
                    "Signature",
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
                    WorkspaceAction("workspace-replace-signing-key-payloads", "Load key payloads..."),
                )
            with section():
                yield group_label("Save replacement sheets to")
                yield field_row(
                    "Save documents to",
                    "replace-output-value",
                    WorkspaceAction("workspace-replace-output", "Choose output folder..."),
                )
                yield select_row("Paper size", "workspace-replace-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-replace-design", DESIGN_OPTIONS)

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        source = group(presentation, "source")
        update_table(self.query_one("#replace-source-table", DataTable), source)
        update_buttons(self, source.actions)
        unlock = group(presentation, "unlock")
        update_radio(self, "workspace-replace-unlock", unlock.choices)
        self.query_one("#replace-unlock-summary", Static).update(first_value(unlock))
        recovery = group(presentation, "recovery")
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
        signing_key = group(presentation, "signing-key-recovery")
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
        output = group(presentation, "output")
        self.query_one("#replace-output-value", Static).update(value(output, "output"))
        set_select(self.query_one("#workspace-replace-paper", Select), value(output, "paper"))
        set_select(self.query_one("#workspace-replace-design", Select), value(output, "design"))
