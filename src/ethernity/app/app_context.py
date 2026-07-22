# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

from textual.app import App

from ethernity.app.app_types import ActiveTask, TaskState, UnlockTaskState
from ethernity.app.execution_controller import ExecutionController
from ethernity.app.settings_controller import SettingsController
from ethernity.app.source_assessment_controller import SourceAssessmentController
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskExecutionResult, TaskIssue
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState


class EthernityAppContext(App[None]):
    """Shared type surface expected by app action controllers."""

    active_task: ActiveTask
    backup_state: BackupTaskState
    restore_state: RestoreTaskState
    add_files_state: AddFilesTaskState
    rebuild_state: RebuildTaskState
    replace_recovery_docs_state: ReplaceRecoveryDocsTaskState
    kit_state: PrintKitTaskState
    settings_state: SettingsTaskState
    settings_controller: SettingsController
    execution_controller: ExecutionController
    source_assessment_controller: SourceAssessmentController
    workflow_ui_states: dict[ActiveTask, WorkflowUiState]
    _initial_task_payloads: dict[ActiveTask, str]
    _last_execution_result: TaskExecutionResult | None
    _preparing_review_task: ActiveTask | None
    _nav_drawer_open: bool
    _nav_rendered_task: ActiveTask | None
    _nav_return_focus_id: str | None
    _nav_return_focus_task: ActiveTask | None
    _nav_focus_generation: int

    @property
    def _running_task(self) -> ActiveTask | None:
        raise NotImplementedError

    def refresh_task_view(self) -> None: ...

    def _rehydrate_workflow_defaults(self) -> None: ...

    async def action_review(self) -> None: ...

    async def action_primary(self) -> None: ...

    async def _edit_next_section(self) -> None: ...

    def _focus_issue(self, issue: TaskIssue | None) -> None: ...

    async def action_diagnostics(self) -> None: ...

    async def action_edit_primary(self) -> None: ...

    async def action_edit_output(self) -> None: ...

    async def action_edit_passphrase(self) -> None: ...

    def _current_layout(self) -> tuple[str, str]: ...

    def _current_state(self) -> TaskState: ...

    def _unlock_state(self) -> UnlockTaskState | None: ...

    def _confirm_source_freshness(self) -> None: ...

    def _toggle_kit_variant(self) -> None: ...

    async def _handle_workspace_button(self, button_id: str) -> None: ...

    async def _apply_workspace_select(self, select_id: str, value: str) -> None: ...

    async def _apply_workspace_choice(self, choice_list_id: str, choice_key: str) -> None: ...

    def _source_changed(self, task: ActiveTask) -> None: ...

    def _show_task(self, task: ActiveTask) -> None: ...

    def _open_nav_drawer(self) -> None: ...

    def _close_nav_drawer(
        self,
        *,
        refresh: bool = True,
        restore_focus: bool = True,
    ) -> None: ...

    def _nav_should_collapse(self) -> bool: ...

    def _sync_nav_layout(self) -> None: ...
