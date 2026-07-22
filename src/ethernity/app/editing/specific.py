from __future__ import annotations

from ethernity.app.editing.primary import PrimaryEditingActions
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerMode
from ethernity.app.screens.paste_text import PasteTextScreen
from ethernity.tasks.quorum import MAX_SHARDS

QUORUM_VALUE = "required/total, for example 2/3"
QUORUM_RANGE = f"Each value must be 1 to {MAX_SHARDS}, and required cannot exceed total."
QUORUM_PROMPT = f"Enter {QUORUM_VALUE}. {QUORUM_RANGE}"
INTEGER_MASK = "0000000000"
QUORUM_MASK = "00/00"


class TaskSpecificEditingActions(PrimaryEditingActions):
    async def _edit_add_files_input_files(self) -> None:
        await self._pick_paths(
            title="Files to add or replace",
            prompt="Select individual files to add or replace in the backup.",
            selected_paths=self.add_files_state.input_paths,
            callback=self._mutation_port._apply_add_files_input_files_picked,
            mode=FilePickerMode.OPEN_FILES,
        )

    async def _edit_add_files_input_folder(self) -> None:
        await self._pick_paths(
            title="Folder to add or replace",
            prompt="Select one folder to add to the current selection.",
            selected_paths=(),
            callback=self._mutation_port._apply_add_files_input_folder_picked,
            mode=FilePickerMode.OPEN_DIRECTORY,
            allow_clear=False,
        )

    async def _edit_add_files_current_source(self) -> None:
        await self._pick_paths(
            title="Scanned backup pages",
            prompt="Load scanned pages from PDFs, images, or folders.",
            selected_paths=self.add_files_state.source_paths,
            callback=self._mutation_port._apply_add_files_sources_picked,
        )

    async def _edit_rebuild_backup_folder(self) -> None:
        await self._pick_paths(
            title="Backup folder",
            prompt="Select the backup folder to rebuild.",
            selected_paths=(
                (self.rebuild_state.backup_folder,)
                if self.rebuild_state.backup_folder is not None
                else ()
            ),
            callback=self._mutation_port._apply_rebuild_backup_picked,
            mode=FilePickerMode.OPEN_DIRECTORY,
        )

    async def _edit_rebuild_scans(self) -> None:
        await self._pick_paths(
            title="Scanned backup pages",
            prompt="Load scanned pages from PDFs, images, or folders.",
            selected_paths=self.rebuild_state.source_paths,
            callback=self._mutation_port._apply_rebuild_scans_picked,
        )

    async def _edit_add_files_base_dir(self) -> None:
        await self._pick_paths(
            title="Update base folder",
            prompt="Choose the folder new paths should be relative to.",
            selected_paths=(
                (self.add_files_state.base_dir,) if self.add_files_state.base_dir else ()
            ),
            callback=self._mutation_port._apply_add_files_base_dir_picked,
            mode=FilePickerMode.OPEN_DIRECTORY,
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
            value = "original"
        await self.push_screen(
            EditFieldScreen(
                title="Update recovery sheets",
                prompt=f"Enter default, original, or {QUORUM_VALUE}. {QUORUM_RANGE}",
                value=value,
                placeholder="default",
            ),
            self._mutation_port._apply_add_files_recovery_documents,
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
                title="Update signing-key sheets",
                prompt=f"Enter default or {QUORUM_VALUE}. {QUORUM_RANGE}",
                value=value,
                placeholder="default",
            ),
            self._mutation_port._apply_add_files_signing_key_shards,
        )

    async def _edit_backup_base_dir(self) -> None:
        await self._pick_paths(
            title="Backup base folder",
            prompt="Choose the folder paths should be relative to.",
            selected_paths=(self.backup_state.base_dir,) if self.backup_state.base_dir else (),
            callback=self._mutation_port._apply_backup_base_dir_picked,
            mode=FilePickerMode.OPEN_DIRECTORY,
        )

    async def _edit_backup_signing_key_shards(self) -> None:
        threshold = (
            self.backup_state.signing_key_shard_threshold or self.backup_state.shard_threshold
        )
        count = self.backup_state.signing_key_shard_count or self.backup_state.shard_count
        await self.push_screen(
            EditFieldScreen(
                title="Signing-key sheets",
                prompt=QUORUM_PROMPT,
                value=f"{threshold}/{count}",
                placeholder="2/3",
                mask_template=QUORUM_MASK,
            ),
            self._mutation_port._apply_backup_signing_key_shards,
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
            self.notify("QR density is fixed for this workflow.")
            return
        await self.push_screen(
            EditFieldScreen(
                title="QR density",
                prompt="Bytes per QR code. Blank uses the saved default.",
                value=str(value) if value is not None else "",
                placeholder="512",
                mask_template=INTEGER_MASK,
            ),
            self._mutation_port._apply_qr_chunk_size,
        )

    async def _edit_restore_recovery_text_source(self) -> None:
        await self.push_screen(
            PasteTextScreen(
                title="Recovery text",
                prompt="Paste the MAIN block from a recovery sheet.",
                value=self.restore_state.recovery_text or "",
                placeholder="Paste the MAIN block here.",
            ),
            self._mutation_port._apply_restore_recovery_text,
        )

    async def _edit_restore_payloads_source(self) -> None:
        await self._pick_paths(
            title="Backup payload file",
            prompt="Use a payload exported from backup documents.",
            selected_paths=(
                (self.restore_state.payloads_file,)
                if self.restore_state.payloads_file is not None
                else ()
            ),
            callback=self._mutation_port._apply_restore_payloads_picked,
            mode=FilePickerMode.OPEN_FILES,
            multiple=False,
        )

    async def _edit_restore_auth_text_source(self) -> None:
        await self._pick_paths(
            title="Signature text file",
            prompt="Use a text file containing the AUTH block from a recovery sheet.",
            selected_paths=(
                (self.restore_state.auth_text_file,)
                if self.restore_state.auth_text_file is not None
                else ()
            ),
            callback=self._mutation_port._apply_restore_auth_text_picked,
            mode=FilePickerMode.OPEN_FILES,
            multiple=False,
        )

    async def _edit_restore_auth_payloads_source(self) -> None:
        await self._pick_paths(
            title="Signature payload file",
            prompt="Use an AUTH payload exported from backup documents.",
            selected_paths=(
                (self.restore_state.auth_payloads_file,)
                if self.restore_state.auth_payloads_file is not None
                else ()
            ),
            callback=self._mutation_port._apply_restore_auth_payloads_picked,
            mode=FilePickerMode.OPEN_FILES,
            multiple=False,
        )

    async def _edit_rebuild_auth_text_source(self) -> None:
        await self._pick_paths(
            title="Signature text file",
            prompt="Use a text file containing the AUTH block from a recovery sheet.",
            selected_paths=(
                (self.rebuild_state.auth_text_file,)
                if self.rebuild_state.auth_text_file is not None
                else ()
            ),
            callback=self._mutation_port._apply_rebuild_auth_text_picked,
            mode=FilePickerMode.OPEN_FILES,
            multiple=False,
        )

    async def _edit_rebuild_auth_payloads_source(self) -> None:
        await self._pick_paths(
            title="Signature payload file",
            prompt="Use an AUTH payload exported from backup documents.",
            selected_paths=(
                (self.rebuild_state.auth_payloads_file,)
                if self.rebuild_state.auth_payloads_file is not None
                else ()
            ),
            callback=self._mutation_port._apply_rebuild_auth_payloads_picked,
            mode=FilePickerMode.OPEN_FILES,
            multiple=False,
        )

    async def _edit_replace_recovery_text_source(self) -> None:
        await self.push_screen(
            PasteTextScreen(
                title="Recovery text",
                prompt="Paste the MAIN block from an existing recovery sheet.",
                value=self.replace_recovery_docs_state.recovery_text or "",
                placeholder="Paste the MAIN block here.",
            ),
            self._mutation_port._apply_replace_recovery_text,
        )

    async def _edit_replace_payloads_source(self) -> None:
        await self._pick_paths(
            title="Backup payload file",
            prompt="Use a payload exported from the existing backup documents.",
            selected_paths=(
                (self.replace_recovery_docs_state.payloads_file,)
                if self.replace_recovery_docs_state.payloads_file is not None
                else ()
            ),
            callback=self._mutation_port._apply_replace_payloads_picked,
            mode=FilePickerMode.OPEN_FILES,
            multiple=False,
        )

    async def _edit_replace_signing_key_payloads(self) -> None:
        await self._pick_paths(
            title="Signing-key recovery payload files",
            prompt="Use payloads exported from the signing-key sheets you are replacing.",
            selected_paths=self.replace_recovery_docs_state.signing_key_recovery_payload_files,
            callback=self._mutation_port._apply_replace_signing_key_payloads_picked,
            mode=FilePickerMode.OPEN_FILES,
        )

    async def _edit_replace_passphrase_replacement_count(self) -> None:
        value = self.replace_recovery_docs_state.passphrase_replacement_count
        await self.push_screen(
            EditFieldScreen(
                title="Passphrase sheets to replace",
                prompt="Number of existing sheets to replace.",
                value=str(value) if value is not None else "",
                placeholder="1",
                mask_template=INTEGER_MASK,
            ),
            self._mutation_port._apply_replace_passphrase_replacement_count,
        )

    async def _edit_replace_signing_key_replacement_count(self) -> None:
        value = self.replace_recovery_docs_state.signing_key_replacement_count
        await self.push_screen(
            EditFieldScreen(
                title="Signing-key sheets to replace",
                prompt="Number of existing sheets to replace.",
                value=str(value) if value is not None else "",
                placeholder="1",
                mask_template=INTEGER_MASK,
            ),
            self._mutation_port._apply_replace_signing_key_replacement_count,
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
                    prompt=(f"Enter recommended, single, or {QUORUM_VALUE}. {QUORUM_RANGE}"),
                    value=value,
                    placeholder="recommended",
                ),
                self._mutation_port._apply_backup_recovery,
            )
        elif self.active_task == "replace_recovery_docs":
            await self.push_screen(
                EditFieldScreen(
                    title="New recovery method",
                    prompt=QUORUM_PROMPT,
                    value=(
                        f"{self.replace_recovery_docs_state.recovery_threshold}/"
                        f"{self.replace_recovery_docs_state.recovery_document_count}"
                    ),
                    placeholder="2/3",
                    mask_template=QUORUM_MASK,
                ),
                self._mutation_port._apply_replace_recovery_set,
            )

    async def _edit_replace_signing_key_recovery(self) -> None:
        state = self.replace_recovery_docs_state
        threshold = state.signing_key_recovery_threshold or state.recovery_threshold
        count = state.signing_key_recovery_count or state.recovery_document_count
        await self.push_screen(
            EditFieldScreen(
                title="Signing-key recovery",
                prompt=QUORUM_PROMPT,
                value=f"{threshold}/{count}",
                placeholder="2/3",
                mask_template=QUORUM_MASK,
            ),
            self._mutation_port._apply_replace_signing_key_recovery,
        )

    async def _edit_layout_section(self) -> None:
        paper_size, design = self._current_layout()
        await self.push_screen(
            EditFieldScreen(
                title="Print layout",
                prompt="Paper and design, for example A4 sentinel or LETTER forge.",
                value=f"{paper_size} {design}",
                placeholder="A4 sentinel",
            ),
            self._mutation_port._apply_layout_section,
        )

    async def _edit_restore_target(self) -> None:
        if self.active_task != "restore":
            self.notify("This field cannot be changed here.", severity="warning")
            return
        value: str = self.restore_state.target
        if self.restore_state.target == "specific_update" and self.restore_state.extension_index:
            value = f"update {self.restore_state.extension_index}"
        await self.push_screen(
            EditFieldScreen(
                title="Version to restore",
                prompt="Latest, initial, or an update number.",
                value=value,
                placeholder="latest",
            ),
            self._mutation_port._apply_restore_target,
        )

    async def _edit_restore_target_fingerprint(self) -> None:
        if self.active_task != "restore":
            self.notify("This field cannot be changed here.", severity="warning")
            return
        await self.push_screen(
            EditFieldScreen(
                title="Version fingerprint",
                prompt="Use the fingerprint printed on the target version or update.",
                value=self.restore_state.extension_doc_hash or "",
                placeholder="fingerprint",
            ),
            self._mutation_port._apply_restore_target_fingerprint,
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
            self.notify("Load scanned pages first.", severity="warning")
            return
        await self.push_screen(
            EditFieldScreen(
                title="Latest backup fingerprint",
                prompt="Use the fingerprint printed on the version you trust as latest.",
                value=value,
                placeholder="fingerprint",
            ),
            self._mutation_port._apply_expected_head_fingerprint,
        )
