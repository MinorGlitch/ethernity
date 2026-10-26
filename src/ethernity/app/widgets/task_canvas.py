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

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Static

from ethernity.app.widgets.action_bar import TaskActionBar
from ethernity.app.widgets.review_task import TaskReview
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.task_progress import TaskProgress
from ethernity.app.widgets.task_result import TaskResult
from ethernity.app.widgets.workbench import WorkbenchSteps, workbench_steps
from ethernity.app.widgets.workflow.controls import InlineNotice
from ethernity.app.workflow_registry import workflow_definition
from ethernity.app.workspaces.shell import TaskWorkspaces
from ethernity.app.workspaces.workspace_controls import BaseWorkspace
from ethernity.tasks.models import TaskValidation
from ethernity.tasks.presentation.models import InlineNoticePresentation, TaskPresentation
from ethernity.tasks.settings import SettingsTaskState
from ethernity.tasks.task_types import TaskKey


class TaskCanvas(Widget):
    """Workbench with step navigation and a focused editor."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._presentation: TaskPresentation | None = None
        self._local_steps = {"backup": "files", "kit": "kit"}
        self._issue: tuple[str, str, str] | None = None
        self.document: TaskReview | TaskProgress | TaskResult | None = None

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
                    yield Vertical(id="canvas-settings-workspace")
                    yield TaskActionBar(id="task-action-bar")
                    yield Vertical(id="workbench-document")

    def present_document(self, document: TaskReview | TaskProgress | TaskResult) -> None:
        """Select the live view immediately; mount it on this widget's message queue."""
        if self.document is not None:
            self.document.display = False
        self.document = document
        self._sync_document_layout()
        self.call_later(self._mount_document, document)

    async def close_document(self) -> None:
        if self.document is not None:
            self.document.display = False
        self.document = None
        closed = asyncio.Event()
        if self.call_later(self._mount_document, None, closed):
            await closed.wait()
        self._sync_document_layout()

    def action_back(self) -> None:
        """Escape also works when focus has moved to the top navigation."""
        if isinstance(self.document, TaskReview):
            self.document.action_cancel()
        elif isinstance(self.document, TaskProgress):
            self.document.action_request_cancel()
        elif isinstance(self.document, TaskResult):
            self.document.action_close()

    async def _mount_document(
        self,
        document: TaskReview | TaskProgress | TaskResult | None,
        completed: asyncio.Event | None = None,
    ) -> None:
        # Progress may finish before its view mounts. Only the latest state may
        # take focus. All mount/removal work uses this widget's queue so leaving
        # review cannot prune a view while its children are still mounting.
        try:
            if self.document is not document:
                return
            host = self.query_one("#workbench-document")
            await host.remove_children()
            if document is not None and self.document is document:
                await host.mount(document)
                if self.document is document and not self.screen.disabled:
                    document.focus_default()
        finally:
            if completed is not None:
                completed.set()

    def _sync_document_layout(self) -> None:
        is_settings = self._presentation is not None and self._presentation.task_key == "settings"
        editing = self.document is None
        self.query_one("#workbench-document").display = not editing
        self.query_one("#canvas-hero").display = editing and not is_settings
        self.query_one("#canvas-task-workspaces").display = editing and not is_settings
        self.query_one("#canvas-settings-workspace").display = editing and is_settings
        self.query_one(TaskActionBar).display = editing and not is_settings
        if self._presentation is not None and not is_settings:
            self.query_one(WorkbenchSteps).sync(
                workbench_steps(self._presentation),
                "review" if not editing else self.active_step,
                locked=isinstance(self.document, TaskProgress),
            )

    async def prepare_task(self, task: TaskKey) -> None:
        """Finish mounting controls before applying state or moving focus."""
        if task == "settings":
            if not self.query(SettingsForm):
                await self.query_one("#canvas-settings-workspace").mount(
                    SettingsForm(id="settings-form-widget")
                )
        else:
            await self.query_one(TaskWorkspaces).prepare(task)

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
        # Padding affects only the editor, so avoid restyling every descendant form.
        self.query_one("#workbench-editor").styles.padding = 0 if is_settings else None
        self.query_one("#workbench-steps").set_class(is_settings, "settings-mode")
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
        for settings_form in self.query(SettingsForm):
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
            self.query_one("#canvas-back", Button).disabled = (
                locked or self.adjacent_step(-1) is None
            )
        if is_settings:
            self.query_one(SettingsForm).update_statuses(validation)
        if self.document is not None:
            self._sync_document_layout()
        else:
            self.query_one("#workbench-document").display = False

    def update_settings_values(self, settings: SettingsTaskState) -> None:
        self.query_one(SettingsForm).update_values(
            settings,
            write_locked=getattr(self, "_settings_write_locked", False),
        )
