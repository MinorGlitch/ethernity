from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Select, Static

from ethernity.app.workspaces.common import (
    DESIGN_OPTIONS,
    KIT_VARIANTS,
    PAPER_OPTIONS,
    BaseWorkspace,
    field_row,
    first_value,
    group,
    group_label,
    section,
    select_row,
    set_select,
    status_note,
    update_status_note,
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class KitWorkspace(BaseWorkspace):
    task_key = "kit"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Kit type")
                yield status_note("kit-variant-status")
                yield select_row("Kit type", "workspace-kit-variant-select", KIT_VARIANTS)
            with section():
                yield group_label("Save PDF as")
                yield status_note("kit-output-status")
                yield field_row(
                    "Save PDF as",
                    "kit-output-value",
                    WorkspaceAction("workspace-kit-output", "Choose PDF path..."),
                )
            with section():
                yield group_label("Print layout")
                yield status_note("kit-layout-status")
                yield select_row("Paper size", "workspace-kit-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-kit-design", DESIGN_OPTIONS)
            with section():
                yield group_label("QR sizing")
                yield status_note("kit-qr-status")
                yield field_row(
                    "QR sizing",
                    "kit-chunk-size-value",
                    WorkspaceAction("workspace-kit-chunk-size", "Set QR sizing..."),
                )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        variant = group(presentation, "variant")
        update_status_note(self, "kit-variant-status", variant)
        set_select(
            self.query_one("#workspace-kit-variant-select", Select),
            value(variant, "variant"),
        )
        output = group(presentation, "output")
        update_status_note(self, "kit-output-status", output)
        self.query_one("#kit-output-value", Static).update(first_value(output))
        layout = group(presentation, "layout")
        update_status_note(self, "kit-layout-status", layout)
        set_select(self.query_one("#workspace-kit-paper", Select), value(layout, "paper"))
        set_select(self.query_one("#workspace-kit-design", Select), value(layout, "design"))
        qr = group(presentation, "qr")
        update_status_note(self, "kit-qr-status", qr)
        self.query_one("#kit-chunk-size-value", Static).update(value(qr, "chunk-size"))
