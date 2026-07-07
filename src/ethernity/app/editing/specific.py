from __future__ import annotations

from ethernity.app.editing.primary import PrimaryEditingActions
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.tasks.quorum import MAX_SHARDS

QUORUM_PROMPT = f"threshold/count from 1 to {MAX_SHARDS}, such as 2/3"


class TaskSpecificEditingActions(PrimaryEditingActions):
    async def _edit_add_files_current_source(self) -> None:
        await self._pick_paths(
            title="Current backup source",
            prompt="Choose latest backup scans, PDFs, images, or folders.",
            selected_paths=self.add_files_state.source_paths,
            callback=self._apply_add_files_sources_picked,
        )

    async def _edit_add_files_base_dir(self) -> None:
        await self._pick_paths(
            title="Update base folder",
            prompt="Choose the folder new paths should be relative to.",
            selected_paths=(
                (self.add_files_state.base_dir,) if self.add_files_state.base_dir else ()
            ),
            callback=self._apply_add_files_base_dir_picked,
            allow_files=False,
            multiple=False,
        )

    async def _edit_add_files_recovery_documents(self) -> None:
        value = "default"
        if (
            self.add_files_state.recovery_document_threshold is not None
            and self.add_files_state.recovery_document_count is not None
        ):
            value = (
                f"{self.add_files_state.recovery_document_threshold}/"
                f"{self.add_files_state.recovery_document_count}"
            )
        elif self.add_files_state.recovery_document_count == 0:
            value = "none"
        await self.push_screen(
            EditFieldScreen(
                title="Update recovery documents",
                prompt=f"Use default, none, or {QUORUM_PROMPT}",
                value=value,
                placeholder="default",
            ),
            self._apply_add_files_recovery_documents,
        )

    async def _edit_add_files_signing_key_shards(self) -> None:
        value = "default"
        if (
            self.add_files_state.signing_key_recovery_threshold is not None
            and self.add_files_state.signing_key_recovery_count is not None
        ):
            value = (
                f"{self.add_files_state.signing_key_recovery_threshold}/"
                f"{self.add_files_state.signing_key_recovery_count}"
            )
        await self.push_screen(
            EditFieldScreen(
                title="Update signing key shards",
                prompt=f"Use default or {QUORUM_PROMPT}",
                value=value,
                placeholder="default",
            ),
            self._apply_add_files_signing_key_shards,
        )

    async def _edit_backup_base_dir(self) -> None:
        await self._pick_paths(
            title="Backup base folder",
            prompt="Choose the folder paths should be relative to.",
            selected_paths=(self.backup_state.base_dir,) if self.backup_state.base_dir else (),
            callback=self._apply_backup_base_dir_picked,
            allow_files=False,
            multiple=False,
        )

    async def _edit_backup_signing_key_shards(self) -> None:
        threshold = (
            self.backup_state.signing_key_shard_threshold or self.backup_state.shard_threshold
        )
        count = self.backup_state.signing_key_shard_count or self.backup_state.shard_count
        await self.push_screen(
            EditFieldScreen(
                title="Signing key shards",
                prompt=f"Signing key {QUORUM_PROMPT}",
                value=f"{threshold}/{count}",
                placeholder="2/3",
            ),
            self._apply_backup_signing_key_shards,
        )

    async def _edit_qr_chunk_size(self) -> None:
        if self.active_task == "backup":
            value = self.backup_state.qr_chunk_size
        elif self.active_task == "add_files":
            value = self.add_files_state.qr_chunk_size
        elif self.active_task == "rebuild":
            value = self.rebuild_state.qr_chunk_size
        elif self.active_task == "kit":
            value = self.kit_state.chunk_size
        else:
            self.notify("This workflow uses the saved QR chunk size.")
            return
        await self.push_screen(
            EditFieldScreen(
                title="QR chunk size",
                prompt="Payload bytes per QR chunk. Leave blank for saved default.",
                value=str(value) if value is not None else "",
                placeholder="saved default",
            ),
            self._apply_qr_chunk_size,
        )

    async def _edit_restore_recovery_text_source(self) -> None:
        await self._pick_paths(
            title="Recovery text source",
            prompt="Choose the recovery text file to restore from.",
            selected_paths=(
                (self.restore_state.recovery_text_file,)
                if self.restore_state.recovery_text_file is not None
                else ()
            ),
            callback=self._apply_restore_recovery_text_picked,
            allow_dirs=False,
            multiple=False,
        )

    async def _edit_restore_payloads_source(self) -> None:
        await self._pick_paths(
            title="Payload source",
            prompt="Choose the payload file to restore from.",
            selected_paths=(
                (self.restore_state.payloads_file,)
                if self.restore_state.payloads_file is not None
                else ()
            ),
            callback=self._apply_restore_payloads_picked,
            allow_dirs=False,
            multiple=False,
        )

    async def _edit_restore_auth_text_source(self) -> None:
        await self._pick_paths(
            title="Authentication text",
            prompt="Choose the authentication recovery text file.",
            selected_paths=(
                (self.restore_state.auth_text_file,)
                if self.restore_state.auth_text_file is not None
                else ()
            ),
            callback=self._apply_restore_auth_text_picked,
            allow_dirs=False,
            multiple=False,
        )

    async def _edit_restore_auth_payloads_source(self) -> None:
        await self._pick_paths(
            title="Authentication payloads",
            prompt="Choose the authentication payload file.",
            selected_paths=(
                (self.restore_state.auth_payloads_file,)
                if self.restore_state.auth_payloads_file is not None
                else ()
            ),
            callback=self._apply_restore_auth_payloads_picked,
            allow_dirs=False,
            multiple=False,
        )

    async def _edit_rebuild_auth_text_source(self) -> None:
        await self._pick_paths(
            title="Authentication text",
            prompt="Choose the authentication recovery text file.",
            selected_paths=(
                (self.rebuild_state.auth_text_file,)
                if self.rebuild_state.auth_text_file is not None
                else ()
            ),
            callback=self._apply_rebuild_auth_text_picked,
            allow_dirs=False,
            multiple=False,
        )

    async def _edit_rebuild_auth_payloads_source(self) -> None:
        await self._pick_paths(
            title="Authentication payloads",
            prompt="Choose the authentication payload file.",
            selected_paths=(
                (self.rebuild_state.auth_payloads_file,)
                if self.rebuild_state.auth_payloads_file is not None
                else ()
            ),
            callback=self._apply_rebuild_auth_payloads_picked,
            allow_dirs=False,
            multiple=False,
        )

    async def _edit_replace_recovery_text_source(self) -> None:
        await self._pick_paths(
            title="Recovery text source",
            prompt="Choose the existing backup recovery text file.",
            selected_paths=(
                (self.replace_recovery_docs_state.recovery_text_file,)
                if self.replace_recovery_docs_state.recovery_text_file is not None
                else ()
            ),
            callback=self._apply_replace_recovery_text_picked,
            allow_dirs=False,
            multiple=False,
        )

    async def _edit_replace_payloads_source(self) -> None:
        await self._pick_paths(
            title="Payload source",
            prompt="Choose the existing backup payload file.",
            selected_paths=(
                (self.replace_recovery_docs_state.payloads_file,)
                if self.replace_recovery_docs_state.payloads_file is not None
                else ()
            ),
            callback=self._apply_replace_payloads_picked,
            allow_dirs=False,
            multiple=False,
        )

    async def _edit_replace_signing_key_payloads(self) -> None:
        await self._pick_paths(
            title="Signing key recovery payloads",
            prompt="Choose existing signing-key recovery payload files.",
            selected_paths=self.replace_recovery_docs_state.signing_key_recovery_payload_files,
            callback=self._apply_replace_signing_key_payloads_picked,
            allow_dirs=False,
        )

    async def _edit_replace_passphrase_replacement_count(self) -> None:
        value = self.replace_recovery_docs_state.passphrase_replacement_count
        await self.push_screen(
            EditFieldScreen(
                title="Passphrase replacement count",
                prompt="How many existing passphrase recovery documents to replace.",
                value=str(value) if value is not None else "",
                placeholder="1",
            ),
            self._apply_replace_passphrase_replacement_count,
        )

    async def _edit_replace_signing_key_replacement_count(self) -> None:
        value = self.replace_recovery_docs_state.signing_key_replacement_count
        await self.push_screen(
            EditFieldScreen(
                title="Signing key replacement count",
                prompt="How many existing signing-key recovery documents to replace.",
                value=str(value) if value is not None else "",
                placeholder="1",
            ),
            self._apply_replace_signing_key_replacement_count,
        )

    async def _edit_recovery_section(self) -> None:
        if self.active_task == "backup":
            if self.backup_state.recovery_method == "single_phrase":
                value = "single"
            else:
                value = f"{self.backup_state.shard_threshold}/{self.backup_state.shard_count}"
            await self.push_screen(
                EditFieldScreen(
                    title="Recovery method",
                    prompt=f"Use recommended, single, or {QUORUM_PROMPT}",
                    value=value,
                    placeholder="recommended",
                ),
                self._apply_backup_recovery,
            )
        elif self.active_task == "replace_recovery_docs":
            await self.push_screen(
                EditFieldScreen(
                    title="New recovery set",
                    prompt=f"Recovery {QUORUM_PROMPT}",
                    value=(
                        f"{self.replace_recovery_docs_state.recovery_threshold}/"
                        f"{self.replace_recovery_docs_state.recovery_document_count}"
                    ),
                    placeholder="2/3",
                ),
                self._apply_replace_recovery_set,
            )

    async def _edit_replace_signing_key_recovery(self) -> None:
        state = self.replace_recovery_docs_state
        threshold = state.signing_key_recovery_threshold or state.recovery_threshold
        count = state.signing_key_recovery_count or state.recovery_document_count
        await self.push_screen(
            EditFieldScreen(
                title="Signing key recovery",
                prompt=f"Signing key recovery {QUORUM_PROMPT}",
                value=f"{threshold}/{count}",
                placeholder="2/3",
            ),
            self._apply_replace_signing_key_recovery,
        )

    async def _edit_layout_section(self) -> None:
        paper_size, design = self._current_layout()
        await self.push_screen(
            EditFieldScreen(
                title="Print layout",
                prompt="Paper and design, for example A4 sentinel or LETTER forge",
                value=f"{paper_size} {design}",
                placeholder="A4 sentinel",
            ),
            self._apply_layout_section,
        )

    async def _edit_restore_target(self) -> None:
        if self.active_task != "restore":
            self.notify("Review will show this value before anything runs.")
            return
        value: str = self.restore_state.target
        if self.restore_state.target == "specific_update" and self.restore_state.extension_index:
            value = f"update {self.restore_state.extension_index}"
        await self.push_screen(
            EditFieldScreen(
                title="Restore target",
                prompt="Restore latest, original, or update number",
                value=value,
                placeholder="latest",
            ),
            self._apply_restore_target,
        )

    async def _edit_restore_target_fingerprint(self) -> None:
        if self.active_task != "restore":
            self.notify("Review will show this value before anything runs.")
            return
        await self.push_screen(
            EditFieldScreen(
                title="Restore target fingerprint",
                prompt="Paste the backup update fingerprint to restore.",
                value=self.restore_state.extension_doc_hash or "",
                placeholder="doc fingerprint",
            ),
            self._apply_restore_target_fingerprint,
        )

    async def _edit_expected_head_fingerprint(self) -> None:
        if self.active_task == "add_files":
            value = self.add_files_state.expected_head_doc_hash or ""
        elif self.active_task == "restore":
            value = self.restore_state.expected_head_doc_hash or ""
        elif self.active_task == "rebuild":
            value = self.rebuild_state.expected_head_doc_hash or ""
        elif self.active_task == "replace_recovery_docs":
            value = self.replace_recovery_docs_state.expected_head_doc_hash or ""
        else:
            self.notify("Choose backup scans before setting a fingerprint.", severity="warning")
            return
        await self.push_screen(
            EditFieldScreen(
                title="Expected latest backup fingerprint",
                prompt="Paste the latest backup fingerprint for these scans.",
                value=value,
                placeholder="doc fingerprint",
            ),
            self._apply_expected_head_fingerprint,
        )
