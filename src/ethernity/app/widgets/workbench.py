"""Step navigation and redacted summaries for the terminal workbench."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import VerticalGroup, VerticalScroll
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static

from ethernity.app.widgets.static_text import update_static_text
from ethernity.tasks.presentation.models import TaskPresentation, WorkspaceValue


@dataclass(frozen=True, slots=True)
class WorkbenchStep:
    key: str
    label: str
    summary: str = ""
    severity: str = "none"


def workbench_steps(presentation: TaskPresentation) -> tuple[WorkbenchStep, ...]:
    """Use task presentations for step status; navigation owns no validation rules."""
    if presentation.workflow is not None:
        steps = tuple(
            WorkbenchStep(
                step.key,
                {
                    "source": "Source",
                    "recovery": "Recovery",
                    "target": "Version",
                    "destination": "Save to",
                    "output": "Print setup",
                }.get(step.key, step.title),
                step.summary,
                step.severity,
            )
            for step in presentation.workflow.steps
            if step.visible
        )
    elif presentation.task_key == "backup":
        groups = {group.key: group for group in presentation.workspace_groups}
        steps = tuple(
            WorkbenchStep(key, label, groups[group_key].status_summary)
            for key, label, group_key in (
                ("files", "Files", "files"),
                ("recovery", "Recovery", "recovery"),
                ("print", "Print setup", "destination"),
            )
        )
    elif presentation.task_key == "kit":
        steps = (WorkbenchStep("kit", "Kit setup"),)
    else:
        return ()
    return (*steps, WorkbenchStep("review", "Review"))


class WorkbenchSteps(Widget):
    """A vertical rail that becomes a horizontal strip in small terminals."""

    class Selected(Message):
        def __init__(self, key: str) -> None:
            super().__init__()
            self.key = key

    def __init__(
        self, *, id: str | None = None, title: str = "WORKFLOW", numbered: bool = True
    ) -> None:
        super().__init__(id=id)
        self._title = title
        self._numbered = numbered
        self._steps: tuple[WorkbenchStep, ...] = ()

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="workbench-step-title", markup=False)
        # The workflow registry bounds the number of decisions. Unused slots stay hidden.
        for index in range(8):
            yield Button(
                "",
                id=f"workbench-step-{index}",
            )

    def sync(self, steps: tuple[WorkbenchStep, ...], active: str, *, locked: bool) -> None:
        if len(steps) > 8:
            raise ValueError("workbench supports at most eight visible steps")
        self._steps = steps
        for index, button in enumerate(self.query(Button)):
            button.display = index < len(steps)
            if index >= len(steps):
                continue
            step = steps[index]
            label = f"{index + 1:02} {step.label}" if self._numbered else step.label
            button.label = Content.from_text(label, markup=False)
            button.tooltip = step.summary or step.label
            became_active = step.key == active and not button.has_class("active-step")
            button.set_class(step.key == active, "active-step")
            button.set_class(step.severity == "error", "step-error")
            button.set_class(step.severity == "warning", "step-warning")
            button.disabled = locked
            if became_active:
                self.call_after_refresh(button.scroll_visible, animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        index = list(self.query(Button)).index(event.button)
        if index < len(self._steps):
            self.post_message(self.Selected(self._steps[index].key))

    def button_for(self, key: str) -> Button:
        index = next(index for index, step in enumerate(self._steps) if step.key == key)
        return self.query_one(f"#workbench-step-{index}", Button)


class WorkbenchSummary(VerticalScroll):
    """Render only the safe display values supplied by the presentation layer."""

    def compose(self) -> ComposeResult:
        yield Static("SUMMARY", id="workbench-summary-title", markup=False)
        for index in range(8):
            with VerticalGroup(
                id=f"workbench-summary-row-{index}", classes="workbench-summary-row"
            ):
                yield Static("", classes="workbench-summary-label", markup=False)
                yield Static("", classes="workbench-summary-value", markup=False)

    def sync(self, presentation: TaskPresentation, *, active_step: str) -> None:
        items = _summary_items(presentation, active_step=active_step)
        self.set_class(not items, "empty-summary")
        for index in range(8):
            row = self.query_one(f"#workbench-summary-row-{index}")
            row.display = index < len(items)
            if index >= len(items):
                continue
            item = items[index]
            update_static_text(row.query_one(".workbench-summary-label", Static), item.label)
            value = row.query_one(".workbench-summary-value", Static)
            update_static_text(value, item.value or "Not selected")
            value.tooltip = item.value


def _summary_items(
    presentation: TaskPresentation, *, active_step: str
) -> tuple[WorkspaceValue, ...]:
    """Show completed decisions from earlier steps, never duplicate the active editor."""
    if presentation.workflow is not None:
        previous = []
        for step in presentation.workflow.steps:
            if step.key == active_step:
                break
            if step.visible and step.state == "complete":
                previous.append(WorkspaceValue(step.key, step.title, step.summary))
        return tuple(previous)
    if presentation.task_key == "backup" and active_step != "files":
        groups = {group.key: group for group in presentation.workspace_groups}
        items = []
        if groups["files"].values:
            items.append(WorkspaceValue("files", "Files", groups["files"].status_summary))
        if active_step == "print":
            items.append(WorkspaceValue("recovery", "Recovery", groups["recovery"].status_summary))
        return tuple(items)
    return ()
