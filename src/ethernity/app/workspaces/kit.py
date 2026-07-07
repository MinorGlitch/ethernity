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
    value,
)
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceAction


class KitWorkspace(BaseWorkspace):
    task_key = "kit"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="task-workspace"):
            with section():
                yield group_label("Kit type")
                yield select_row("Kit type", "workspace-kit-variant-select", KIT_VARIANTS)
            with section():
                yield group_label("Print layout")
                yield select_row("Paper size", "workspace-kit-paper", PAPER_OPTIONS)
                yield select_row("Print design", "workspace-kit-design", DESIGN_OPTIONS)
                yield field_row(
                    "QR sizing",
                    "kit-chunk-size-value",
                    WorkspaceAction("workspace-kit-chunk-size", "Set QR sizing..."),
                )
            with section():
                yield group_label("Save PDF as")
                yield field_row(
                    "Save PDF as",
                    "kit-output-value",
                    WorkspaceAction("workspace-kit-output", "Choose PDF path..."),
                )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        print_group = group(presentation, "print")
        set_select(
            self.query_one("#workspace-kit-variant-select", Select),
            value(print_group, "variant"),
        )
        set_select(self.query_one("#workspace-kit-paper", Select), value(print_group, "paper"))
        set_select(self.query_one("#workspace-kit-design", Select), value(print_group, "design"))
        self.query_one("#kit-chunk-size-value", Static).update(value(print_group, "chunk-size"))
        self.query_one("#kit-output-value", Static).update(
            first_value(group(presentation, "output"))
        )
