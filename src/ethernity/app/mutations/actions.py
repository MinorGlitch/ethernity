from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from ethernity.app.input_parsers import (
    parse_layout,
    parse_paths,
    parse_threshold_count,
    parse_update_index,
)
from ethernity.app.mutations.paths import TaskPathMutationActions
from ethernity.app.path_utils import split_file_dir_paths
from ethernity.tasks.quorum import MAX_SHARDS

QUORUM_INPUT_HELP = f"Use required/total sheets from 1 to {MAX_SHARDS}, such as 2/3."


class TaskMutationActions(TaskPathMutationActions):
    """Apply parsed user input to task state models."""

    def _apply_backup_passphrase(self, value: str | None) -> None:
        if value is not None:
            if value:
                self.backup_state.passphrase_words = None
            self.backup_state.passphrase = value or None
            self.refresh_task_view()

    def _apply_restore_passphrase(self, value: str | None) -> None:
        if value is None:
            self.refresh_task_view()
            return
        self.restore_state.passphrase = value or None
        if value:
            self.restore_state.recovery_documents = []
            self.restore_state.recovery_payload_files = []
        self.refresh_task_view()

    def _apply_add_files_inputs(self, value: str | None) -> None:
        if value is not None:
            self.add_files_state.input_paths, self.add_files_state.input_dirs = (
                split_file_dir_paths(parse_paths(value))
            )
            self.refresh_task_view()

    def _apply_add_files_inputs_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.add_files_state.input_paths, self.add_files_state.input_dirs = (
                split_file_dir_paths(paths)
            )
            self.refresh_task_view()

    def _apply_add_files_input_files_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.add_files_state.input_paths = list(paths)
            self.refresh_task_view()

    def _apply_add_files_input_folder_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths:
            folder = paths[0]
            if folder not in self.add_files_state.input_dirs:
                self.add_files_state.input_dirs.append(folder)
            self.refresh_task_view()

    def _apply_add_files_sources(self, value: str | None) -> None:
        if value is not None:
            self.add_files_state.source_paths = parse_paths(value)
            if self.add_files_state.source_paths:
                self.add_files_state.backup_folder = None
            self.add_files_state.allow_stale_head = False
            self.add_files_state.expected_head_doc_hash = None
            self._source_changed("add_files")

    def _apply_add_files_sources_picked(self, paths: tuple[Path, ...] | None) -> None:
        if paths is not None:
            self.add_files_state.source_paths = list(paths)
            if self.add_files_state.source_paths:
                self.add_files_state.backup_folder = None
            self.add_files_state.allow_stale_head = False
            self.add_files_state.expected_head_doc_hash = None
            self._source_changed("add_files")

    def _apply_add_files_passphrase(self, value: str | None) -> None:
        if value is None:
            self.refresh_task_view()
            return
        self.add_files_state.passphrase = value or None
        if value:
            self.add_files_state.recovery_documents = []
            self.add_files_state.recovery_payload_files = []
        self.refresh_task_view()

    def _apply_rebuild_passphrase(self, value: str | None) -> None:
        if value is None:
            self.refresh_task_view()
            return
        self.rebuild_state.passphrase = value or None
        if value:
            self.rebuild_state.recovery_documents = []
            self.rebuild_state.recovery_payload_files = []
        self.refresh_task_view()

    def _apply_replace_recovery_passphrase(self, value: str | None) -> None:
        if value is None:
            self.refresh_task_view()
            return
        self.replace_recovery_docs_state.passphrase = value or None
        if value:
            self.replace_recovery_docs_state.recovery_documents = []
            self.replace_recovery_docs_state.recovery_payload_files = []
        self.refresh_task_view()

    def _apply_unlock_recovery_documents_picked(
        self,
        paths: tuple[Path, ...] | None,
    ) -> None:
        state = self._unlock_state()
        if state is None:
            return
        if paths is None:
            self.refresh_task_view()
            return
        state.recovery_documents = list(paths)
        if paths:
            state.passphrase = None
            state.recovery_payload_files = []
        self.refresh_task_view()

    def _apply_unlock_payload_files_picked(self, paths: tuple[Path, ...] | None) -> None:
        state = self._unlock_state()
        if state is None:
            return
        if paths is None:
            self.refresh_task_view()
            return
        state.recovery_payload_files = list(paths)
        if paths:
            state.passphrase = None
            state.recovery_documents = []
        self.refresh_task_view()

    def _apply_backup_recovery(self, value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip().lower()
        if not normalized or normalized in {"recommended", "recommended_shards", "shards"}:
            self.backup_state.recovery_method = "recommended_shards"
            self.backup_state.shard_threshold = 2
            self.backup_state.shard_count = 3
        elif normalized in {"single", "single_phrase", "phrase"}:
            self.backup_state.recovery_method = "single_phrase"
        elif counts := parse_threshold_count(normalized):
            threshold, count = counts
            self.backup_state.recovery_method = "custom_shards"
            self.backup_state.shard_threshold = 1
            self.backup_state.shard_count = count
            self.backup_state.shard_threshold = threshold
        else:
            self.notify(
                f"Use recommended, single, or required/total sheets from 1 to {MAX_SHARDS}.",
                severity="error",
            )
            return
        self.refresh_task_view()

    def _apply_backup_signing_key_shards(self, value: str | None) -> None:
        if value is None:
            return
        counts = parse_threshold_count(value.strip().lower())
        if counts is None:
            self.notify(QUORUM_INPUT_HELP, severity="error")
            return
        threshold, count = counts
        self.backup_state.signing_key_mode = "sharded"
        self.backup_state.signing_key_shard_threshold = None
        self.backup_state.signing_key_shard_count = count
        self.backup_state.signing_key_shard_threshold = threshold
        self.refresh_task_view()

    def _apply_qr_chunk_size(self, value: str | None) -> None:
        if value is None:
            self.refresh_task_view()
            return
        normalized = value.strip()
        if not normalized:
            self._set_current_qr_chunk_size(None)
            self.refresh_task_view()
            return
        try:
            chunk_size = int(normalized)
        except ValueError:
            self.notify("Use a positive whole number.", severity="error")
            return
        if chunk_size < 1:
            self.notify("Use a positive whole number.", severity="error")
            return
        self._set_current_qr_chunk_size(chunk_size)
        self.refresh_task_view()

    def _set_current_qr_chunk_size(self, value: int | None) -> None:
        if self.active_task == "backup":
            self.backup_state.qr_chunk_size = value
        elif self.active_task == "add_files":
            self.add_files_state.qr_chunk_size = value
        elif self.active_task == "rebuild":
            self.rebuild_state.qr_chunk_size = value
        elif self.active_task == "kit":
            self.kit_state.chunk_size = value

    def _apply_add_files_recovery_documents(self, value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip().lower()
        if not normalized or normalized in {"default", "defaults"}:
            self.add_files_state.recovery_document_threshold = None
            self.add_files_state.recovery_document_count = None
        elif normalized in {"none", "off", "0"}:
            self.add_files_state.recovery_document_threshold = None
            self.add_files_state.recovery_document_count = 0
        elif counts := parse_threshold_count(normalized):
            threshold, count = counts
            self.add_files_state.unlock_policy = "self-contained"
            self.add_files_state.recovery_document_threshold = None
            self.add_files_state.recovery_document_count = count
            self.add_files_state.recovery_document_threshold = threshold
        else:
            self.notify(
                f"Use default, none, or required/total sheets from 1 to {MAX_SHARDS}.",
                severity="error",
            )
            return
        self.refresh_task_view()

    def _apply_add_files_signing_key_shards(self, value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip().lower()
        if not normalized or normalized in {"default", "defaults"}:
            self.add_files_state.signing_key_mode = None
            self.add_files_state.signing_key_recovery_threshold = None
            self.add_files_state.signing_key_recovery_count = None
            self.refresh_task_view()
            return
        counts = parse_threshold_count(normalized)
        if counts is None:
            self.notify(
                f"Use default or required/total sheets from 1 to {MAX_SHARDS}.",
                severity="error",
            )
            return
        threshold, count = counts
        self.add_files_state.signing_key_mode = "sharded"
        self.add_files_state.signing_key_recovery_threshold = None
        self.add_files_state.signing_key_recovery_count = count
        self.add_files_state.signing_key_recovery_threshold = threshold
        self.refresh_task_view()

    def _apply_replace_recovery_set(self, value: str | None) -> None:
        if value is None:
            self.refresh_task_view()
            return
        counts = parse_threshold_count(value.strip().lower())
        if counts is None:
            self.notify(QUORUM_INPUT_HELP, severity="error")
            self.refresh_task_view()
            return
        threshold, count = counts
        self.replace_recovery_docs_state.recovery_threshold = 1
        self.replace_recovery_docs_state.recovery_document_count = count
        self.replace_recovery_docs_state.recovery_threshold = threshold
        self.refresh_task_view()

    def _apply_replace_signing_key_recovery(self, value: str | None) -> None:
        if value is None:
            return
        counts = parse_threshold_count(value.strip().lower())
        if counts is None:
            self.notify(QUORUM_INPUT_HELP, severity="error")
            return
        threshold, count = counts
        self.replace_recovery_docs_state.mint_signing_key_recovery = True
        self.replace_recovery_docs_state.signing_key_recovery_threshold = None
        self.replace_recovery_docs_state.signing_key_recovery_count = None
        self.replace_recovery_docs_state.signing_key_recovery_count = count
        self.replace_recovery_docs_state.signing_key_recovery_threshold = threshold
        self.replace_recovery_docs_state.signing_key_replacement_count = None
        self.refresh_task_view()

    def _apply_replace_passphrase_replacement_count(self, value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip()
        if not normalized:
            self.replace_recovery_docs_state.passphrase_replacement_count = None
            self.refresh_task_view()
            return
        try:
            count = int(normalized)
        except ValueError:
            self.notify("Use a positive whole number.", severity="error")
            return
        if count < 1:
            self.notify("Use a positive whole number.", severity="error")
            return
        self.replace_recovery_docs_state.mint_passphrase_recovery = True
        self.replace_recovery_docs_state.passphrase_replacement_count = count
        self.refresh_task_view()

    def _apply_replace_signing_key_replacement_count(self, value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip()
        if not normalized:
            self.replace_recovery_docs_state.signing_key_replacement_count = None
            self.refresh_task_view()
            return
        try:
            count = int(normalized)
        except ValueError:
            self.notify("Use a positive whole number.", severity="error")
            return
        if count < 1:
            self.notify("Use a positive whole number.", severity="error")
            return
        self.replace_recovery_docs_state.mint_signing_key_recovery = True
        self.replace_recovery_docs_state.signing_key_recovery_threshold = None
        self.replace_recovery_docs_state.signing_key_recovery_count = None
        self.replace_recovery_docs_state.signing_key_replacement_count = count
        self.refresh_task_view()

    def _apply_layout_section(self, value: str | None) -> None:
        if value is None:
            return
        paper_size, design = parse_layout(value, fallback=self._current_layout())
        paper = cast(Literal["A4", "LETTER"], paper_size)
        if self.active_task == "backup":
            self.backup_state.paper_size = paper
            self.backup_state.design = design
        elif self.active_task == "rebuild":
            self.rebuild_state.paper_size = paper_size
            self.rebuild_state.design = design
        elif self.active_task == "replace_recovery_docs":
            self.replace_recovery_docs_state.paper_size = paper_size
            self.replace_recovery_docs_state.design = design
        elif self.active_task == "kit":
            self.kit_state.paper_size = paper
            self.kit_state.design = design
        self.refresh_task_view()

    def _apply_restore_target(self, value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip().lower()
        if normalized in {"latest", ""}:
            self.restore_state.target = "latest"
            self.restore_state.extension_index = None
            self.restore_state.extension_doc_hash = None
        elif normalized == "original":
            self.restore_state.target = "original"
            self.restore_state.extension_index = None
            self.restore_state.extension_doc_hash = None
        else:
            update_index = parse_update_index(normalized)
            if update_index is None:
                self.notify("Use latest, original, or an update number.", severity="error")
                return
            self.restore_state.target = "specific_update"
            self.restore_state.extension_index = update_index
            self.restore_state.extension_doc_hash = None
        self.refresh_task_view()

    def _apply_restore_target_fingerprint(self, value: str | None) -> None:
        if value is None:
            self.refresh_task_view()
            return
        fingerprint = value.strip()
        if not fingerprint:
            self.restore_state.extension_doc_hash = None
            self.refresh_task_view()
            return
        self.restore_state.target = "specific_update"
        self.restore_state.extension_index = None
        self.restore_state.extension_doc_hash = fingerprint
        self.refresh_task_view()

    def _apply_expected_head_fingerprint(self, value: str | None) -> None:
        if value is None:
            self.refresh_task_view()
            return
        fingerprint = value.strip() or None
        if self.active_task == "add_files":
            self.add_files_state.expected_head_doc_hash = fingerprint
            self.add_files_state.allow_stale_head = False
        elif self.active_task == "restore":
            self.restore_state.expected_head_doc_hash = fingerprint
        elif self.active_task == "rebuild":
            self.rebuild_state.expected_head_doc_hash = fingerprint
            self.rebuild_state.allow_stale_head = False
        elif self.active_task == "replace_recovery_docs":
            self.replace_recovery_docs_state.expected_head_doc_hash = fingerprint
            self.replace_recovery_docs_state.allow_stale_head = False
        self.refresh_task_view()

    def _confirm_source_freshness(self) -> None:
        if self.active_task == "add_files" and self.add_files_state.source_paths:
            self.add_files_state.allow_stale_head = True
            self.add_files_state.expected_head_doc_hash = None
            self.refresh_task_view()
            self.notify("Current backup source accepted for this update.")
        elif self.active_task == "rebuild" and self.rebuild_state.source_paths:
            self.rebuild_state.allow_stale_head = True
            self.rebuild_state.expected_head_doc_hash = None
            self.refresh_task_view()
            self.notify("Existing backup accepted for this rebuild.")
        elif (
            self.active_task == "replace_recovery_docs"
            and self.replace_recovery_docs_state.source_paths
        ):
            self.replace_recovery_docs_state.allow_stale_head = True
            self.replace_recovery_docs_state.expected_head_doc_hash = None
            self.refresh_task_view()
            self.notify("Existing backup accepted for replacement recovery sheets.")
        else:
            self.notify("Choose scanned pages before confirming freshness.", severity="warning")

    def _toggle_kit_variant(self) -> None:
        if self.active_task != "kit":
            return
        self.kit_state.variant = "scanner" if self.kit_state.variant == "lean" else "lean"
        self.refresh_task_view()

    def _current_layout(self) -> tuple[str, str]:
        if self.active_task == "rebuild":
            return self.rebuild_state.paper_size, self.rebuild_state.design
        if self.active_task == "replace_recovery_docs":
            return (
                self.replace_recovery_docs_state.paper_size,
                self.replace_recovery_docs_state.design,
            )
        if self.active_task == "kit":
            return self.kit_state.paper_size, self.kit_state.design
        return self.backup_state.paper_size, self.backup_state.design
