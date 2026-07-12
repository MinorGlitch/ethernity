# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

import asyncio
from dataclasses import replace
from functools import partial
from typing import cast

from textual.widget import Widget
from textual.widgets import Button, Label, ListView
from textual.worker import Worker

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_types import ActiveTask, TaskState
from ethernity.app.execution import (
    ExecutionContext,
    ExecutionOutcome,
    infer_execution_failure_section,
)
from ethernity.app.navigation import (
    NavTaskState,
    app_version_label,
    blocker_focus_selector,
    issue_focus_selector,
    run_directional_widget_binding,
    sync_nav_active,
    workspace_focus_selector,
)
from ethernity.app.screens.diagnostics import DiagnosticsScreen
from ethernity.app.screens.review_task import ReviewTaskScreen
from ethernity.app.screens.task_result import TaskResultScreen
from ethernity.app.task_catalog import (
    TASK_ORDER,
    TASK_TITLES,
    execute_label,
    review_label,
)
from ethernity.app.widgets.guided_workflow import WorkflowStepStack
from ethernity.app.widgets.task_canvas import TaskCanvas
from ethernity.app.workflow_presenter import (
    active_step_is_complete,
    build_guided_workflow,
    is_guided_task,
    next_step,
    step_for_section,
)
from ethernity.app.workflow_registry import workflow_definition
from ethernity.app.workspaces.common import BaseWorkspace
from ethernity.tasks.models import TaskDiagnostics, TaskIssue
from ethernity.tasks.presentation.builder import build_task_presentation

_TASK_ACTIVITY_LABELS: dict[ActiveTask, str] = {
    "backup": "backup",
    "restore": "restore",
    "add_files": "backup update",
    "rebuild": "backup rebuild",
    "replace_recovery_docs": "recovery-sheet replacement",
    "kit": "recovery kit",
    "settings": "settings save",
}
_REVIEW_TITLES: dict[ActiveTask, str] = {
    "backup": "Review backup",
    "restore": "Review file restore",
    "add_files": "Review backup update",
    "rebuild": "Review backup rebuild",
    "replace_recovery_docs": "Review replacement sheets",
    "kit": "Review recovery kit",
    "settings": "Review settings",
}
_RUNNING_LABELS: dict[ActiveTask, str] = {
    "backup": "Backup in progress",
    "restore": "Restore in progress",
    "add_files": "Update in progress",
    "rebuild": "Rebuild in progress",
    "replace_recovery_docs": "Replacement in progress",
    "kit": "Kit in progress",
    "settings": "Save in progress",
}


def _return_step_for_section(task: ActiveTask, section: str) -> str | None:
    if task == "replace_recovery_docs" and section == "signature":
        # Signing-key recovery is auxiliary to the nearest guided recovery decision.
        return "recovery"
    return step_for_section(task, section)


class TaskViewActions(EthernityAppContext):
    """Navigation, refresh, review, diagnostics, and execution behavior."""

    async def action_primary(self) -> None:
        if not is_guided_task(self.active_task):
            if self._current_state().validate_task().ready:
                await self.action_review()
            else:
                await self._edit_next_section()
            return

        validation = self._current_state().validate_task()
        ui_state = self.workflow_ui_states[self.active_task]
        if not active_step_is_complete(self.active_task, validation, ui_state):
            ui_state.touch(ui_state.active_step)
            self.refresh_task_view()
            self.call_after_refresh(self._focus_guided_active_step)
            return

        following_step = next_step(self.active_task, ui_state.active_step)
        if following_step is not None:
            ui_state.activate(following_step)
            self.refresh_task_view()
            self.call_after_refresh(self._focus_guided_active_step)
            return

        await self.action_review()

    async def action_review(self) -> None:
        if self._running_task is not None:
            task_label = _TASK_ACTIVITY_LABELS[self._running_task]
            self.notify(f"The {task_label} task is still running.")
            return
        preparing_task = self._preparing_review_task
        if preparing_task is not None:
            task_label = _TASK_ACTIVITY_LABELS[preparing_task]
            self.notify(f"Ethernity is preparing the {task_label} review.")
            return
        if self.active_task == "settings":
            self.notify("Settings save automatically.")
            return

        task = self.active_task
        state = self._current_state()
        ui_state = self.workflow_ui_states.get(task)
        if ui_state is not None and ui_state.has_invalid_draft():
            invalid_step = next(
                step_key for step_key in ui_state.step_keys if ui_state.has_invalid_draft(step_key)
            )
            ui_state.activate(invalid_step)
            ui_state.touch(invalid_step)
            ui_state.mark_review_attempted()
            self.refresh_task_view()
            self.call_after_refresh(self._focus_guided_step_input, task, invalid_step)
            return

        self._preparing_review_task = task
        self.refresh_task_view()
        validation = None
        context = None
        preparation_error: OSError | RuntimeError | ValueError | None = None
        try:
            if ui_state is not None and ui_state.is_touched("source"):
                await self.source_assessment_controller.ensure_current(task)
            prepare_review = getattr(state, "prepare_review", None)
            if callable(prepare_review):
                await asyncio.to_thread(prepare_review, force=True)
            validation = state.validate_task()
            if validation.ready:
                context = await asyncio.to_thread(ExecutionContext.capture, task, state)
        except (OSError, RuntimeError, ValueError) as error:
            preparation_error = error
        finally:
            self._preparing_review_task = None
            self.refresh_task_view()

        if preparation_error is not None:
            self.notify(
                f"Ethernity could not prepare the review: {preparation_error}",
                severity="error",
            )
            return
        assert validation is not None
        if not validation.ready:
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
        assert context is not None
        await self._push_execution_review(context)

    async def _push_execution_review(self, context: ExecutionContext) -> None:
        await self.push_screen(
            ReviewTaskScreen(
                title=_REVIEW_TITLES[context.task],
                validation=context.validation,
                preview=context.preview,
                plan=context.plan,
                execute_label=execute_label(context.task),
                decision_facts=context.decision_facts,
            ),
            partial(self._execute_after_review, context),
        )

    async def action_execute_current(self) -> None:
        await self.action_review()

    async def action_quit(self) -> None:
        if self._running_task is not None:
            task_label = _TASK_ACTIVITY_LABELS[self._running_task]
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

    def action_show_task(self, task: ActiveTask) -> None:
        self._show_task(task)

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
        self._open_nav_drawer()

    async def action_move_right(self) -> None:
        if await self._run_focused_key_binding("right"):
            return
        self._close_nav_drawer(restore_focus=False)
        if self.active_task == "settings":
            self.query_one("#setting-control-render_style").focus()
        else:
            self.query_one(workspace_focus_selector(self.active_task)).focus()

    def _focus_first_blocker(self) -> None:
        validation = self._current_state().validate_task()
        first_issue = next(
            (issue for issue in validation.issues if issue.severity == "error"),
            None,
        )
        self._focus_issue(first_issue)

    def _focus_issue(self, issue: TaskIssue | None) -> None:
        selector = issue_focus_selector(self.active_task, issue)
        self._reveal_advanced_focus_target(selector)
        try:
            self.query_one(selector).focus()
        except Exception:
            self.query_one(workspace_focus_selector(self.active_task)).focus()

    def _reveal_advanced_focus_target(self, selector: str) -> None:
        workspace_id = workflow_definition(self.active_task).workspace_id
        if workspace_id is None:
            return
        try:
            workspace = self.query_one(f"#{workspace_id}", BaseWorkspace)
        except Exception:
            return
        workspace.reveal_advanced_focus_target(selector)

    def _move_focused_selection(self, direction: int) -> bool:
        focused = self.screen.focused
        if self.active_task == "settings" and focused is not self.query_one("#nav-list", ListView):
            if direction > 0:
                self.screen.focus_next(".settings-control")
            else:
                self.screen.focus_previous(".settings-control")
            return True
        if (
            focused is not self.query_one("#nav-list", ListView)
            and self.query_one("#task-workspaces").has_focus_within
        ):
            if direction > 0:
                self.screen.focus_next(".workspace-control")
            else:
                self.screen.focus_previous(".workspace-control")
            return True
        if isinstance(focused, ListView):
            if direction > 0:
                focused.action_cursor_down()
            else:
                focused.action_cursor_up()
            return True
        return False

    async def _run_focused_key_binding(self, key: str) -> bool:
        return await run_directional_widget_binding(self.screen.focused, key)

    def refresh_task_view(self) -> None:
        state = self._current_state()
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
            running=self._running_task is not None,
            running_label=(
                _RUNNING_LABELS[self._running_task] if self._running_task is not None else None
            ),
        )
        self.query_one("#task-workspaces").disabled = preparing_task is not None
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

    def _focus_guided_step_input(self, task: ActiveTask, step_key: str) -> None:
        try:
            self.query_one(f"#workflow-{task}-{step_key}-body Input").focus(scroll_visible=True)
        except Exception:
            self._focus_guided_active_step()

    def _refresh_execution_status(self) -> None:
        status = self.query_one("#app-header-status", Label)
        status.update(app_version_label())
        status.tooltip = None

    def _refresh_navigation(self) -> None:
        nav = self.query_one("#nav-list", ListView)
        with nav.prevent(ListView.Highlighted):
            sync_nav_active(nav, self.active_task, self._navigation_task_states())
            self._nav_rendered_task = self.active_task

    def _navigation_task_states(self) -> dict[ActiveTask, NavTaskState]:
        states: dict[ActiveTask, NavTaskState] = {}
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

    def _show_task(self, task: ActiveTask) -> None:
        if task not in TASK_ORDER:
            return
        preparing_task = self._preparing_review_task
        if preparing_task is not None and task != self.active_task:
            task_label = _TASK_ACTIVITY_LABELS[preparing_task]
            self.notify(f"Ethernity is preparing the {task_label} review.")
            return
        if task == self.active_task:
            self._close_nav_drawer()
            self._refresh_navigation()
            return
        drawer_was_open = self._nav_drawer_open
        move_workspace_focus = self.query_one("#canvas-task-workspaces").has_focus_within or (
            self.query_one("#canvas-settings-workspace").has_focus_within
        )
        self.active_task = task
        self._last_execution_result = None
        self._close_nav_drawer(refresh=False, restore_focus=False)
        self.refresh_task_view()
        if drawer_was_open or move_workspace_focus:
            self.call_after_refresh(self._focus_active_task, task)

    def _focus_active_task(self, task: ActiveTask) -> None:
        if task == self.active_task:
            self.query_one(workspace_focus_selector(task)).focus()

    def _show_relative_task(self, offset: int) -> None:
        current = TASK_ORDER.index(self.active_task)
        self._show_task(TASK_ORDER[(current + offset) % len(TASK_ORDER)])

    def _open_nav_drawer(self) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        if not self._nav_should_collapse():
            self._nav_focus_generation += 1
            self._discard_nav_return_focus()
            self._nav_drawer_open = False
            self._sync_nav_layout()
            self.query_one("#nav-list", ListView).focus()
            return
        if not self._nav_drawer_open:
            self._remember_nav_return_focus()
            self._nav_focus_generation += 1
        self._nav_drawer_open = True
        self._sync_nav_layout()
        self.query_one("#nav-list", ListView).focus()

    def _close_nav_drawer(
        self,
        *,
        refresh: bool = True,
        restore_focus: bool = True,
    ) -> None:
        if not self._nav_drawer_open:
            if not restore_focus:
                self._nav_focus_generation += 1
                self._discard_nav_return_focus()
            return
        self._nav_drawer_open = False
        self._nav_focus_generation += 1
        focus_generation = self._nav_focus_generation
        if refresh:
            self._sync_nav_layout()
        if restore_focus:
            self.call_after_refresh(self._restore_nav_return_focus, focus_generation)
        else:
            self._discard_nav_return_focus()

    def _remember_nav_return_focus(self) -> None:
        focused = self.screen.focused
        focus_id = None if focused is None or focused.id == "nav-list" else focused.id
        self._nav_return_focus_id = focus_id
        self._nav_return_focus_task = self.active_task

    def _restore_nav_return_focus(self, focus_generation: int) -> None:
        if self._nav_drawer_open or focus_generation != self._nav_focus_generation:
            return
        focus_id = self._nav_return_focus_id
        return_task = self._nav_return_focus_task
        self._discard_nav_return_focus()
        main_screen = self.screen_stack[0]

        if focus_id is not None:
            try:
                target = main_screen.query_one(f"#{focus_id}", Widget)
            except Exception:
                target = None
            if target is not None and target.can_focus and not target.disabled:
                target.focus(scroll_visible=True)
                return

        if return_task != self.active_task:
            return
        if is_guided_task(self.active_task):
            self._focus_guided_active_step()
            return
        try:
            main_screen.query_one(workspace_focus_selector(self.active_task), Widget).focus(
                scroll_visible=True
            )
        except Exception:
            main_screen.query_one("#nav-strip", Button).focus()

    def _discard_nav_return_focus(self) -> None:
        self._nav_return_focus_id = None
        self._nav_return_focus_task = None

    def _sync_nav_layout(self) -> None:
        shell = self.query_one("#shell")
        should_collapse = self._nav_should_collapse()
        restore_after_resize = not should_collapse and self._nav_drawer_open
        focus_generation: int | None = None
        if restore_after_resize:
            self._nav_drawer_open = False
            self._nav_focus_generation += 1
            focus_generation = self._nav_focus_generation
        shell.set_class(self.size.width <= 150, "compact-nav")
        shell.set_class(should_collapse and not self._nav_drawer_open, "nav-collapsed")
        shell.set_class(should_collapse and self._nav_drawer_open, "nav-drawer-open")
        if should_collapse and not self._nav_drawer_open:
            nav_list = self.query_one("#nav-list", ListView)
            if self.screen.focused is nav_list:
                self.query_one("#nav-strip", Button).focus()
        if focus_generation is not None:
            self.call_after_refresh(self._restore_nav_return_focus, focus_generation)

    def _current_state(self) -> TaskState:
        return self._state_for_task(self.active_task)

    def _state_for_task(self, task: ActiveTask) -> TaskState:
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
        context: ExecutionContext,
        confirmed: bool | None,
    ) -> None:
        if confirmed is not True:
            return
        self.execution_controller.start(context)

    def _present_execution_start(self, task: ActiveTask) -> None:
        del task
        self._last_execution_result = None
        self.refresh_task_view()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        self.execution_controller.handle_worker_state_changed(event)

    def _present_execution_outcome(
        self,
        context: ExecutionContext,
        outcome: ExecutionOutcome,
    ) -> None:
        result = outcome.result
        self._last_execution_result = result
        self.refresh_task_view()
        recoverable_errors = () if result.ok else context.state_snapshot.recoverable_errors()
        return_section = (
            None if result.ok else infer_execution_failure_section(context.task, outcome)
        )
        screen = TaskResultScreen(
            task=context.task,
            title=TASK_TITLES[context.task],
            result=result,
            error=outcome.error_message,
            error_detail=outcome.error_detail,
            recoverable_errors=recoverable_errors,
            reviewed_plan=context.plan,
            return_section=return_section,
            allow_return=outcome.allow_retry,
            return_callback=(
                partial(
                    self._return_to_workflow,
                    context.task,
                    recoverable_errors,
                    return_section,
                )
                if not result.ok and outcome.allow_retry
                else None
            ),
        )
        self.push_screen(screen)

    async def _return_to_workflow(
        self,
        task: ActiveTask,
        recoverable_errors: tuple[TaskIssue, ...],
        return_section: str | None,
    ) -> None:
        self._show_task(task)
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

    def _focus_section(self, task: ActiveTask, section: str) -> None:
        selector = blocker_focus_selector(task, section)
        self._reveal_advanced_focus_target(selector)
        try:
            self.query_one(selector).focus(scroll_visible=True)
        except Exception:
            self._focus_active_task(task)
