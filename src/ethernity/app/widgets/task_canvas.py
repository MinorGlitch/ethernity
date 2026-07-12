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
from textual.containers import HorizontalGroup, Vertical
from textual.widget import Widget
from textual.widgets import ProgressBar, Static

from ethernity.app.widgets.action_bar import TaskActionBar
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.workspaces.shell import TaskWorkspaces
from ethernity.tasks.models import TaskValidation
from ethernity.tasks.presentation.models import TaskPresentation
from ethernity.tasks.settings import SettingsTaskState


class TaskCanvas(Widget):
    """Structured task workspace for the main terminal app."""

    def compose(self) -> ComposeResult:
        with Vertical(id="task-canvas-shell"):
            with HorizontalGroup(id="canvas-hero"):
                with Vertical(id="canvas-heading"):
                    yield Static("", id="canvas-title")
                with Vertical(id="canvas-readiness"):
                    yield Static("", id="canvas-progress-label")
                    yield ProgressBar(
                        total=1,
                        show_eta=False,
                        show_percentage=False,
                        id="canvas-progress",
                    )
            with Vertical(id="canvas-task-workspaces"):
                yield TaskWorkspaces(id="task-workspaces")
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
    ) -> None:
        is_settings = task_key == "settings"
        self.query_one("#task-canvas-shell", Vertical).set_class(is_settings, "settings-mode")
        self.query_one("#canvas-hero", HorizontalGroup).display = not is_settings
        self.query_one("#canvas-hero", HorizontalGroup).set_class(is_settings, "settings-mode")
        action_bar = self.query_one(TaskActionBar)
        action_bar.display = not is_settings or running
        action_bar.update_actions(
            primary_label=presentation.primary_action.label,
            primary_enabled=presentation.primary_action.enabled,
            compact=is_settings,
            internals_visible=internals_visible and presentation.diagnostics_available,
            running=running,
            running_label=running_label,
        )
        _update_static(self.query_one("#canvas-title", Static), "" if is_settings else title)
        self.query_one("#canvas-task-workspaces", Vertical).display = not is_settings
        self.query_one("#canvas-settings-workspace", Vertical).display = is_settings
        self.query_one("#canvas-readiness", Vertical).display = not is_settings
        settings_form = self.query_one(SettingsForm)
        settings_form.disabled = running
        self._settings_write_locked = running

        progress_label = presentation.readiness_label
        progress_total = presentation.total_count
        progress_value = presentation.ready_count
        if presentation.workflow is not None:
            progress_label = presentation.workflow.progress_label
            progress_total = len(presentation.workflow.steps)
            progress_value = presentation.workflow.active_step_number
        _update_static(self.query_one("#canvas-progress-label", Static), progress_label)
        self.query_one("#canvas-progress", ProgressBar).update(
            total=progress_total,
            progress=progress_value,
        )
        if not is_settings:
            self.query_one(TaskWorkspaces).update_presentation(presentation)
        if is_settings:
            self.query_one(SettingsForm).update_statuses(validation)

    def update_settings_values(self, settings: SettingsTaskState) -> None:
        self.query_one(SettingsForm).update_values(
            settings,
            write_locked=getattr(self, "_settings_write_locked", False),
        )


def _update_static(static: Static, content: str) -> None:
    if str(static.content) != content:
        static.update(content)
