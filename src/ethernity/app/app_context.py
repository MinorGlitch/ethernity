# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ethernity.app.app_types import ActiveTask
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.doctor import DoctorTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState


class EthernityAppContext:
    """Shared type surface expected by app action controllers."""

    active_task: ActiveTask
    backup_state: BackupTaskState
    restore_state: RestoreTaskState
    add_files_state: AddFilesTaskState
    rebuild_state: RebuildTaskState
    replace_recovery_docs_state: ReplaceRecoveryDocsTaskState
    kit_state: PrintKitTaskState
    doctor_state: DoctorTaskState
    settings_state: SettingsTaskState
    settings_controller: Any
    _last_execution_result: TaskExecutionResult | None

    if TYPE_CHECKING:
        screen: Any

        def query_one(
            self,
            selector: str | type[Any],
            expect_type: type[Any] | None = None,
        ) -> Any: ...

        def push_screen(
            self,
            screen: Any,
            callback: Callable[[Any], Any] | None = None,
            wait_for_dismiss: bool = False,
            *,
            mode: str | None = None,
        ) -> Any: ...

        def notify(
            self,
            message: str,
            *,
            title: str = "",
            severity: Literal["information", "warning", "error"] = "information",
            timeout: float | None = None,
            markup: bool = True,
        ) -> None: ...

        def refresh_task_view(self) -> None: ...

        async def action_review(self) -> None: ...

        async def action_diagnostics(self) -> None: ...

        async def action_edit_primary(self) -> None: ...

        async def action_edit_output(self) -> None: ...

        async def action_edit_passphrase(self) -> None: ...

        def _current_layout(self) -> tuple[str, str]: ...

        def _current_state(self) -> Any: ...

        def _unlock_state(self) -> Any: ...

        def _confirm_source_freshness(self) -> None: ...

        def _toggle_kit_variant(self) -> None: ...

        async def _handle_workspace_button(self, button_id: str) -> None: ...

        async def _apply_workspace_select(self, select_id: str, value: str) -> None: ...

        async def _apply_workspace_radio(self, radio_id: str, pressed_id: str) -> None: ...

        def _show_task(self, task: ActiveTask) -> None: ...

        def _apply_backup_files_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_restore_sources_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_add_files_inputs_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_rebuild_source_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_replace_recovery_sources_picked(
            self,
            paths: tuple[Path, ...] | None,
        ) -> None: ...

        def _apply_backup_output_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_restore_output_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_kit_output_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_add_files_backup_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_rebuild_output_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_replace_recovery_output_picked(
            self,
            paths: tuple[Path, ...] | None,
        ) -> None: ...

        def _apply_backup_passphrase(self, value: str | None) -> None: ...

        def _apply_restore_passphrase(self, value: str | None) -> None: ...

        def _apply_add_files_passphrase(self, value: str | None) -> None: ...

        def _apply_rebuild_passphrase(self, value: str | None) -> None: ...

        def _apply_replace_recovery_passphrase(self, value: str | None) -> None: ...

        def _apply_unlock_recovery_documents_picked(
            self,
            paths: tuple[Path, ...] | None,
        ) -> None: ...

        def _apply_unlock_payload_files_picked(
            self,
            paths: tuple[Path, ...] | None,
        ) -> None: ...

        def _apply_add_files_sources_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_add_files_base_dir_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_backup_base_dir_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_backup_signing_key_shards(self, value: str | None) -> None: ...

        def _apply_qr_chunk_size(self, value: str | None) -> None: ...

        def _apply_add_files_recovery_documents(self, value: str | None) -> None: ...

        def _apply_add_files_signing_key_shards(self, value: str | None) -> None: ...

        def _apply_restore_recovery_text_picked(
            self,
            paths: tuple[Path, ...] | None,
        ) -> None: ...

        def _apply_restore_payloads_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_restore_auth_text_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_restore_auth_payloads_picked(
            self,
            paths: tuple[Path, ...] | None,
        ) -> None: ...

        def _apply_rebuild_auth_text_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_rebuild_auth_payloads_picked(
            self,
            paths: tuple[Path, ...] | None,
        ) -> None: ...

        def _apply_replace_recovery_text_picked(
            self,
            paths: tuple[Path, ...] | None,
        ) -> None: ...

        def _apply_replace_payloads_picked(self, paths: tuple[Path, ...] | None) -> None: ...

        def _apply_replace_signing_key_payloads_picked(
            self,
            paths: tuple[Path, ...] | None,
        ) -> None: ...

        def _apply_backup_recovery(self, value: str | None) -> None: ...

        def _apply_replace_recovery_set(self, value: str | None) -> None: ...

        def _apply_replace_signing_key_recovery(self, value: str | None) -> None: ...

        def _apply_replace_passphrase_replacement_count(
            self,
            value: str | None,
        ) -> None: ...

        def _apply_replace_signing_key_replacement_count(
            self,
            value: str | None,
        ) -> None: ...

        def _apply_layout_section(self, value: str | None) -> None: ...

        def _apply_restore_target(self, value: str | None) -> None: ...

        def _apply_restore_target_fingerprint(self, value: str | None) -> None: ...

        def _apply_expected_head_fingerprint(self, value: str | None) -> None: ...
