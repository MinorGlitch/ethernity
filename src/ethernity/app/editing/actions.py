from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, cast

from ethernity.app.app_types import SignatureTaskState
from ethernity.app.editing.specific import TaskSpecificEditingActions
from ethernity.app.workflow_registry import workflow_definition
from ethernity.formats.extension_mode import UpdateMode
from ethernity.page_sizes import resolve_paper_size
from ethernity.tasks.page_layout import with_print_layout
from ethernity.tasks.task_types import TaskKey


class TaskEditingActions(TaskSpecificEditingActions):
    """Route workspace controls to task-specific editors."""

    async def _edit_section(self, section_key: str) -> None:
        if self.active_task == "add_files" and section_key == "source":
            await self._edit_add_files_source()
        elif section_key in {"files", "source", "design"}:
            await self.action_edit_primary()
        elif section_key in {"unlock", "paper"}:
            await self.action_edit_passphrase()
        elif section_key in {"backup", "output", "backup_output"}:
            await self.action_edit_output()
        elif section_key == "recovery":
            await self._edit_recovery_section()
        elif section_key == "layout":
            await self._edit_layout_section()
        elif section_key == "target":
            await self._edit_restore_target()
        elif section_key == "freshness":
            self._confirm_source_freshness()
        elif section_key == "variant":
            self._toggle_kit_variant()
        else:
            self.notify("This field cannot be changed here.", severity="warning")

    async def _edit_next_section(self) -> None:
        validation = self._current_state().validate_task()
        for issue in validation.issues:
            if issue.section is not None:
                if issue.section == "advanced":
                    self._focus_issue(issue)
                    return
                await self._edit_section(issue.section)
                return
        for section in validation.sections:
            if section.status != "ready":
                await self._edit_section(section.key)
                return
        await self.action_review()

    async def _handle_workspace_button(self, button_id: str) -> None:
        handlers = {
            "workspace-backup-files": self.action_edit_primary,
            "workspace-restore-source": self.action_edit_primary,
            "workspace-add-files-files": self.action_edit_primary,
            "workspace-rebuild-source": self.action_edit_primary,
            "workspace-replace-source": self.action_edit_primary,
            "workspace-add-files-add-files": self._edit_add_files_input_files,
            "workspace-add-files-add-folder": self._edit_add_files_input_folder,
            "workspace-backup-output": self.action_edit_output,
            "workspace-restore-output": self.action_edit_output,
            "workspace-add-files-output": self.action_edit_output,
            "workspace-rebuild-output": self.action_edit_output,
            "workspace-replace-output": self.action_edit_output,
            "workspace-kit-output": self.action_edit_output,
            "workspace-add-files-source": self._edit_add_files_source,
            "workspace-add-files-recovery-text": self._edit_add_files_recovery_text_source,
            "workspace-add-files-payloads": self._edit_add_files_payloads_source,
            "workspace-rebuild-backup": self._edit_rebuild_backup_folder,
            "workspace-rebuild-scans": self._edit_rebuild_scans,
            "workspace-backup-passphrase": self.action_edit_passphrase,
            "workspace-backup-recovery-quorum": self._edit_recovery_section,
            "workspace-backup-base-dir": self._edit_backup_base_dir,
            "workspace-backup-qr-chunk-size": self._edit_qr_chunk_size,
            "workspace-add-files-qr-chunk-size": self._edit_qr_chunk_size,
            "workspace-rebuild-qr-chunk-size": self._edit_qr_chunk_size,
            "workspace-kit-chunk-size": self._edit_qr_chunk_size,
            "workspace-backup-signing-key-shards": self._edit_backup_signing_key_shards,
            "workspace-restore-unlock": self._edit_current_unlock,
            "workspace-add-files-unlock": self._edit_current_unlock,
            "workspace-rebuild-unlock": self._edit_current_unlock,
            "workspace-replace-unlock": self._edit_current_unlock,
            "workspace-restore-target": self._edit_restore_target,
            "workspace-restore-target-fingerprint": self._edit_restore_target_fingerprint,
            "workspace-restore-expected-head": self._edit_expected_head_fingerprint,
            "workspace-restore-recovery-text": self._edit_restore_recovery_text_source,
            "workspace-restore-payloads": self._edit_restore_payloads_source,
            "workspace-add-files-base-dir": self._edit_add_files_base_dir,
            "workspace-add-files-recovery-sheets": self._edit_add_files_recovery_sheets,
            "workspace-replace-recovery-text": self._edit_replace_recovery_text_source,
            "workspace-replace-payloads": self._edit_replace_payloads_source,
            "workspace-add-files-fingerprint": self._edit_expected_head_fingerprint,
            "workspace-rebuild-fingerprint": self._edit_expected_head_fingerprint,
            "workspace-replace-fingerprint": self._edit_expected_head_fingerprint,
            "workspace-replace-recovery": self._edit_recovery_section,
            "workspace-replace-passphrase-count": self._edit_replace_passphrase_replacement_count,
            "workspace-replace-signing-key-count": self._edit_replace_signing_key_replacement_count,
            "workspace-replace-signing-key-quorum": self._edit_replace_signing_key_recovery,
            "workspace-replace-signing-key-payloads": self._edit_replace_signing_key_payloads,
        }
        handler = handlers.get(button_id)
        if handler is not None:
            await handler()
            return
        if button_id == "workspace-backup-clear-files":
            state = self.backup_state
        elif button_id == "workspace-add-files-clear-files":
            state = self.add_files_state
        else:
            if button_id in {
                "workspace-rebuild-freshness",
                "workspace-add-files-freshness",
                "workspace-replace-freshness",
            }:
                self._confirm_source_freshness()
            else:
                self.notify("This field cannot be changed here.", severity="warning")
            return
        state.input_paths = []
        state.input_dirs = []
        self.refresh_task_view()

    async def _apply_workspace_choice(self, choice_list_id: str, choice_key: str) -> None:
        handlers = {
            "workspace-backup-recovery-method": self._choose_backup_recovery,
            "workspace-restore-target-method": self._choose_restore_target,
            "workspace-replace-recovery-method": self._choose_replacement_recovery,
        }
        handler = handlers.get(choice_list_id)
        if handler is not None:
            await handler(choice_key)
        elif choice_list_id.endswith("-unlock-method") and choice_key in {
            "passphrase",
            "recovery_documents",
            "recovery_payloads",
        }:
            await self._choose_unlock_method(choice_key)

    async def _choose_backup_recovery(self, choice_key: str) -> None:
        if choice_key in {"recommended_shards", "single_phrase", "custom_shards"}:
            if self.backup_state.recovery_method == choice_key:
                return
            self.backup_state.recovery_method = cast(
                Literal["recommended_shards", "single_phrase", "custom_shards"], choice_key
            )
            self.refresh_task_view()
            if choice_key == "custom_shards":
                await self._edit_recovery_section()

    async def _choose_restore_target(self, choice_key: str) -> None:
        if choice_key in {"latest", "original", "specific_update"}:
            self.restore_state.target = cast(
                Literal["latest", "original", "specific_update"], choice_key
            )
            if choice_key in {"latest", "original"}:
                self.restore_state.extension_index = None
                self.restore_state.extension_doc_hash = None
            self.refresh_task_view()
            if choice_key == "specific_update":
                await self._edit_restore_target()

    async def _choose_unlock_method(self, choice_key: str) -> None:
        await self._edit_unlock_choice(
            cast(Literal["passphrase", "recovery_documents", "recovery_payloads"], choice_key)
        )

    async def _choose_replacement_recovery(self, choice_key: str) -> None:
        if choice_key == "recommended":
            self.replace_recovery_docs_state.recovery_threshold = 2
            self.replace_recovery_docs_state.recovery_document_count = 3
            self.refresh_task_view()
        elif choice_key == "custom":
            await self._edit_recovery_section()

    async def _apply_workspace_select(self, select_id: str, value: str) -> None:
        if select_id == "workspace-backup-recovery-select":
            await self._apply_workspace_choice("workspace-backup-recovery-method", value)
            return
        if select_id.endswith("-paper") or select_id == "workspace-backup-paper-size":
            changed = await self._set_workspace_paper(value)
        elif select_id.endswith("-design"):
            changed = await self._set_workspace_design(value)
        else:
            handlers = {
                "workspace-kit-variant-select": self._set_kit_variant,
                "workspace-backup-signing-key-mode": self._set_backup_signing_mode,
                "workspace-backup-passphrase-words": self._set_backup_phrase_words,
                "workspace-restore-auth-policy": self._set_restore_auth_policy,
                "workspace-restore-signature-source": self._set_restore_signature_source,
                "workspace-add-files-update-mode": self._set_update_mode,
                "workspace-add-files-signature-source": self._set_add_files_signature_source,
                "workspace-rebuild-signature-source": self._set_rebuild_signature_source,
                "workspace-replace-signing-key-select": self._set_replacement_signing_mode,
                "workspace-replace-passphrase-select": self._set_replacement_passphrase_mode,
            }
            handler = handlers.get(select_id)
            changed = await handler(value) if handler is not None else True
        if changed:
            self.refresh_task_view()

    async def _set_workspace_paper(self, value: str) -> bool:
        paper = resolve_paper_size(value).name
        current_paper, design = self._current_layout()
        if paper == current_paper:
            return False
        current = self._current_state()
        state = with_print_layout(
            current, paper_size=paper, design=getattr(current, "design", design)
        )
        setattr(self, workflow_definition(self.active_task).state_attribute, state)
        return True

    async def _set_workspace_design(self, value: str) -> bool:
        paper, current_design = self._current_layout()
        if value == current_design:
            return False
        current = self._current_state()
        state = with_print_layout(
            current, paper_size=getattr(current, "paper_size", paper), design=value
        )
        setattr(self, workflow_definition(self.active_task).state_attribute, state)
        return True

    async def _set_kit_variant(self, value: str) -> bool:
        if value == self.kit_state.variant:
            return False
        self.kit_state.variant = cast(Literal["lean", "scanner"], value)
        return True

    async def _set_backup_signing_mode(self, value: str) -> bool:
        if value == (self.backup_state.signing_key_mode or "embedded"):
            return False
        self.backup_state.signing_key_mode = cast(Literal["embedded", "sharded"], value)
        if value == "embedded":
            self.backup_state.signing_key_shard_threshold = None
            self.backup_state.signing_key_shard_count = None
        return True

    async def _set_backup_phrase_words(self, value: str) -> bool:
        words = None if value == "default" else int(value)
        if words == self.backup_state.passphrase_words:
            return False
        if value == "default":
            self.backup_state.passphrase_words = None
        else:
            self.backup_state.passphrase = None
            self.backup_state.passphrase_words = words
        return True

    async def _set_restore_auth_policy(self, value: str) -> bool:
        allow_unsigned = value == "allow-unsigned"
        if self.restore_state.allow_unsigned == allow_unsigned:
            return False
        self.restore_state.allow_unsigned = allow_unsigned
        self._source_changed("restore")
        return False

    async def _set_restore_signature_source(self, value: str) -> bool:
        return await self._set_signature_source(
            self.restore_state,
            value,
            "restore",
            self._edit_restore_auth_text_source,
            self._edit_restore_auth_payloads_source,
        )

    async def _set_update_mode(self, value: str) -> bool:
        source = self.add_files_state.current_source_assessment()
        if source is not None and source.has_updates:
            return False
        mode = UpdateMode(value)
        if mode == self.add_files_state.resolved_update_mode():
            return False
        self.add_files_state.update_mode = mode
        return True

    async def _set_add_files_signature_source(self, value: str) -> bool:
        return await self._set_signature_source(
            self.add_files_state,
            value,
            "add_files",
            self._edit_add_files_auth_text_source,
            self._edit_add_files_auth_payloads_source,
        )

    async def _set_rebuild_signature_source(self, value: str) -> bool:
        return await self._set_signature_source(
            self.rebuild_state,
            value,
            "rebuild",
            self._edit_rebuild_auth_text_source,
            self._edit_rebuild_auth_payloads_source,
        )

    async def _set_replacement_signing_mode(self, value: str) -> bool:
        current_signing = (
            "off"
            if not self.replace_recovery_docs_state.create_signing_key_recovery
            else "replace"
            if self.replace_recovery_docs_state.signing_key_replacement_count is not None
            else "custom"
            if self.replace_recovery_docs_state.signing_key_recovery_threshold is not None
            else "same"
        )
        if value == current_signing:
            return False
        if value == "off":
            self.replace_recovery_docs_state.create_signing_key_recovery = False
            self.replace_recovery_docs_state.signing_key_recovery_threshold = None
            self.replace_recovery_docs_state.signing_key_recovery_count = None
            self.replace_recovery_docs_state.signing_key_replacement_count = None
        elif value == "same":
            self.replace_recovery_docs_state.create_signing_key_recovery = True
            self.replace_recovery_docs_state.signing_key_recovery_threshold = None
            self.replace_recovery_docs_state.signing_key_recovery_count = None
            self.replace_recovery_docs_state.signing_key_replacement_count = None
        elif value == "custom":
            await self._edit_replace_signing_key_recovery()
        elif value == "replace":
            await self._edit_replace_signing_key_replacement_count()
        return True

    async def _set_replacement_passphrase_mode(self, value: str) -> bool:
        current_passphrase = (
            "off"
            if not self.replace_recovery_docs_state.create_passphrase_recovery
            else "replace"
            if self.replace_recovery_docs_state.passphrase_replacement_count is not None
            else "create"
        )
        if value == current_passphrase:
            return False
        if value == "off":
            self.replace_recovery_docs_state.create_passphrase_recovery = False
            self.replace_recovery_docs_state.passphrase_replacement_count = None
        elif value == "create":
            self.replace_recovery_docs_state.create_passphrase_recovery = True
            self.replace_recovery_docs_state.passphrase_replacement_count = None
        elif value == "replace":
            await self._edit_replace_passphrase_replacement_count()
        return True

    async def _set_signature_source(
        self,
        state: SignatureTaskState,
        value: str,
        task: TaskKey,
        edit_text: Callable[[], Awaitable[None]],
        edit_payloads: Callable[[], Awaitable[None]],
    ) -> bool:
        current = (
            "text"
            if state.auth_text_file is not None
            else ("payloads" if state.auth_payloads_file is not None else "auto")
        )
        if value == current:
            return False
        if value == "auto":
            state.auth_text_file = None
            state.auth_payloads_file = None
            self._source_changed(task)
            return False
        if value == "text":
            await edit_text()
        elif value == "payloads":
            await edit_payloads()
        return True
