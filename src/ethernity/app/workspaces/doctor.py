from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.content import Content
from textual.widgets import OptionList
from textual.widgets.option_list import Option

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
                yield OptionList(
                    id="doctor-checks",
                    compact=True,
                    classes="workspace-control doctor-checklist",
                )

    def update_presentation(self, presentation: TaskPresentation) -> None:
        super().update_presentation(presentation)
        checks = group(presentation, "checks")
        self.query_one("#doctor-checks", OptionList).set_options(
            [
                Option(
                    Content.assemble(
                        (status_label(value.status), _status_style(value.status)),
                        " ",
                        (value.label, "bold"),
                        "\n",
                        (value.value, "dim"),
                    ),
                    id=value.key,
                )
                for value in checks.values
            ]
        )


def _status_style(status: str) -> str:
    if status == "ready":
        return "$text-success"
    if status == "warning":
        return "$text-warning"
    return "$text-error"
