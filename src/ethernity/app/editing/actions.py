from __future__ import annotations

from typing import Literal, cast

from ethernity.app.editing.specific import TaskSpecificEditingActions
from ethernity.page_sizes import resolve_paper_size
from ethernity.tasks.add_files import AddFilesSigningKeyMode, AddFilesUnlockPolicy


class TaskEditingActions(TaskSpecificEditingActions):
    """Route workspace controls to task-specific editors."""

    async def _edit_section(self, section_key: str) -> None:
        if self.active_task == "add_files" and section_key == "source":
            await self._edit_add_files_current_source()
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
        if button_id in {
            "workspace-backup-files",
            "workspace-restore-source",
            "workspace-add-files-files",
            "workspace-rebuild-source",
            "workspace-replace-source",
        }:
            await self.action_edit_primary()
        elif button_id == "workspace-backup-clear-files":
            self.backup_state.input_paths = []
            self.backup_state.input_dirs = []
            self.refresh_task_view()
        elif button_id == "workspace-add-files-clear-files":
            self.add_files_state.input_paths = []
            self.add_files_state.input_dirs = []
            self.refresh_task_view()
        elif button_id == "workspace-add-files-add-files":
            await self._edit_add_files_input_files()
        elif button_id == "workspace-add-files-add-folder":
            await self._edit_add_files_input_folder()
        elif button_id in {
            "workspace-backup-output",
            "workspace-restore-output",
            "workspace-add-files-output",
            "workspace-rebuild-output",
            "workspace-replace-output",
            "workspace-kit-output",
        }:
            await self.action_edit_output()
        elif button_id == "workspace-add-files-backup":
            await self._edit_add_files_backup_folder()
        elif button_id == "workspace-rebuild-backup":
            await self._edit_rebuild_backup_folder()
        elif button_id == "workspace-rebuild-scans":
            await self._edit_rebuild_scans()
        elif button_id == "workspace-backup-passphrase":
            await self.action_edit_passphrase()
        elif button_id == "workspace-backup-base-dir":
            await self._edit_backup_base_dir()
        elif button_id in {
            "workspace-backup-qr-chunk-size",
            "workspace-add-files-qr-chunk-size",
            "workspace-rebuild-qr-chunk-size",
            "workspace-kit-chunk-size",
        }:
            await self._edit_qr_chunk_size()
        elif button_id == "workspace-backup-signing-key-shards":
            await self._edit_backup_signing_key_shards()
        elif button_id in {
            "workspace-restore-unlock",
            "workspace-add-files-unlock",
            "workspace-rebuild-unlock",
            "workspace-replace-unlock",
        }:
            await self._edit_current_unlock()
        elif button_id == "workspace-restore-target":
            await self._edit_restore_target()
        elif button_id == "workspace-restore-target-fingerprint":
            await self._edit_restore_target_fingerprint()
        elif button_id == "workspace-restore-expected-head":
            await self._edit_expected_head_fingerprint()
        elif button_id == "workspace-restore-recovery-text":
            await self._edit_restore_recovery_text_source()
        elif button_id == "workspace-restore-payloads":
            await self._edit_restore_payloads_source()
        elif button_id == "workspace-add-files-source":
            await self._edit_add_files_current_source()
        elif button_id == "workspace-add-files-base-dir":
            await self._edit_add_files_base_dir()
        elif button_id == "workspace-replace-recovery-text":
            await self._edit_replace_recovery_text_source()
        elif button_id == "workspace-replace-payloads":
            await self._edit_replace_payloads_source()
        elif button_id in {
            "workspace-add-files-freshness",
            "workspace-rebuild-freshness",
            "workspace-replace-freshness",
        }:
            self._confirm_source_freshness()
        elif button_id in {
            "workspace-add-files-fingerprint",
            "workspace-rebuild-fingerprint",
            "workspace-replace-fingerprint",
        }:
            await self._edit_expected_head_fingerprint()
        elif button_id == "workspace-replace-recovery":
            await self._edit_recovery_section()
        elif button_id == "workspace-replace-passphrase-count":
            await self._edit_replace_passphrase_replacement_count()
        elif button_id == "workspace-replace-signing-key-count":
            await self._edit_replace_signing_key_replacement_count()
        elif button_id == "workspace-replace-signing-key-quorum":
            await self._edit_replace_signing_key_recovery()
        elif button_id == "workspace-replace-signing-key-payloads":
            await self._edit_replace_signing_key_payloads()
        else:
            self.notify("This field cannot be changed here.", severity="warning")

    async def _apply_workspace_choice(self, choice_list_id: str, choice_key: str) -> None:
        if choice_list_id == "workspace-backup-recovery-method":
            if choice_key in {"recommended_shards", "single_phrase", "custom_shards"}:
                self.backup_state.recovery_method = cast(
                    Literal["recommended_shards", "single_phrase", "custom_shards"],
                    choice_key,
                )
                self.refresh_task_view()
                if choice_key == "custom_shards":
                    await self._edit_recovery_section()
        elif choice_list_id == "workspace-restore-target-method":
            if choice_key in {"latest", "original", "specific_update"}:
                self.restore_state.target = cast(
                    Literal["latest", "original", "specific_update"],
                    choice_key,
                )
                if choice_key in {"latest", "original"}:
                    self.restore_state.extension_index = None
                    self.restore_state.extension_doc_hash = None
                self.refresh_task_view()
                if choice_key == "specific_update":
                    await self._edit_restore_target()
        elif choice_list_id.endswith("-unlock-method") and choice_key in {
            "passphrase",
            "recovery_documents",
            "recovery_payloads",
        }:
            await self._edit_unlock_choice(
                cast(
                    Literal["passphrase", "recovery_documents", "recovery_payloads"],
                    choice_key,
                )
            )
        elif choice_list_id == "workspace-replace-recovery-method":
            if choice_key == "recommended":
                self.replace_recovery_docs_state.recovery_threshold = 2
                self.replace_recovery_docs_state.recovery_document_count = 3
                self.refresh_task_view()
            elif choice_key == "custom":
                await self._edit_recovery_section()

    async def _apply_workspace_select(self, select_id: str, value: str) -> None:
        if select_id.endswith("-paper"):
            paper = resolve_paper_size(value).name
            if self.active_task == "backup":
                self.backup_state.paper_size = paper
            elif self.active_task == "add_files":
                self.add_files_state.paper_size = paper
            elif self.active_task == "rebuild":
                self.rebuild_state.paper_size = paper
            elif self.active_task == "replace_recovery_docs":
                self.replace_recovery_docs_state.paper_size = paper
            elif self.active_task == "kit":
                self.kit_state.paper_size = paper
        elif select_id.endswith("-design"):
            if self.active_task == "backup":
                self.backup_state.design = value
            elif self.active_task == "add_files":
                self.add_files_state.design = value
            elif self.active_task == "rebuild":
                self.rebuild_state.design = value
            elif self.active_task == "replace_recovery_docs":
                self.replace_recovery_docs_state.design = value
            elif self.active_task == "kit":
                self.kit_state.design = value
        elif select_id == "workspace-kit-variant-select":
            self.kit_state.variant = cast(Literal["lean", "scanner"], value)
        elif select_id == "workspace-backup-signing-key-mode":
            self.backup_state.signing_key_mode = cast(Literal["embedded", "sharded"], value)
            if value == "embedded":
                self.backup_state.signing_key_shard_threshold = None
                self.backup_state.signing_key_shard_count = None
        elif select_id == "workspace-backup-passphrase-words":
            if value == "default":
                self.backup_state.passphrase_words = None
            else:
                self.backup_state.passphrase = None
                self.backup_state.passphrase_words = int(value)
        elif select_id == "workspace-restore-auth-policy":
            allow_unsigned = value == "allow-unsigned"
            if self.restore_state.allow_unsigned == allow_unsigned:
                return
            self.restore_state.allow_unsigned = allow_unsigned
            self._source_changed("restore")
            return
        elif select_id == "workspace-restore-auth-material":
            current_auth_material = (
                "text"
                if self.restore_state.auth_text_file is not None
                else "payloads"
                if self.restore_state.auth_payloads_file is not None
                else "auto"
            )
            if value == current_auth_material:
                return
            if value == "auto":
                self.restore_state.auth_text_file = None
                self.restore_state.auth_payloads_file = None
                self._source_changed("restore")
                return
            elif value == "text":
                await self._edit_restore_auth_text_source()
            elif value == "payloads":
                await self._edit_restore_auth_payloads_source()
        elif select_id == "workspace-restore-resource-policy":
            enabled = value == "resource-intensive-compatibility"
            if self.restore_state.resource_intensive_compatibility_recovery == enabled:
                return
            self.restore_state.resource_intensive_compatibility_recovery = enabled
            self._source_changed("restore")
            return
        elif select_id == "workspace-rebuild-auth-material":
            current_auth_material = (
                "text"
                if self.rebuild_state.auth_text_file is not None
                else "payloads"
                if self.rebuild_state.auth_payloads_file is not None
                else "auto"
            )
            if value == current_auth_material:
                return
            if value == "auto":
                self.rebuild_state.auth_text_file = None
                self.rebuild_state.auth_payloads_file = None
                self._source_changed("rebuild")
                return
            elif value == "text":
                await self._edit_rebuild_auth_text_source()
            elif value == "payloads":
                await self._edit_rebuild_auth_payloads_source()
        elif select_id == "workspace-add-files-unlock-policy":
            self.add_files_state.unlock_policy = (
                None if value == "default" else cast(AddFilesUnlockPolicy, value)
            )
            if value == "reuse-root":
                self.add_files_state.recovery_document_threshold = None
                self.add_files_state.recovery_document_count = None
        elif select_id == "workspace-add-files-recovery-docs":
            current_recovery = (
                "original"
                if self.add_files_state.recovery_document_count == 0
                else "custom"
                if self.add_files_state.recovery_document_threshold is not None
                else "default"
            )
            if value == current_recovery:
                return
            if value == "default":
                self.add_files_state.recovery_document_threshold = None
                self.add_files_state.recovery_document_count = None
            elif value == "original":
                self.add_files_state.unlock_policy = "reuse-root"
                self.add_files_state.recovery_document_threshold = None
                self.add_files_state.recovery_document_count = 0
            elif value == "custom":
                await self._edit_add_files_recovery_documents()
        elif select_id == "workspace-add-files-signing-key-mode":
            current_signing = (
                "default"
                if self.add_files_state.signing_key_mode is None
                else "custom"
                if self.add_files_state.signing_key_recovery_threshold is not None
                else self.add_files_state.signing_key_mode
            )
            if value == current_signing:
                return
            if value == "default":
                self.add_files_state.signing_key_mode = None
                self.add_files_state.signing_key_recovery_threshold = None
                self.add_files_state.signing_key_recovery_count = None
            elif value == "not-stored":
                self.add_files_state.signing_key_mode = "not-stored"
                self.add_files_state.signing_key_recovery_threshold = None
                self.add_files_state.signing_key_recovery_count = None
            elif value == "sharded":
                self.add_files_state.signing_key_mode = cast(AddFilesSigningKeyMode, value)
                self.add_files_state.signing_key_recovery_threshold = None
                self.add_files_state.signing_key_recovery_count = None
            elif value == "custom":
                await self._edit_add_files_signing_key_shards()
        elif select_id == "workspace-replace-signing-key-select":
            current_signing = (
                "off"
                if not self.replace_recovery_docs_state.mint_signing_key_recovery
                else "replace"
                if self.replace_recovery_docs_state.signing_key_replacement_count is not None
                else "custom"
                if self.replace_recovery_docs_state.signing_key_recovery_threshold is not None
                else "same"
            )
            if value == current_signing:
                return
            if value == "off":
                self.replace_recovery_docs_state.mint_signing_key_recovery = False
                self.replace_recovery_docs_state.signing_key_recovery_threshold = None
                self.replace_recovery_docs_state.signing_key_recovery_count = None
                self.replace_recovery_docs_state.signing_key_replacement_count = None
            elif value == "same":
                self.replace_recovery_docs_state.mint_signing_key_recovery = True
                self.replace_recovery_docs_state.signing_key_recovery_threshold = None
                self.replace_recovery_docs_state.signing_key_recovery_count = None
                self.replace_recovery_docs_state.signing_key_replacement_count = None
            elif value == "custom":
                await self._edit_replace_signing_key_recovery()
            elif value == "replace":
                await self._edit_replace_signing_key_replacement_count()
        elif select_id == "workspace-replace-passphrase-select":
            current_passphrase = (
                "off"
                if not self.replace_recovery_docs_state.mint_passphrase_recovery
                else "replace"
                if self.replace_recovery_docs_state.passphrase_replacement_count is not None
                else "create"
            )
            if value == current_passphrase:
                return
            if value == "off":
                self.replace_recovery_docs_state.mint_passphrase_recovery = False
                self.replace_recovery_docs_state.passphrase_replacement_count = None
            elif value == "create":
                self.replace_recovery_docs_state.mint_passphrase_recovery = True
                self.replace_recovery_docs_state.passphrase_replacement_count = None
            elif value == "replace":
                await self._edit_replace_passphrase_replacement_count()
        self.refresh_task_view()
