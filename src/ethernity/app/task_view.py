# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from dataclasses import replace
from typing import cast

from textual.widgets import Button, Collapsible, Label, ListView
from textual.worker import Worker

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_types import UnlockTaskState
from ethernity.app.backup_context import BACKUP_TASKS, LoadedBackupContext
from ethernity.app.desktop_session import DesktopDriver
from ethernity.app.execution import (
    ExecutionOutcome,
    ReviewedTask,
    execution_failure_section,
)
from ethernity.app.navigation import (
    DIRECT_NAV_TASKS,
    MANAGE_TASKS,
    NavTaskState,
    app_version_label,
    blocker_focus_selector,
    issue_focus_selector,
    run_directional_widget_binding,
    sync_nav_active,
    workspace_focus_selector,
)
from ethernity.app.operation_progress import OperationProgress
from ethernity.app.screens.diagnostics import DiagnosticsScreen
from ethernity.app.task_catalog import (
    TASK_ORDER,
    TASK_TITLES,
    execute_label,
    review_label,
)
from ethernity.app.widgets.form import FormScroll
from ethernity.app.widgets.review_task import ReviewEditRequest, TaskReview
from ethernity.app.widgets.settings_form import SettingsForm
from ethernity.app.widgets.static_text import update_static_text
from ethernity.app.widgets.task_canvas import TaskCanvas
from ethernity.app.widgets.task_progress import TaskProgress
from ethernity.app.widgets.task_result import TaskResult
from ethernity.app.widgets.workflow.steps import WorkflowStepStack
from ethernity.app.workflow_presenter import (
    is_guided_task,
    step_for_section,
)
from ethernity.app.workflow_registry import build_guided_workflow, workflow_definition
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.app.workspaces.workspace_controls import BaseWorkspace
from ethernity.tasks.models import TaskDiagnostics, TaskIssue, TaskValidation
from ethernity.tasks.presentation.builder import build_task_presentation
from ethernity.tasks.source_assessment import SourceAssessableTaskState
from ethernity.tasks.task_types import TaskKey, TaskState

_TASK_ACTIVITY_LABELS: dict[TaskKey, str] = {
    "backup": "backup",
    "restore": "restore",
    "add_files": "backup update",
    "rebuild": "backup rebuild",
    "replace_recovery_docs": "recovery-sheet replacement",
    "kit": "offline recovery kit",
    "settings": "settings save",
}
_REVIEW_TITLES: dict[TaskKey, str] = {
    "backup": "Review backup",
    "restore": "Review file restore",
    "add_files": "Review backup update",
    "rebuild": "Review backup rebuild",
    "replace_recovery_docs": "Review replacement sheets",
    "kit": "Review offline recovery kit",
    "settings": "Review settings",
}
_RUNNING_LABELS: dict[TaskKey, str] = {
    "backup": "Backup in progress",
    "restore": "Restore in progress",
    "add_files": "Update in progress",
    "rebuild": "Rebuild in progress",
    "replace_recovery_docs": "Replacement in progress",
    "kit": "Kit in progress",
    "settings": "Save in progress",
}


def _return_step_for_section(task: TaskKey, section: str) -> str | None:
    if task == "replace_recovery_docs" and section == "signature":
        # Signing-key recovery is auxiliary to the nearest guided recovery decision.
        return "recovery"
    return step_for_section(task, section)


class TaskViewActions(EthernityAppContext):
    """Navigation, refresh, review, diagnostics, and execution behavior."""

    async def action_primary(self) -> None:
        self._commit_form_inputs()
        canvas = self.query_one(TaskCanvas)
        ui_state = self.workflow_ui_states.get(self.active_task)
        if ui_state is not None and ui_state.has_invalid_draft(canvas.active_step):
            canvas.show_issue(ui_state.draft_error(canvas.active_step) or "Check this step.")
            self.call_after_refresh(
                self._focus_guided_step_input, self.active_task, canvas.active_step
            )
            return
        for issue in self._current_state().validate_task().issues:
            if issue.severity != "error":
                continue
            section_step = step_for_section(self.active_task, issue.section)
            workspace_id = workflow_definition(self.active_task).workspace_id
            if workspace_id is not None:
                workspace = self.query_one(f"#{workspace_id}", BaseWorkspace)
                section_step = (
                    workspace.step_for_target(issue_focus_selector(self.active_task, issue))
                    or section_step
                )
            if section_step == canvas.active_step:
                ui_state = self.workflow_ui_states.get(self.active_task)
                if ui_state is not None:
                    ui_state.touch(canvas.active_step)
                self.refresh_task_view()
                canvas.show_issue(issue.message)
                self.call_after_refresh(self._focus_issue, issue)
                return
        next_step = canvas.adjacent_step(1)
        await self._select_workbench_step(next_step or "review")

    async def _select_workbench_step(self, key: str) -> None:
        if self.running_task is not None or self._preparing_review_task is not None:
            return
        self._commit_form_inputs()
        if key == "review":
            await self.action_review()
            return
        await self._close_task_document()
        ui_state = self.workflow_ui_states.get(self.active_task)
        if ui_state is not None:
            if key not in ui_state.step_keys:
                return
            ui_state.activate(key)
        else:
            self.query_one(TaskCanvas).select_step(key)
        self.refresh_task_view()
        self.call_after_refresh(self._focus_active_task, self.active_task)

    async def action_review(self) -> None:
        if self._desktop_shutdown_requested:
            return
        self._review_edit_task = None
        if self.screen is not self.screen_stack[0]:
            self.notify("Close the current dialog before reviewing.", severity="warning")
            return
        self._commit_form_inputs()
        if self._review_busy():
            return
        await self._close_task_document()
        if self.active_task == "settings":
            self.notify("Settings save automatically.")
            return

        task = self.active_task
        state = self._current_state()
        ui_state = self.workflow_ui_states.get(task)
        if ui_state is not None and ui_state.has_invalid_draft():
            self._focus_invalid_review_draft(task, ui_state)
            return
        self._preparing_review_task = task
        self.refresh_task_view()
        capture = await self._prepare_review_capture(task, state, ui_state)
        if capture is None:
            return
        validation, reviewed_task = capture
        assert validation is not None
        if not validation.ready:
            self._focus_review_problems(task, validation)
            return
        assert reviewed_task is not None
        await self._present_execution_review(reviewed_task)

    async def _prepare_review_capture(
        self, task: TaskKey, state: TaskState, ui_state: WorkflowUiState | None
    ) -> tuple[TaskValidation, ReviewedTask | None] | None:
        validation = None
        reviewed_task = None
        preparation_error: OSError | RuntimeError | ValueError | None = None
        try:
            if ui_state is not None and ui_state.is_touched("source"):
                await self.source_assessment_controller.ensure_current(task)
            prepare_review = getattr(state, "prepare_review", None)
            if callable(prepare_review):
                await asyncio.to_thread(prepare_review, force=True)
            validation = state.validate_task()
            if validation.ready:
                reviewed_task = await asyncio.to_thread(ReviewedTask.capture, task, state)
        except (OSError, RuntimeError, ValueError) as error:
            preparation_error = error
        finally:
            self._preparing_review_task = None
            if self._desktop_shutdown_requested:
                self._finish_desktop_shutdown()
            else:
                self.refresh_task_view()

        if self._desktop_shutdown_requested:
            return
        if preparation_error is not None:
            self.notify(
                f"Ethernity could not prepare the review: {preparation_error}",
                severity="error",
            )
            return
        return (validation, reviewed_task) if validation is not None else None

    def _focus_invalid_review_draft(self, task: TaskKey, ui_state: WorkflowUiState) -> None:
        invalid_step = next(
            step_key for step_key in ui_state.step_keys if ui_state.has_invalid_draft(step_key)
        )
        ui_state.activate(invalid_step)
        ui_state.touch(invalid_step)
        ui_state.mark_review_attempted()
        self.refresh_task_view()
        self.call_after_refresh(self._focus_guided_step_input, task, invalid_step)
        return

    def _review_busy(self) -> bool:
        if self.running_task is not None:
            task_label = _TASK_ACTIVITY_LABELS[self.running_task]
            self.notify(f"The {task_label} task is still running.")
            return True
        preparing_task = self._preparing_review_task
        if preparing_task is not None:
            task_label = _TASK_ACTIVITY_LABELS[preparing_task]
            self.notify(f"Ethernity is preparing the {task_label} review.")
            return True
        return False

    def _focus_review_problems(self, task: TaskKey, validation: TaskValidation) -> None:
        first_issue = next(
            (issue for issue in validation.issues if issue.severity == "error"),
            None,
        )
        if is_guided_task(task):
            ui_state = self.workflow_ui_states[task]
            ui_state.mark_review_attempted()
            if first_issue is not None:
                step_key = step_for_section(task, first_issue.section)
                if step_key is not None:
                    ui_state.activate(step_key)
            self.refresh_task_view()
        self.call_after_refresh(self._focus_issue, first_issue)
        if first_issue is not None and not is_guided_task(task):
            self.notify(first_issue.message, severity="warning")
        return

    async def _present_execution_review(self, reviewed_task: ReviewedTask) -> None:
        self._close_nav_menu(restore_focus=False)
        self._last_reviewed_task = reviewed_task
        self.query_one(TaskCanvas).present_document(
            TaskReview(
                title=_REVIEW_TITLES[reviewed_task.task],
                validation=reviewed_task.validation,
                preview=reviewed_task.preview,
                plan=reviewed_task.plan,
                execute_label=execute_label(reviewed_task.task),
                review_details=reviewed_task.review_details,
            )
        )

    async def on_task_review_decided(self, event: TaskReview.Decided) -> None:
        event.stop()
        canvas = self.query_one(TaskCanvas)
        if event.review is not canvas.document or self._desktop_shutdown_requested:
            return
        reviewed = self._last_reviewed_task
        await self._close_task_document()
        if reviewed is not None:
            self._execute_after_review(reviewed, event.decision)

    async def on_task_result_close_requested(self, event: TaskResult.CloseRequested) -> None:
        event.stop()
        if event.result is not self.query_one(TaskCanvas).document:
            return
        await self._close_task_document()
        if event.return_to_form:
            await self._return_to_workflow(event.task, event.issues, event.section)

    async def _close_task_document(self) -> None:
        canvas = self.query_one(TaskCanvas)
        document = canvas.document
        if document is None or isinstance(document, TaskProgress):
            return
        await canvas.close_document()
        if (
            isinstance(document, TaskResult)
            and document.task_key == "backup"
            and self.active_task == "backup"
            and document.result is self._last_execution_result
            and self._last_execution_result is not None
            and self._last_execution_result.status == "succeeded"
        ):
            self.action_clear_task()
        self.refresh_task_view()
        self.call_after_refresh(self._focus_active_task, self.active_task)

    async def action_execute_current(self) -> None:
        await self.action_review()

    async def action_quit(self) -> None:
        if isinstance(self._driver, DesktopDriver):
            self._driver.request_quit()
            return
        if self.running_task is not None:
            task_label = _TASK_ACTIVITY_LABELS[self.running_task]
            self.notify(
                f"The {task_label} task is writing files. Quit stays disabled until it finishes.",
                title="Write in progress",
                severity="warning",
                timeout=6,
            )
            return
        self.exit()

    async def action_diagnostics(self) -> None:
        if not self._diagnostics_available():
            if self.active_task == "backup":
                self.notify("Choose backup files first.", severity="warning")
            else:
                self.notify(
                    "Diagnostics are available while creating a backup.",
                    severity="warning",
                )
            return
        await self.push_screen(DiagnosticsScreen(self._current_diagnostics()))

    async def action_show_task(self, task: TaskKey) -> None:
        await self._show_task(task)

    async def action_move_down(self) -> None:
        if await self._run_focused_key_binding("down"):
            return
        self._move_focused_selection(1)

    async def action_move_up(self) -> None:
        if await self._run_focused_key_binding("up"):
            return
        self._move_focused_selection(-1)

    async def action_move_left(self) -> None:
        if await self._run_focused_key_binding("left"):
            return
        if self.screen is not self.screen_stack[0]:
            self.screen.focus_previous()
            return
        if not self._move_top_navigation(-1):
            self.action_open_navigation()

    async def action_move_right(self) -> None:
        if await self._run_focused_key_binding("right"):
            return
        if self.screen is not self.screen_stack[0]:
            self.screen.focus_next()
            return
        if self._move_top_navigation(1):
            return
        self._close_nav_menu(restore_focus=False)
        self._focus_active_task(self.active_task)

    def _move_top_navigation(self, direction: int) -> bool:
        buttons = list(self.query("#workbench-navigation Button"))
        focused = self.screen.focused
        if focused not in buttons and not self._nav_menu_open:
            return False
        current = self.query_one("#nav-manage", Button) if self._nav_menu_open else focused
        self._close_nav_menu(restore_focus=False)
        assert current is not None
        self.screen.set_focus(buttons[(buttons.index(current) + direction) % len(buttons)])
        return True

    def _focus_first_blocker(self) -> None:
        validation = self._current_state().validate_task()
        first_issue = next(
            (issue for issue in validation.issues if issue.severity == "error"),
            None,
        )
        self._focus_issue(first_issue)

    def _focus_issue(self, issue: TaskIssue | None) -> None:
        selector = issue_focus_selector(self.active_task, issue)
        self._reveal_focus_target(selector)
        try:
            self.query_one(selector).focus()
        except Exception:
            self.query_one(workspace_focus_selector(self.active_task)).focus()

    def _reveal_focus_target(self, selector: str) -> None:
        workspace_id = workflow_definition(self.active_task).workspace_id
        if workspace_id is None:
            return
        try:
            workspace = self.query_one(f"#{workspace_id}", BaseWorkspace)
        except Exception:
            return
        step = workspace.step_for_target(selector)
        if step is not None and step != self.query_one(TaskCanvas).active_step:
            ui_state = self.workflow_ui_states.get(self.active_task)
            if ui_state is not None:
                ui_state.activate(step)
            else:
                self.query_one(TaskCanvas).select_step(step)
            self.refresh_task_view()
        target = workspace.query_one(selector)
        for parent in target.ancestors:
            if isinstance(parent, Collapsible):
                parent.collapsed = False
        self.call_after_refresh(target.scroll_visible, animate=False)

    def _move_focused_selection(self, direction: int) -> None:
        focused = self.screen.focused
        if (
            self.screen is self.screen_stack[0]
            and focused is not None
            and focused.parent == self.query_one("#workbench-navigation")
        ):
            if focused.id == "nav-manage":
                self._open_nav_menu()
            else:
                self._focus_active_task(self.active_task)
            return
        if direction > 0:
            self.screen.focus_next()
        else:
            self.screen.focus_previous()

    async def _run_focused_key_binding(self, key: str) -> bool:
        return await run_directional_widget_binding(self.screen.focused, key)

    def refresh_task_view(self) -> None:
        if not self.is_running:
            return
        with ExitStack() as snapshots:
            for task in BACKUP_TASKS:
                state = getattr(self, f"{task}_state")
                if isinstance(state, SourceAssessableTaskState):
                    snapshots.enter_context(state.presentation_snapshot())
            self._update_task_view()

    def _update_task_view(self) -> None:
        state = self._current_state()
        if self.active_task == "backup" and self.running_task is None:
            self.backup_estimate_controller.refresh()
        validation = state.validate_task()
        preview = state.preview()
        diagnostics_available = self._diagnostics_available()
        internals_visible = self._internals_button_enabled() and diagnostics_available
        presentation = build_task_presentation(
            task_key=self.active_task,
            title=TASK_TITLES[self.active_task],
            state=state,
            validation=validation,
            preview=preview,
            primary_label=review_label(self.active_task),
            diagnostics_available=diagnostics_available,
        )
        if is_guided_task(self.active_task):
            workflow = build_guided_workflow(
                task=self.active_task,
                state=state,
                validation=validation,
                ui_state=self.workflow_ui_states[self.active_task],
                review_summary=presentation.summary,
                review_label=review_label(self.active_task),
            )
            if workflow is not None:
                presentation = replace(
                    presentation,
                    workflow=workflow,
                    primary_action=workflow.primary_action,
                )
        preparing_task = self._preparing_review_task
        if preparing_task is not None:
            presentation = replace(
                presentation,
                primary_action=replace(
                    presentation.primary_action,
                    label="Preparing review...",
                    enabled=False,
                ),
            )
        self._sync_nav_layout()
        self._refresh_navigation()
        self._refresh_execution_status()
        self.query_one(TaskCanvas).update_task(
            task_key=self.active_task,
            title=TASK_TITLES[self.active_task],
            validation=validation,
            presentation=presentation,
            primary_label=review_label(self.active_task),
            internals_visible=internals_visible,
            running=self.running_task is not None,
            running_label=(
                _RUNNING_LABELS[self.running_task] if self.running_task is not None else None
            ),
            preparing=preparing_task is not None,
        )
        locked = preparing_task is not None or self.running_task is not None
        self.query_one("#task-workspaces").disabled = locked
        self.query_one("#workbench-steps").disabled = locked
        self.query_one("#workbench-navigation").disabled = locked
        ui_state = self.workflow_ui_states.get(self.active_task)
        self.query_one("#canvas-primary", Button).disabled = locked or (
            ui_state is not None and ui_state.has_invalid_draft(ui_state.active_step)
        )
        if self.active_task == "settings":
            self.query_one(TaskCanvas).update_settings_values(self.settings_state)

    def _focus_guided_active_step(self) -> None:
        try:
            workspace_id = workflow_definition(self.active_task).workspace_id
            if workspace_id is None:
                raise LookupError("guided workflow has no workspace")
            self.query_one(f"#{workspace_id}").query_one(WorkflowStepStack).focus_active()
        except Exception:
            self.query_one(workspace_focus_selector(self.active_task)).focus()

    def _focus_guided_step_input(self, task: TaskKey, step_key: str) -> None:
        try:
            self.query_one(f"#workflow-{task}-{step_key}-body Input").focus(scroll_visible=True)
        except Exception:
            self._focus_guided_active_step()

    def _refresh_execution_status(self) -> None:
        status = self.query_one("#app-header-status", Label)
        update_static_text(status, app_version_label())
        status.tooltip = None

    def _refresh_navigation(self) -> None:
        if self.active_task in BACKUP_TASKS:
            state = cast(UnlockTaskState, self._current_state())
            context = LoadedBackupContext.from_state(self.active_task, state)
            if context is not None:
                self._loaded_backup_context = context
            elif (
                self._loaded_backup_context is not None
                and self._loaded_backup_context.source_task == self.active_task
            ):
                self._loaded_backup_context = None
        nav = self.query_one("#nav-list", ListView)
        with nav.prevent(ListView.Highlighted):
            sync_nav_active(
                nav,
                self.active_task,
                self._navigation_task_states(),
            )
        for button_id, task in DIRECT_NAV_TASKS.items():
            self.query_one(f"#{button_id}", Button).set_class(
                self.active_task == task, "active-task"
            )
        self.query_one("#nav-manage", Button).set_class(
            self.active_task in MANAGE_TASKS, "active-task"
        )

    def _navigation_task_states(self) -> dict[TaskKey, NavTaskState]:
        states: dict[TaskKey, NavTaskState] = {}
        for task in TASK_ORDER:
            if task == "settings":
                states[task] = ""
                continue
            state = cast(TaskState, getattr(self, f"{task}_state"))
            if state.model_dump_json() == self._initial_task_payloads[task]:
                states[task] = ""
                continue
            validation = state.validate_task()
            if validation.ready:
                states[task] = "ready"
                continue
            ui_state = self.workflow_ui_states.get(task)
            needs_attention = ui_state is not None and (
                ui_state.attempted_review
                or any(
                    (step_key := step_for_section(task, issue.section)) is not None
                    and ui_state.is_touched(step_key)
                    for issue in validation.issues
                    if issue.severity == "error"
                )
            )
            states[task] = "attention" if needs_attention else "in-progress"
        return states

    async def _show_task(self, task: TaskKey) -> None:
        if not self.is_running or task not in TASK_ORDER:
            return
        if self.screen is not self.screen_stack[0]:
            return
        if self.running_task is not None:
            return
        preparing_task = self._preparing_review_task
        if preparing_task is not None and task != self.active_task:
            task_label = _TASK_ACTIVITY_LABELS[preparing_task]
            self.notify(f"Ethernity is preparing the {task_label} review.")
            return
        await self._close_task_document()
        if task == self.active_task:
            self._close_nav_menu()
            self._refresh_navigation()
            return
        menu_was_open = self._nav_menu_open
        move_workspace_focus = self.query_one("#canvas-task-workspaces").has_focus_within or (
            self.query_one("#canvas-settings-workspace").has_focus_within
        )
        if task in BACKUP_TASKS and self._loaded_backup_context is not None:
            state = cast(UnlockTaskState, self._state_for_task(task))
            ui_state = self.workflow_ui_states.get(task)
            pristine = (
                not state.model_fields_set
                and state.model_dump_json() == self._initial_task_payloads[task]
                and (ui_state is None or not ui_state.has_invalid_draft())
            )
            if pristine and self._loaded_backup_context.apply_to(state):
                if state.current_source_assessment() is None:
                    self.source_assessment_controller.request(task)
        await self.query_one(TaskCanvas).prepare_task(task)
        self.active_task = task
        self._last_execution_result = None
        self._close_nav_menu(refresh=False, restore_focus=False)
        self.refresh_task_view()
        if menu_was_open or move_workspace_focus:
            self.call_after_refresh(self._focus_active_task, task)

    def _focus_active_task(self, task: TaskKey) -> None:
        if not self.is_running or self._nav_menu_open or self.screen is not self.screen_stack[0]:
            return
        document = self.query_one(TaskCanvas).document
        if document is not None:
            if document.is_mounted:
                document.focus_default()
            return
        if task == self.active_task:
            if is_guided_task(task):
                self._focus_guided_active_step()
            elif task == "settings":
                self.query_one(SettingsForm).focus_active()
            elif task == "backup":
                step = self.query_one(TaskCanvas).active_step
                selector = {
                    "files": "#workspace-backup-files",
                    "recovery": "#workspace-backup-recovery-method",
                    "print": "#backup-destination-value",
                }[step]
                control = self.query_one(selector)
                self.query_one("#backup-workspace", BaseWorkspace).query_one(
                    FormScroll
                ).focus_start(control)
            else:
                control = self.query_one(workspace_focus_selector(task))
                workspace_id = workflow_definition(task).workspace_id
                self.query_one(f"#{workspace_id}").query_one(FormScroll).focus_start(control)

    async def _show_relative_task(self, offset: int) -> None:
        current = TASK_ORDER.index(self.active_task)
        await self._show_task(TASK_ORDER[(current + offset) % len(TASK_ORDER)])

    def _open_nav_menu(self) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        self._nav_menu_open = True
        self._refresh_navigation()
        self._sync_nav_layout()
        self._focus_nav_menu()

    def _focus_nav_menu(self) -> None:
        if self._nav_menu_open and self.screen is self.screen_stack[0]:
            self.screen.set_focus(self.query_one("#nav-list", ListView))

    def _close_nav_menu(
        self,
        *,
        refresh: bool = True,
        restore_focus: bool = True,
    ) -> None:
        was_open = self._nav_menu_open
        self._nav_menu_open = False
        if refresh:
            self._sync_nav_layout()
        if was_open and restore_focus:
            screen = self.screen_stack[0]
            screen.set_focus(screen.query_one("#nav-manage", Button))

    def _sync_nav_layout(self) -> None:
        menu = self.query_one("#nav-menu")
        menu.display = self._nav_menu_open
        if self._nav_menu_open:
            owner = self.query_one("#nav-manage")
            anchor = self.query_one("#nav-menu-anchor")
            assert menu.styles.width is not None
            menu_width = int(menu.styles.width.resolve(self.size, self.size))
            x = max(0, min(owner.region.x, self.size.width - menu_width))
            y = self.query_one("#workbench-navigation").content_region.bottom
            menu.styles.offset = (x - anchor.region.x, y - anchor.region.y)
        self.refresh_bindings()

    def _current_state(self) -> TaskState:
        return self._state_for_task(self.active_task)

    def _state_for_task(self, task: TaskKey) -> TaskState:
        return cast(TaskState, getattr(self, workflow_definition(task).state_attribute))

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

    def _internals_button_enabled(self) -> bool:
        return bool(self.settings_state.setting_value("ui_show_internals"))

    def _execute_after_review(
        self,
        reviewed_task: ReviewedTask,
        confirmed: bool | ReviewEditRequest | None,
    ) -> None:
        if self._desktop_shutdown_requested:
            return
        if isinstance(confirmed, ReviewEditRequest):
            self.call_later(self._edit_review_field, reviewed_task.task, confirmed.section)
            return
        if confirmed is not True:
            return
        self.execution_controller.start(reviewed_task)

    async def _edit_review_field(self, task: TaskKey, section: str) -> None:
        await self._show_task(task)
        step = step_for_section(task, section)
        if step is not None:
            self.workflow_ui_states[task].activate(step)
        self.refresh_task_view()
        self._review_edit_task = task
        if section in {"signature", "authentication", "variant"}:
            self._review_edit_task = None
            self._focus_section(task, section)
        elif section == "qr":
            await self._edit_qr_chunk_size()
        elif section == "freshness":
            await self._edit_expected_head_fingerprint()
        elif section == "unlock":
            await self._edit_current_unlock()
        else:
            await self._edit_section(section)
        # Inline controls return to the task form; modal editors prepare a new review.
        self._review_edit_task = None

    def _present_execution_start(self, reviewed_task: ReviewedTask) -> None:
        self._close_nav_menu(restore_focus=False)
        self._publish_desktop_status(_RUNNING_LABELS[reviewed_task.task], busy=True)
        self._last_execution_result = None
        self.refresh_task_view()
        self.query_one(TaskCanvas).present_document(
            TaskProgress(
                title=_RUNNING_LABELS[reviewed_task.task],
                task=reviewed_task.task,
                destination="\n".join(str(path) for path in reviewed_task.plan.output_paths),
                cancel=self.execution_controller.request_cancel,
            )
        )

    def _present_execution_progress(self, progress: OperationProgress) -> None:
        text = " - ".join(part for part in (progress.stage, progress.count_text) if part)
        self._publish_desktop_status(text, busy=True)
        document = self.query_one(TaskCanvas).document
        if isinstance(document, TaskProgress):
            document.update_progress(progress)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        self.execution_controller.handle_worker_state_changed(event)

    def _present_execution_outcome(
        self,
        reviewed_task: ReviewedTask,
        outcome: ExecutionOutcome,
    ) -> None:
        result = outcome.result
        title = _TASK_ACTIVITY_LABELS[reviewed_task.task].capitalize()
        state = (
            "complete" if result.ok else "cancelled" if result.status == "cancelled" else "failed"
        )
        self._publish_desktop_status(f"{title} {state}", busy=False)
        self._last_execution_result = result
        self._last_reviewed_task = reviewed_task
        if self._desktop_shutdown_requested:
            self._finish_desktop_shutdown()
            return
        self.refresh_task_view()
        recoverable_errors = () if result.ok else reviewed_task.state_snapshot.recoverable_errors()
        return_section = (
            None if result.ok else execution_failure_section(reviewed_task.task, outcome)
        )
        screen = TaskResult(
            task=reviewed_task.task,
            title=TASK_TITLES[reviewed_task.task],
            result=result,
            error=outcome.error_message,
            error_detail=outcome.error_detail,
            failed_stage=outcome.failed_stage,
            output_note=outcome.output_note,
            recoverable_errors=recoverable_errors,
            reviewed_plan=reviewed_task.plan,
            return_section=return_section,
            allow_return=outcome.allow_retry,
            context_actions_enabled=(
                result.ok and reviewed_task.task in {"backup", "add_files", "rebuild"}
            ),
        )
        self.query_one(TaskCanvas).present_document(screen)

    async def _return_to_workflow(
        self,
        task: TaskKey,
        recoverable_errors: tuple[TaskIssue, ...],
        return_section: str | None,
    ) -> None:
        await self._show_task(task)
        first_issue = next(
            (issue for issue in recoverable_errors if issue.severity == "error"),
            recoverable_errors[0] if recoverable_errors else None,
        )
        focus_section = first_issue.section if first_issue is not None else return_section
        if is_guided_task(task) and focus_section is not None:
            step_key = _return_step_for_section(task, focus_section)
            if step_key is not None:
                self.workflow_ui_states[task].activate(step_key)
        self.refresh_task_view()
        if first_issue is not None:
            self.call_after_refresh(self._focus_issue, first_issue)
        elif return_section is not None:
            self.call_after_refresh(self._focus_section, task, return_section)
        else:
            self.call_after_refresh(self._focus_active_task, task)

    def _focus_section(self, task: TaskKey, section: str) -> None:
        selector = blocker_focus_selector(task, section)
        self._reveal_focus_target(selector)
        try:
            self.query_one(selector).focus(scroll_visible=True)
        except Exception:
            self._focus_active_task(task)
