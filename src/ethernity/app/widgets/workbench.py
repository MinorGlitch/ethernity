"""Step navigation and redacted summaries for the terminal workbench."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.content import Content
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static

from ethernity.app.widgets.static_text import update_static_text
from ethernity.tasks.presentation.models import TaskPresentation


@dataclass(frozen=True, slots=True)
class WorkbenchStep:
    key: str
    label: str
    summary: str = ""
    severity: str = "none"
    complete: bool = False


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
                step.state == "complete",
            )
            for step in presentation.workflow.steps
            if step.visible
        )
    elif presentation.task_key == "backup":
        groups = {group.key: group for group in presentation.workspace_groups}
        steps = tuple(
            WorkbenchStep(
                key,
                label,
                groups[group_key].status_summary,
                complete=groups[group_key].status in {"ready", "warning"},
            )
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

    def __init__(self, *, id: str | None = None, title: str = "", numbered: bool = True) -> None:
        super().__init__(id=id)
        self._title = title
        self._numbered = numbered
        self._steps: tuple[WorkbenchStep, ...] = ()

    def compose(self) -> ComposeResult:
        if self._title:
            yield Static(self._title, id="workbench-step-title", markup=False)
        # The workflow registry bounds the number of decisions. Unused slots stay hidden.
        for index in range(8):
            with VerticalGroup(classes="workbench-step"):
                yield Button("", id=f"workbench-step-{index}")
                yield Static("", classes="workbench-step-summary", markup=False)

    def sync(self, steps: tuple[WorkbenchStep, ...], active: str, *, locked: bool) -> None:
        if len(steps) > 8:
            raise ValueError("workbench supports at most eight visible steps")
        self._steps = steps
        active_index = next((index for index, step in enumerate(steps) if step.key == active), 0)
        for index, button in enumerate(self.query(Button)):
            row = button.parent
            assert row is not None
            row.display = index < len(steps)
            if index >= len(steps):
                continue
            step = steps[index]
            label = f"{index + 1:02} {step.label}" if self._numbered else step.label
            content = Content.from_text(label, markup=False)
            if button.label != content:
                button.label = content
                button.refresh(layout=True)
            button.tooltip = step.summary or step.label
            summary = row.query_one(".workbench-step-summary", Static)
            update_static_text(summary, step.summary)
            summary.tooltip = step.summary
            summary.set_class(
                index < active_index and step.complete and bool(step.summary), "completed"
            )
            became_active = step.key == active and not button.has_class("active-step")
            button.update_classes(
                {
                    "active-step": step.key == active,
                    "step-error": step.severity == "error",
                    "step-warning": step.severity == "warning",
                }
            )
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
