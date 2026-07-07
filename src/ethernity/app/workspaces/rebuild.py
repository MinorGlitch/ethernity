from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, RadioButton, RadioSet, Select, Static

from ethernity.app.workspaces.common import (
    AUTH_MATERIAL_OPTIONS,
    DESIGN_OPTIONS,
    PAPER_OPTIONS,
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
    select_row,
    set_select,
    update_buttons,
    update_radio,
    update_table,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class RebuildWorkspace(BaseWorkspace):
    task_key = "rebuild"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Existing backup")
                yield path_table("rebuild-source-table")
                yield button_row(
                    WorkspaceAction("workspace-rebuild-source", "Choose backup folder..."),
                    WorkspaceAction("workspace-rebuild-freshness", "Use this backup"),
                    WorkspaceAction("workspace-rebuild-fingerprint", "Show fingerprint..."),
                )
            with section():
                yield group_label("Unlock backup")
                with RadioSet(
                    id="workspace-rebuild-unlock-method",
                    classes="workspace-control",
                    compact=True,
                ):
                    yield RadioButton(
                        "Enter passphrase",
                        id="workspace-rebuild-unlock-passphrase",
                    )
                    yield RadioButton(
                        "Use recovery sheets",
                        id="workspace-rebuild-unlock-recovery_documents",
                    )
                    yield RadioButton(
                        "Use recovery payload files",
                        id="workspace-rebuild-unlock-recovery_payloads",
                    )
                yield Static("", id="rebuild-unlock-summary", classes="workspace-field-note")
                yield button_row(WorkspaceAction("workspace-rebuild-unlock", "Set unlock method..."))
            with section():
                yield group_label("Signature check")
                yield labeled_select_row(
                    "Trust source",
                    "workspace-rebuild-auth-material",
                    AUTH_MATERIAL_OPTIONS,
                )
            with section():
                yield group_label("Save rebuilt backup documents to")
                yield field_row(
                    "Save documents to",
                    "rebuild-output-value",
                    WorkspaceAction("workspace-rebuild-output", "Choose output folder..."),
                )
                yield Static("", id="rebuild-freshness-value", classes="workspace-field-note")
                yield field_row(
                    "QR density",
                    "rebuild-qr-chunk-size-value",
                    WorkspaceAction("workspace-rebuild-qr-chunk-size", "Set QR density..."),
                )
                yield select_row("Paper size", "workspace-rebuild-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-rebuild-design", DESIGN_OPTIONS)

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        source = group(presentation, "source")
        update_table(self.query_one("#rebuild-source-table", DataTable), source)
        update_buttons(self, source.actions)
        unlock = group(presentation, "unlock")
        update_radio(self, "workspace-rebuild-unlock", unlock.choices)
        self.query_one("#rebuild-unlock-summary", Static).update(first_value(unlock))
        output = group(presentation, "output")
        self.query_one("#rebuild-output-value", Static).update(value(output, "output"))
        self.query_one("#rebuild-freshness-value", Static).update(value(output, "freshness"))
        self.query_one("#rebuild-qr-chunk-size-value", Static).update(
            value(output, "qr-chunk-size")
        )
        set_select(
            self.query_one("#workspace-rebuild-auth-material", Select),
            auth_material_select_value(value(output, "auth-material")),
        )
        set_select(self.query_one("#workspace-rebuild-paper", Select), value(output, "paper"))
        set_select(self.query_one("#workspace-rebuild-design", Select), value(output, "design"))
