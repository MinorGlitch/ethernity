from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Static

from ethernity.app.workspaces.common import (
    BaseWorkspace,
    group,
    group_label,
    section,
    status_label,
)
from ethernity.tasks.presentation.models import TaskPresentation


class DoctorWorkspace(BaseWorkspace):
    task_key = "doctor"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Setup checks")
                yield DataTable(
                    id="doctor-checks-table", classes="workspace-table workspace-control"
                )
                yield Static("", id="doctor-check-detail", classes="workspace-field-note")

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        checks = group(presentation, "checks")
        table = self.query_one("#doctor-checks-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        table.add_columns("Check", "Status", "Detail")
        for value in checks.values:
            table.add_row(value.label, status_label(value.status), value.value, key=value.key)
        self.query_one("#doctor-check-detail", Static).update(
            checks.values[0].value if checks.values else ""
        )
