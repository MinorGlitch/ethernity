from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll
from textual.widgets import Button, DataTable, RadioButton, RadioSet, Select, Static

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
    status_note,
    update_buttons,
    update_radio,
    update_status_note,
    update_table,
    value,
    value_row,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction, WorkspaceGroup


class RebuildWorkspace(BaseWorkspace):
    task_key = "rebuild"
    _advanced_row_ids = (
        "rebuild-advanced-auth-row",
        "rebuild-advanced-qr-row",
    )

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Existing backup")
                yield status_note("rebuild-source-status")
                yield path_table("rebuild-source-table")
                yield button_row(
                    WorkspaceAction("workspace-rebuild-source", "Choose backup folder..."),
                )
            with section():
                yield group_label("Rebuild options")
                yield status_note("rebuild-options-status")
                yield value_row("Version included", "rebuild-freshness-value")
                yield value_row("Safety", "rebuild-safety-value")
                yield button_row(
                    WorkspaceAction("workspace-rebuild-freshness", "Use this backup"),
                    WorkspaceAction("workspace-rebuild-fingerprint", "Show fingerprint..."),
                )
            with section():
                yield group_label("Unlock backup")
                yield status_note("rebuild-unlock-status")
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
                yield button_row(
                    WorkspaceAction("workspace-rebuild-unlock", "Set unlock method...")
                )
            with section():
                yield group_label("Save rebuilt backup documents to")
                yield status_note("rebuild-output-status")
                yield field_row(
                    "Save documents to",
                    "rebuild-output-value",
                    WorkspaceAction("workspace-rebuild-output", "Choose output folder..."),
                )
            with section():
                yield group_label("Print options")
                yield status_note("rebuild-layout-status")
                yield select_row("Paper size", "workspace-rebuild-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-rebuild-design", DESIGN_OPTIONS)
            with section():
                yield group_label("Advanced")
                yield status_note("rebuild-advanced-status")
                with HorizontalGroup(
                    id="rebuild-advanced-summary-row",
                    classes="workspace-field-row",
                ):
                    yield Static(
                        "Advanced: using saved defaults",
                        id="rebuild-advanced-summary",
                        classes="workspace-field-value",
                    )
                    yield Button(
                        "Show advanced",
                        id="rebuild-advanced-toggle",
                        compact=True,
                        classes="workspace-control",
                    )
                yield labeled_select_row(
                    "Trust source",
                    "workspace-rebuild-auth-material",
                    AUTH_MATERIAL_OPTIONS,
                    row_id="rebuild-advanced-auth-row",
                )
                yield field_row(
                    "QR density",
                    "rebuild-qr-chunk-size-value",
                    WorkspaceAction("workspace-rebuild-qr-chunk-size", "Set QR density..."),
                    row_id="rebuild-advanced-qr-row",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "rebuild-advanced-toggle":
            return
        event.stop()
        self._advanced_expanded = not getattr(self, "_advanced_expanded", False)
        self._sync_advanced_visibility()

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        source = group(presentation, "source")
        update_status_note(self, "rebuild-source-status", source)
        update_table(self.query_one("#rebuild-source-table", DataTable), source)
        update_buttons(self, source.actions)
        unlock = group(presentation, "unlock")
        update_status_note(self, "rebuild-unlock-status", unlock)
        update_radio(self, "workspace-rebuild-unlock", unlock.choices)
        self.query_one("#rebuild-unlock-summary", Static).update(first_value(unlock))
        options = group(presentation, "options")
        update_status_note(self, "rebuild-options-status", options)
        self.query_one("#rebuild-freshness-value", Static).update(value(options, "freshness"))
        self.query_one("#rebuild-safety-value", Static).update(value(options, "safety"))
        output = group(presentation, "output")
        update_status_note(self, "rebuild-output-status", output)
        self.query_one("#rebuild-output-value", Static).update(value(output, "output"))
        layout = group(presentation, "layout")
        update_status_note(self, "rebuild-layout-status", layout)
        set_select(self.query_one("#workspace-rebuild-paper", Select), value(layout, "paper"))
        set_select(self.query_one("#workspace-rebuild-design", Select), value(layout, "design"))
        advanced = group(presentation, "advanced")
        update_status_note(self, "rebuild-advanced-status", advanced)
        set_select(
            self.query_one("#workspace-rebuild-auth-material", Select),
            auth_material_select_value(value(advanced, "auth-material")),
        )
        self.query_one("#rebuild-qr-chunk-size-value", Static).update(
            value(advanced, "qr-chunk-size")
        )
        update_buttons(self, advanced.actions)
        self.query_one("#rebuild-advanced-summary", Static).update(
            _rebuild_advanced_summary(advanced)
        )
        self._sync_advanced_visibility()

    def _sync_advanced_visibility(self) -> None:
        expanded = getattr(self, "_advanced_expanded", False)
        for row_id in self._advanced_row_ids:
            self.query_one(f"#{row_id}").display = expanded
        self.query_one("#rebuild-advanced-toggle", Button).label = (
            "Hide advanced" if expanded else "Show advanced"
        )


def _rebuild_advanced_summary(advanced_group: WorkspaceGroup) -> str:
    return (
        "Advanced: using saved defaults | "
        f"Trust source: {value(advanced_group, 'auth-material')} | "
        f"QR density: {value(advanced_group, 'qr-chunk-size')}"
    )
