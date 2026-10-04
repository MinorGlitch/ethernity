#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Static

from ethernity.app.widgets.action_bar import TaskActionBar
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.workbench import WorkbenchSteps, WorkbenchSummary, workbench_steps
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.workflow_registry import workflow_definition
from ethernity.app.workspaces.shell import TaskWorkspaces
from ethernity.app.workspaces.workspace_controls import BaseWorkspace
from ethernity.tasks.models import TaskValidation
from ethernity.tasks.presentation.models import InlineNoticePresentation, TaskPresentation
from ethernity.tasks.settings import SettingsTaskState


class TaskCanvas(Widget):
    """Workbench with step navigation, a focused editor, and a live summary."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._presentation: TaskPresentation | None = None
        self._local_steps = {"backup": "files", "kit": "kit"}
        self._issue: tuple[str, str, str] | None = None

    @property
    def active_step(self) -> str:
        presentation = self._presentation
        if presentation is None:
            return "files"
        if presentation.workflow is not None:
            return presentation.workflow.active_step
        return self._local_steps.get(presentation.task_key, "")

    def select_step(self, key: str) -> None:
        if self._presentation is not None:
            keys = {step.key for step in workbench_steps(self._presentation)}
            if key in keys and key != "review":
                self._local_steps[self._presentation.task_key] = key

    def adjacent_step(self, offset: int) -> str | None:
        if self._presentation is None:
            return None
        keys = [step.key for step in workbench_steps(self._presentation)]
        if self.active_step not in keys:
            return None
        index = keys.index(self.active_step) + offset
        return keys[index] if 0 <= index < len(keys) else None

    def show_issue(self, message: str) -> None:
        self._issue = (
            (self._presentation.task_key, self.active_step, message)
            if message and self._presentation is not None
            else None
        )
        workflow = self._presentation.workflow if self._presentation is not None else None
        if workflow is not None:
            active = next(step for step in workflow.steps if step.key == self.active_step)
            if active.issue is not None and active.issue.message == message:
                message = ""
        self.query_one("#canvas-step-issue", InlineNotice).sync_presentation(
            InlineNoticePresentation(message, tone="error") if message else None
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="task-canvas-shell"):
            with Horizontal(id="workbench-body"):
                yield WorkbenchSteps(id="workbench-steps")
                with Vertical(id="workbench-editor"):
                    with Vertical(id="canvas-hero"):
                        yield Static("", id="canvas-title", markup=False)
                        yield InlineNotice(id="canvas-step-issue")
                    with Vertical(id="canvas-task-workspaces"):
                        yield TaskWorkspaces(id="task-workspaces")
                yield WorkbenchSummary(id="workbench-summary")
            with Vertical(id="canvas-settings-workspace"):
                yield SettingsForm(id="settings-form-widget")
            yield TaskActionBar(id="task-action-bar")

    def update_task(
        self,
        *,
        task_key: str,
        title: str,
        validation: TaskValidation,
        presentation: TaskPresentation,
        primary_label: str,
        internals_visible: bool,
        running: bool,
        running_label: str | None,
        preparing: bool = False,
    ) -> None:
        self._presentation = presentation
        issue = self._issue
        self.show_issue(
            issue[2]
            if issue is not None
            and issue[:2] == (task_key, self.active_step)
            and any(item.message == issue[2] for item in validation.issues)
            else ""
        )
        is_settings = task_key == "settings"
        locked = running or preparing
        self.query_one("#task-canvas-shell", Vertical).set_class(is_settings, "settings-mode")
        self.query_one("#workbench-body").display = not is_settings
        self.query_one("#canvas-hero").display = not is_settings
        action_bar = self.query_one(TaskActionBar)
        action_bar.display = not is_settings or running
        action_bar.update_actions(
            primary_label=(
                presentation.primary_action.label
                if preparing or self.adjacent_step(1) in {None, "review"}
                else "Continue >"
            ),
            primary_enabled=not locked,
            compact=is_settings,
            internals_visible=internals_visible and presentation.diagnostics_available,
            running=running,
            running_label=running_label,
        )
        heading = title
        if task_key == "backup":
            heading = {
                "files": "Choose files to back up",
                "recovery": "Choose how to recover your files",
                "print": "Set up your printed backup",
            }[self.active_step]
        update_static_text(self.query_one("#canvas-title", Static), "" if is_settings else heading)
        self.query_one("#canvas-task-workspaces", Vertical).display = not is_settings
        self.query_one("#canvas-settings-workspace", Vertical).display = is_settings
        settings_form = self.query_one(SettingsForm)
        settings_form.disabled = running
        self._settings_write_locked = running

        if not is_settings:
            self.query_one(TaskWorkspaces).update_presentation(presentation)
            definition = workflow_definition(presentation.task_key)
            if definition.workspace_id is not None:
                self.query_one(f"#{definition.workspace_id}", BaseWorkspace).show_step(
                    self.active_step
                )
            steps = workbench_steps(presentation)
            self.query_one(WorkbenchSteps).sync(steps, self.active_step, locked=locked)
            self.query_one(WorkbenchSummary).sync(presentation, active_step=self.active_step)
            self.query_one("#canvas-back", Button).disabled = (
                locked or self.adjacent_step(-1) is None
            )
            current = next(
                index for index, step in enumerate(steps, 1) if step.key == self.active_step
            )
            update_static_text(
                self.query_one("#canvas-progress", Static), f"Step {current} of {len(steps)}"
            )
        if is_settings:
            self.query_one(SettingsForm).update_statuses(validation)

    def update_settings_values(self, settings: SettingsTaskState) -> None:
        self.query_one(SettingsForm).update_values(
            settings,
            write_locked=getattr(self, "_settings_write_locked", False),
        )
