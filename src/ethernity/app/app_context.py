# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

from ethernity.app.app_types import UnlockTaskState
from ethernity.app.backup_context import LoadedBackupContext
from ethernity.app.backup_estimate_controller import BackupEstimateController
from ethernity.app.execution import ReviewedTask
from ethernity.app.execution_controller import ExecutionController
from ethernity.app.navigation import NavMenu
from ethernity.app.recovery_check_controller import RecoveryCheckController
from ethernity.app.settings_controller import SettingsController
from ethernity.app.source_assessment_controller import SourceAssessmentController
from ethernity.app.styling import StyledApp
from ethernity.app.workflow_state import WorkflowUiState
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskExecutionResult, TaskIssue
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState
from ethernity.tasks.task_types import TaskKey, TaskState


class EthernityAppContext(StyledApp):
    """Shared application context required by action controllers."""

    active_task: TaskKey
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
    backup_estimate_controller: BackupEstimateController
    recovery_check_controller: RecoveryCheckController
    workflow_ui_states: dict[TaskKey, WorkflowUiState]
    _initial_task_payloads: dict[TaskKey, str]
    _last_execution_result: TaskExecutionResult | None
    _last_reviewed_task: ReviewedTask | None
    _review_edit_task: TaskKey | None
    _preparing_review_task: TaskKey | None
    _nav_menu_open: bool
    _nav_menu: NavMenu
    _loaded_backup_context: LoadedBackupContext | None

    @property
    def running_task(self) -> TaskKey | None:
        raise NotImplementedError

    def refresh_task_view(self) -> None: ...

    def _commit_form_inputs(self) -> None: ...

    def _rehydrate_workflow_defaults(self) -> None: ...

    async def action_review(self) -> None: ...

    async def action_primary(self) -> None: ...

    async def _edit_next_section(self) -> None: ...

    async def _edit_section(self, section_key: str) -> None: ...

    async def _edit_qr_chunk_size(self) -> None: ...

    async def _edit_expected_head_fingerprint(self) -> None: ...

    async def _edit_current_unlock(self) -> None: ...

    def _focus_issue(self, issue: TaskIssue | None) -> None: ...

    async def action_diagnostics(self) -> None: ...

    async def action_edit_primary(self) -> None: ...

    async def action_edit_output(self) -> None: ...

    async def action_edit_passphrase(self) -> None: ...

    def _current_layout(self) -> tuple[str, str]: ...

    def _current_state(self) -> TaskState: ...

    def _state_for_task(self, task: TaskKey) -> TaskState: ...

    def _unlock_state(self) -> UnlockTaskState | None: ...

    def _confirm_source_freshness(self) -> None: ...

    def _toggle_kit_variant(self) -> None: ...

    async def _handle_workspace_button(self, button_id: str) -> None: ...

    async def _apply_workspace_select(self, select_id: str, value: str) -> None: ...

    async def _apply_workspace_choice(self, choice_list_id: str, choice_key: str) -> None: ...

    def _source_changed(self, task: TaskKey) -> None: ...

    async def _show_task(self, task: TaskKey) -> None: ...

    def _open_nav_menu(self, menu: NavMenu) -> None: ...

    def _close_nav_menu(
        self,
        *,
        refresh: bool = True,
        restore_focus: bool = True,
    ) -> None: ...

    async def _select_workbench_step(self, key: str) -> None: ...

    def _focus_active_task(self, task: TaskKey) -> None: ...

    def _refresh_navigation(self) -> None: ...

    def action_open_navigation(self) -> None: ...

    def _sync_nav_layout(self) -> None: ...
