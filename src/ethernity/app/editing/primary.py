from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from textual.widgets import RadioButton, RadioSet, Select

from ethernity.app.app_types import UnlockTaskState
from ethernity.app.editing.base import BaseEditingActions
from ethernity.app.path_utils import save_picker_parts
from ethernity.app.screens.edit_field import EditFieldScreen


class PrimaryEditingActions(BaseEditingActions):
    async def action_edit_primary(self) -> None:
        if self.active_task == "backup":
            await self._pick_paths(
                title="Backup files",
                prompt="Choose files or folders to back up.",
                selected_paths=(*self.backup_state.input_paths, *self.backup_state.input_dirs),
                callback=self._apply_backup_files_picked,
            )
        elif self.active_task == "restore":
            await self._pick_paths(
                title="Backup to restore",
                prompt="Load scanned backup pages, PDFs, images, or folders.",
                selected_paths=self.restore_state.source_paths,
                callback=self._apply_restore_sources_picked,
            )
        elif self.active_task == "add_files":
            await self._pick_paths(
                title="Files to add",
                prompt="Choose files or folders to add to this backup.",
                selected_paths=(
                    *self.add_files_state.input_paths,
                    *self.add_files_state.input_dirs,
                ),
                callback=self._apply_add_files_inputs_picked,
            )
        elif self.active_task == "kit":
            self.query_one("#workspace-kit-variant-select", Select).focus()
        elif self.active_task == "rebuild":
            rebuild_selection: tuple[Path, ...] = (
                (self.rebuild_state.backup_folder,)
                if self.rebuild_state.backup_folder is not None
                else tuple(self.rebuild_state.source_paths)
            )
            await self._pick_paths(
                title="Existing backup",
                prompt="Choose a generated backup folder or load scanned pages.",
                selected_paths=rebuild_selection,
                callback=self._apply_rebuild_source_picked,
            )
        elif self.active_task == "replace_recovery_docs":
            await self._pick_paths(
                title="Existing backup",
                prompt="Load newest backup scans, PDFs, images, or folders.",
                selected_paths=self.replace_recovery_docs_state.source_paths,
                callback=self._apply_replace_recovery_sources_picked,
            )
        elif self.active_task == "settings":
            self.query_one("#setting-control-render_style").focus()

    async def action_edit_output(self) -> None:
        if self.active_task == "backup":
            root, name = save_picker_parts(self.backup_state.output_dir)
            await self._pick_paths(
                title="Backup output",
                prompt="Choose where backup documents will be saved.",
                selected_paths=(root,),
                callback=self._apply_backup_output_picked,
                allow_files=False,
                multiple=False,
                save_name=name,
                save_placeholder="backup-out",
            )
        elif self.active_task == "restore":
            root, name = save_picker_parts(self.restore_state.output_path)
            await self._pick_paths(
                title="Restore destination",
                prompt="Choose where recovered files will be written.",
                selected_paths=(root,),
                callback=self._apply_restore_output_picked,
                multiple=False,
                save_name=name,
                save_placeholder="recovered",
            )
        elif self.active_task == "kit":
            root, name = save_picker_parts(self.kit_state.output_path)
            await self._pick_paths(
                title="Recovery kit PDF",
                prompt="Choose where the printable recovery kit PDF will be saved.",
                selected_paths=(root,),
                callback=self._apply_kit_output_picked,
                allow_files=False,
                multiple=False,
                save_name=name,
                save_placeholder="recovery_kit_qr.pdf",
            )
        elif self.active_task == "add_files":
            selected = (
                (self.add_files_state.backup_folder,)
                if self.add_files_state.backup_folder is not None
                else ()
            )
            await self._pick_paths(
                title="Backup folder",
                prompt="Choose the generated backup folder to update.",
                selected_paths=selected,
                callback=self._apply_add_files_backup_picked,
                allow_files=False,
                multiple=False,
            )
        elif self.active_task == "rebuild":
            root, name = save_picker_parts(self.rebuild_state.output_dir)
            await self._pick_paths(
                title="Rebuilt backup output",
                prompt="Choose where rebuilt backup documents will be saved.",
                selected_paths=(root,),
                callback=self._apply_rebuild_output_picked,
                allow_files=False,
                multiple=False,
                save_name=name,
                save_placeholder="rebuilt-backup",
            )
        elif self.active_task == "replace_recovery_docs":
            root, name = save_picker_parts(self.replace_recovery_docs_state.output_dir)
            await self._pick_paths(
                title="Replacement sheet output",
                prompt="Choose where replacement recovery sheets will be saved.",
                selected_paths=(root,),
                callback=self._apply_replace_recovery_output_picked,
                allow_files=False,
                multiple=False,
                save_name=name,
                save_placeholder="replacement-recovery-docs",
            )
        elif self.active_task == "settings":
            await self.settings_controller.edit("backup_output_dir")

    async def action_edit_passphrase(self) -> None:
        if self.active_task == "backup":
            current = self.backup_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Backup passphrase",
                    prompt="Optional passphrase. Leave blank to generate one.",
                    value=current,
                    placeholder="auto-generate if blank",
                    password=True,
                ),
                self._apply_backup_passphrase,
            )
        elif self.active_task == "restore":
            current = self.restore_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Restore passphrase",
                    prompt="Passphrase used to unlock the backup",
                    value=current,
                    placeholder="passphrase",
                    password=True,
                ),
                self._apply_restore_passphrase,
            )
        elif self.active_task == "add_files":
            current = self.add_files_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Backup passphrase",
                    prompt="Passphrase used to unlock this backup",
                    value=current,
                    placeholder="passphrase",
                    password=True,
                ),
                self._apply_add_files_passphrase,
            )
        elif self.active_task == "rebuild":
            current = self.rebuild_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Backup passphrase",
                    prompt="Passphrase used to unlock this backup",
                    value=current,
                    placeholder="passphrase",
                    password=True,
                ),
                self._apply_rebuild_passphrase,
            )
        elif self.active_task == "replace_recovery_docs":
            current = self.replace_recovery_docs_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Backup passphrase",
                    prompt="Passphrase used to unlock this backup",
                    value=current,
                    placeholder="passphrase",
                    password=True,
                ),
                self._apply_replace_recovery_passphrase,
            )
        elif self.active_task == "settings":
            self.query_one("#setting-control-page_size").focus()

    async def _edit_current_unlock(self) -> None:
        choice = self._selected_unlock_choice() or "passphrase"
        await self._edit_unlock_choice(choice)

    async def _edit_unlock_choice(
        self,
        choice: Literal["passphrase", "recovery_documents", "recovery_payloads"],
    ) -> None:
        state = self._unlock_state()
        if state is None:
            await self.action_edit_passphrase()
            return
        if choice == "passphrase":
            await self.action_edit_passphrase()
            return
        if choice == "recovery_documents":
            await self._pick_paths(
                title="Recovery sheets",
                prompt="Choose recovery sheet scans, PDFs, images, or folders.",
                selected_paths=state.recovery_documents,
                callback=self._apply_unlock_recovery_documents_picked,
            )
            return
        await self._pick_paths(
            title="Recovery payload files",
            prompt="Choose exported recovery payload files.",
            selected_paths=state.recovery_payload_files,
            callback=self._apply_unlock_payload_files_picked,
            allow_dirs=False,
        )

    def _selected_unlock_choice(
        self,
    ) -> Literal["passphrase", "recovery_documents", "recovery_payloads"] | None:
        radio_id = {
            "restore": "workspace-restore-unlock-method",
            "add_files": "workspace-add-files-unlock-method",
            "rebuild": "workspace-rebuild-unlock-method",
            "replace_recovery_docs": "workspace-replace-unlock-method",
        }.get(self.active_task)
        if radio_id is None:
            return None
        radio = self.query_one(f"#{radio_id}", RadioSet)
        for button in radio.query(RadioButton):
            if not button.value or button.id is None:
                continue
            choice = button.id.removeprefix(radio_id.removesuffix("-method") + "-")
            if choice in {"passphrase", "recovery_documents", "recovery_payloads"}:
                return cast(
                    Literal["passphrase", "recovery_documents", "recovery_payloads"],
                    choice,
                )
        return "passphrase"

    def _unlock_state(self) -> UnlockTaskState | None:
        if self.active_task == "restore":
            return self.restore_state
        if self.active_task == "add_files":
            return self.add_files_state
        if self.active_task == "rebuild":
            return self.rebuild_state
        if self.active_task == "replace_recovery_docs":
            return self.replace_recovery_docs_state
        return None
