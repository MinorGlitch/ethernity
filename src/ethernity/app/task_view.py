# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

from typing import Any, cast

from textual.widgets import OptionList
from textual.worker import Worker, WorkerState

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_types import ActiveTask, TaskState
from ethernity.app.navigation import blocker_focus_selector, workspace_focus_selector
from ethernity.app.screens.diagnostics import DiagnosticsScreen
from ethernity.app.screens.review_task import ReviewTaskScreen
from ethernity.app.task_catalog import (
    NAV_OPTION_INDEX,
    TASK_ORDER,
    TASK_TITLES,
    execute_label,
    review_label,
)
from ethernity.app.widgets.preview_panel import PreviewPanel
from ethernity.app.widgets.task_canvas import TaskCanvas
from ethernity.tasks.models import TaskDiagnostics, TaskExecutionResult
from ethernity.tasks.presentation.builder import build_task_presentation


class TaskViewActions(EthernityAppContext):
    """Navigation, refresh, review, diagnostics, and execution behavior."""

    async def action_review(self) -> None:
        if self.active_task == "settings":
            self.notify("Settings save automatically.")
            return
        validation = self._current_state().validate_task()
        if not validation.ready:
            self._focus_first_blocker()
            first_issue = next(
                (issue for issue in validation.issues if issue.severity == "error"),
                None,
            )
            if first_issue is not None:
                self.notify(first_issue.message, severity="warning")
            return
        await self.push_screen(
            ReviewTaskScreen(
                title=TASK_TITLES[self.active_task],
                validation=validation,
                preview=self._current_state().preview(),
                plan=self._current_state().execution_plan(),
                execute_label=execute_label(self.active_task),
            ),
            self._execute_after_review,
        )

    async def action_execute_current(self) -> None:
        await self.action_review()

    async def action_diagnostics(self) -> None:
        if not self._diagnostics_available():
            if self.active_task == "backup":
                self.notify("Choose backup files first.", severity="warning")
            else:
                self.notify(
                    "Backup internals are available while creating a backup.",
                    severity="warning",
                )
            return
        await self.push_screen(DiagnosticsScreen(self._current_diagnostics()))

    def action_show_backup(self) -> None:
        self._show_task("backup")

    def action_show_restore(self) -> None:
        self._show_task("restore")

    def action_show_add_files(self) -> None:
        self._show_task("add_files")

    def action_show_rebuild(self) -> None:
        self._show_task("rebuild")

    def action_show_replace_recovery_docs(self) -> None:
        self._show_task("replace_recovery_docs")

    def action_show_kit(self) -> None:
        self._show_task("kit")

    def action_show_doctor(self) -> None:
        self._show_task("doctor")

    def action_show_settings(self) -> None:
        self._show_task("settings")

    def action_nav_next(self) -> None:
        if self._move_focused_selection(1):
            return
        self._show_relative_task(1)

    def action_nav_previous(self) -> None:
        if self._move_focused_selection(-1):
            return
        self._show_relative_task(-1)

    def action_focus_nav(self) -> None:
        if self.active_task == "settings" and self.query_one("#settings-form").has_focus_within:
            self.query_one("#nav-list", OptionList).focus()
        else:
            self.query_one("#nav-list", OptionList).focus()

    def action_focus_workspace(self) -> None:
        if self.active_task == "settings":
            self.query_one("#setting-control-render_style").focus()
        else:
            self.query_one(workspace_focus_selector(self.active_task)).focus()

    def _focus_first_blocker(self) -> None:
        validation = self._current_state().validate_task()
        first_issue = next((issue for issue in validation.issues if issue.severity == "error"), None)
        self._focus_issue(first_issue.section if first_issue is not None else None)

    def _focus_issue_by_index(self, index: int) -> None:
        state = self._current_state()
        preview = state.preview()
        displayed_issues = (
            *[warning for warning in preview.warnings if warning.code != "FINAL_REVIEW_REQUIRED"],
            *state.validate_task().issues,
        )
        if index < 0 or index >= len(displayed_issues):
            return
        self._focus_issue(displayed_issues[index].section)

    def _focus_issue(self, section: str | None) -> None:
        selector = blocker_focus_selector(self.active_task, section)
        try:
            self.query_one(selector).focus()
        except Exception:
            self.query_one(workspace_focus_selector(self.active_task)).focus()

    def _move_focused_selection(self, direction: int) -> bool:
        focused = self.screen.focused
        if self.active_task == "settings" and focused is not self.query_one(
            "#nav-list", OptionList
        ):
            if direction > 0:
                self.screen.focus_next(".settings-control")
            else:
                self.screen.focus_previous(".settings-control")
            return True
        if (
            focused is not self.query_one("#nav-list", OptionList)
            and self.query_one("#task-workspaces").has_focus_within
        ):
            if direction > 0:
                self.screen.focus_next(".workspace-control")
            else:
                self.screen.focus_previous(".workspace-control")
            return True
        if isinstance(focused, OptionList):
            if direction > 0:
                focused.action_cursor_down()
            else:
                focused.action_cursor_up()
            return True
        return False

    def refresh_task_view(self) -> None:
        state = self._current_state()
        validation = state.validate_task()
        preview = state.preview()
        diagnostics_available = self._diagnostics_available()
        presentation = build_task_presentation(
            task_key=self.active_task,
            title=TASK_TITLES[self.active_task],
            state=state,
            validation=validation,
            preview=preview,
            primary_label=review_label(self.active_task),
            diagnostics_available=diagnostics_available,
        )
        self._refresh_navigation()
        self.query_one(TaskCanvas).update_task(
            task_key=self.active_task,
            title=TASK_TITLES[self.active_task],
            validation=validation,
            presentation=presentation,
            primary_label=review_label(self.active_task),
        )
        if self.active_task == "settings":
            self.query_one(TaskCanvas).update_settings_values(self.settings_state)
        self.query_one(PreviewPanel).update_preview(
            preview=preview,
            validation=validation,
            result=self._last_execution_result,
            diagnostics_available=diagnostics_available,
        )

    def _refresh_navigation(self) -> None:
        nav = self.query_one("#nav-list", OptionList)
        nav.highlighted = NAV_OPTION_INDEX[self.active_task]

    def _show_task(self, task: ActiveTask) -> None:
        if task not in TASK_ORDER:
            return
        self.active_task = task
        self._last_execution_result = None
        self.refresh_task_view()

    def _show_relative_task(self, offset: int) -> None:
        current = TASK_ORDER.index(self.active_task)
        self._show_task(TASK_ORDER[(current + offset) % len(TASK_ORDER)])

    def _current_state(self) -> TaskState:
        if self.active_task == "restore":
            return self.restore_state
        if self.active_task == "add_files":
            return self.add_files_state
        if self.active_task == "rebuild":
            return self.rebuild_state
        if self.active_task == "replace_recovery_docs":
            return self.replace_recovery_docs_state
        if self.active_task == "kit":
            return self.kit_state
        if self.active_task == "doctor":
            return self.doctor_state
        if self.active_task == "settings":
            return self.settings_state
        return self.backup_state

    def _current_diagnostics(self) -> TaskDiagnostics:
        state = self._current_state()
        diagnostics = getattr(state, "diagnostics", None)
        if callable(diagnostics):
            return cast(TaskDiagnostics, diagnostics())
        return TaskDiagnostics()

    def _diagnostics_available(self) -> bool:
        state = self._current_state()
        available = getattr(state, "diagnostics_available", None)
        if callable(available):
            return bool(available())
        return False

    def _execute_after_review(self, confirmed: bool | None) -> None:
        if confirmed is not True:
            return
        state = self._current_state().model_copy(deep=True)
        self._last_execution_result = None
        self.notify(f"Running {TASK_TITLES[self.active_task].lower()}...")
        cast(Any, self).run_worker(
            state.execute,
            name=self.active_task,
            group="task-execution",
            exit_on_error=False,
            exclusive=True,
            thread=True,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != "task-execution":
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, TaskExecutionResult):
                self._last_execution_result = result
                self.notify(result.message)
                self.refresh_task_view()
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            self.notify(str(error) if error is not None else "Task failed.", severity="error")
