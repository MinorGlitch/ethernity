from __future__ import annotations

from pathlib import Path

from ethernity.app.input_parsers import parse_paths
from ethernity.app.mutations.state import TaskStateMutationActions
from ethernity.app.path_utils import split_file_dir_paths


class TaskPathMutationActions(TaskStateMutationActions):
    def _apply_backup_files(self, value: str | None) -> None:
        if value is not None:
            self.backup_state.input_paths, self.backup_state.input_dirs = split_file_dir_paths(
                parse_paths(value)
            )
            self.refresh_task_view()

    def _apply_backup_files_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.backup_state.input_paths, self.backup_state.input_dirs = split_file_dir_paths(
                paths
            )
            self.refresh_task_view()

    def _apply_restore_sources(self, value: str | None) -> None:
        if value is not None:
            self.restore_state.source_paths = parse_paths(value)
            self.restore_state.recovery_text_file = None
            self.restore_state.payloads_file = None
            self.restore_state.expected_head_doc_hash = None
            self.refresh_task_view()

    def _apply_restore_sources_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.restore_state.source_paths = list(paths)
            self.restore_state.recovery_text_file = None
            self.restore_state.payloads_file = None
            self.restore_state.expected_head_doc_hash = None
            self.refresh_task_view()

    def _apply_restore_recovery_text_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.restore_state.recovery_text_file = paths[0] if paths else None
            self.restore_state.payloads_file = None
            self.restore_state.source_paths = []
            self.restore_state.expected_head_doc_hash = None
            self.refresh_task_view()

    def _apply_restore_payloads_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.restore_state.payloads_file = paths[0] if paths else None
            self.restore_state.recovery_text_file = None
            self.restore_state.source_paths = []
            self.restore_state.expected_head_doc_hash = None
            self.refresh_task_view()

    def _apply_restore_auth_text_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.restore_state.auth_text_file = paths[0] if paths else None
            self.restore_state.auth_payloads_file = None
            self.refresh_task_view()

    def _apply_restore_auth_payloads_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.restore_state.auth_payloads_file = paths[0] if paths else None
            self.restore_state.auth_text_file = None
            self.refresh_task_view()

    def _apply_backup_output(self, value: str | None) -> None:
        if value is not None:
            self.backup_state.output_dir = Path(value) if value else None
            self.refresh_task_view()

    def _apply_backup_output_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.backup_state.output_dir = paths[0] if paths else None
            self.refresh_task_view()

    def _apply_backup_base_dir_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.backup_state.base_dir = paths[0] if paths else None
            self.refresh_task_view()

    def _apply_add_files_base_dir_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.add_files_state.base_dir = paths[0] if paths else None
            self.refresh_task_view()

    def _apply_restore_output(self, value: str | None) -> None:
        if value is not None:
            self.restore_state.output_path = Path(value) if value else None
            self.refresh_task_view()

    def _apply_restore_output_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.restore_state.output_path = paths[0] if paths else None
            self.refresh_task_view()

    def _apply_add_files_backup(self, value: str | None) -> None:
        if value is not None:
            self.add_files_state.backup_folder = Path(value) if value else None
            self.refresh_task_view()

    def _apply_add_files_backup_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.add_files_state.backup_folder = paths[0] if paths else None
            self.refresh_task_view()

    def _apply_rebuild_source(self, value: str | None) -> None:
        if value is not None:
            self.rebuild_state.backup_folder = Path(value) if value else None
            self.rebuild_state.source_paths = []
            self.rebuild_state.allow_stale_head = False
            self.rebuild_state.expected_head_doc_hash = None
            self.refresh_task_view()

    def _apply_rebuild_source_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is None:
            return
        if len(paths) == 1 and paths[0].is_dir():
            self.rebuild_state.backup_folder = paths[0]
            self.rebuild_state.source_paths = []
            self.rebuild_state.allow_stale_head = False
            self.rebuild_state.expected_head_doc_hash = None
        else:
            self.rebuild_state.backup_folder = None
            self.rebuild_state.source_paths = list(paths)
            self.rebuild_state.allow_stale_head = False
            self.rebuild_state.expected_head_doc_hash = None
        self.refresh_task_view()

    def _apply_replace_recovery_sources(self, value: str | None) -> None:
        if value is not None:
            self.replace_recovery_docs_state.source_paths = parse_paths(value)
            self.replace_recovery_docs_state.recovery_text_file = None
            self.replace_recovery_docs_state.payloads_file = None
            self.replace_recovery_docs_state.allow_stale_head = False
            self.replace_recovery_docs_state.expected_head_doc_hash = None
            self.refresh_task_view()

    def _apply_replace_recovery_sources_picked(
        self,
        paths: tuple[Path, ...] | None,
    ) -> None:
        if paths is not None:
            self.replace_recovery_docs_state.source_paths = list(paths)
            self.replace_recovery_docs_state.recovery_text_file = None
            self.replace_recovery_docs_state.payloads_file = None
            self.replace_recovery_docs_state.allow_stale_head = False
            self.replace_recovery_docs_state.expected_head_doc_hash = None
            self.refresh_task_view()

    def _apply_replace_recovery_text_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.replace_recovery_docs_state.recovery_text_file = paths[0] if paths else None
            self.replace_recovery_docs_state.payloads_file = None
            self.replace_recovery_docs_state.source_paths = []
            self.replace_recovery_docs_state.allow_stale_head = False
            self.replace_recovery_docs_state.expected_head_doc_hash = None
            self.refresh_task_view()

    def _apply_replace_payloads_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.replace_recovery_docs_state.payloads_file = paths[0] if paths else None
            self.replace_recovery_docs_state.recovery_text_file = None
            self.replace_recovery_docs_state.source_paths = []
            self.replace_recovery_docs_state.allow_stale_head = False
            self.replace_recovery_docs_state.expected_head_doc_hash = None
            self.refresh_task_view()

    def _apply_replace_signing_key_payloads_picked(
        self,
        paths: tuple[Path, ...] | None,
    ) -> None:
        if paths is not None:
            self.replace_recovery_docs_state.signing_key_recovery_payload_files = list(paths)
            self.refresh_task_view()

    def _apply_rebuild_output(self, value: str | None) -> None:
        if value is not None:
            self.rebuild_state.output_dir = Path(value) if value else None
            self.refresh_task_view()

    def _apply_rebuild_output_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.rebuild_state.output_dir = paths[0] if paths else None
            self.refresh_task_view()

    def _apply_rebuild_auth_text_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.rebuild_state.auth_text_file = paths[0] if paths else None
            self.rebuild_state.auth_payloads_file = None
            self.refresh_task_view()

    def _apply_rebuild_auth_payloads_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.rebuild_state.auth_payloads_file = paths[0] if paths else None
            self.rebuild_state.auth_text_file = None
            self.refresh_task_view()

    def _apply_replace_recovery_output(self, value: str | None) -> None:
        if value is not None:
            self.replace_recovery_docs_state.output_dir = Path(value) if value else None
            self.refresh_task_view()

    def _apply_replace_recovery_output_picked(
        self,
        paths: tuple[Path, ...] | None,
    ) -> None:
        if paths is not None:
            self.replace_recovery_docs_state.output_dir = paths[0] if paths else None
            self.refresh_task_view()

    def _apply_kit_output(self, value: str | None) -> None:
        if value is not None and value:
            self.kit_state.output_path = Path(value)
            self.refresh_task_view()

    def _apply_kit_output_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None and paths:
            self.kit_state.output_path = paths[0]
            self.refresh_task_view()
