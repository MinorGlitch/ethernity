from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from textual.widgets import Select

from ethernity.app.app_types import UnlockTaskState
from ethernity.app.editing.base import BaseEditingActions
from ethernity.app.path_utils import save_picker_parts
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerMode
from ethernity.app.widgets.guided_workflow import UnlockEditor


class PrimaryEditingActions(BaseEditingActions):
    async def action_edit_primary(self) -> None:
        if self.active_task == "backup":
            await self._pick_paths(
                title="Backup files",
                prompt="Add files or folders. Folder contents are included.",
                selected_paths=(*self.backup_state.input_paths, *self.backup_state.input_dirs),
                callback=self._mutation_port._apply_backup_files_picked,
            )
        elif self.active_task == "restore":
            await self._pick_paths(
                title="Backup to restore",
                prompt="Use a backup folder, or load scanned pages from PDFs, images, or folders.",
                selected_paths=self.restore_state.source_paths,
                callback=self._mutation_port._apply_restore_sources_picked,
            )
        elif self.active_task == "add_files":
            await self._pick_paths(
                title="Files to add or replace",
                prompt="A selected path replaces content at the same backup path.",
                selected_paths=(
                    *self.add_files_state.input_paths,
                    *self.add_files_state.input_dirs,
                ),
                callback=self._mutation_port._apply_add_files_inputs_picked,
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
                prompt="Use a backup folder, or load scanned pages from PDFs, images, or folders.",
                selected_paths=rebuild_selection,
                callback=self._mutation_port._apply_rebuild_source_picked,
            )
        elif self.active_task == "replace_recovery_docs":
            await self._pick_paths(
                title="Existing backup",
                prompt=(
                    "Use a backup folder, or load the newest scanned pages from PDFs, images, "
                    "or folders."
                ),
                selected_paths=self.replace_recovery_docs_state.source_paths,
                callback=self._mutation_port._apply_replace_recovery_sources_picked,
            )
        elif self.active_task == "settings":
            self.query_one("#setting-control-render_style").focus()

    async def action_edit_output(self) -> None:
        if self.active_task == "backup":
            root, name = save_picker_parts(self.backup_state.output_dir)
            await self._pick_paths(
                title="Backup output",
                prompt=(
                    "Choose a custom folder. Clear returns to an automatic folder named for the "
                    "backup ID in the current folder."
                ),
                selected_paths=(root,),
                callback=self._mutation_port._apply_backup_output_picked,
                mode=FilePickerMode.SAVE_DIRECTORY,
                save_name=name,
                save_placeholder="custom-folder",
            )
        elif self.active_task == "restore":
            root, name = save_picker_parts(self.restore_state.output_path)
            await self._pick_paths(
                title="Restore destination",
                prompt="Recovered files will be written here.",
                selected_paths=(root,),
                callback=self._mutation_port._apply_restore_output_picked,
                mode=FilePickerMode.SAVE_DIRECTORY,
                save_name=name,
                save_placeholder="recovered",
            )
        elif self.active_task == "kit":
            root, name = save_picker_parts(self.kit_state.output_path)
            await self._pick_paths(
                title="Recovery kit PDF",
                prompt="Creates one printable PDF.",
                selected_paths=(root,),
                callback=self._mutation_port._apply_kit_output_picked,
                mode=FilePickerMode.SAVE_FILE,
                save_name=name,
                save_placeholder="recovery_kit_qr.pdf",
                allow_clear=False,
            )
        elif self.active_task == "add_files":
            if not self.add_files_state.source_paths:
                await self._edit_add_files_backup_folder()
                return
            root, name = save_picker_parts(self.add_files_state.loose_output_folder)
            await self._pick_paths(
                title="Scan-based update output",
                prompt="Use a new or empty folder.",
                selected_paths=(root,),
                callback=self._mutation_port._apply_add_files_output_picked,
                mode=FilePickerMode.SAVE_DIRECTORY,
                save_name=name,
                save_placeholder="backup-update",
            )
        elif self.active_task == "rebuild":
            root, name = save_picker_parts(self.rebuild_state.output_dir)
            await self._pick_paths(
                title="Rebuilt backup output",
                prompt="Use a new or empty folder.",
                selected_paths=(root,),
                callback=self._mutation_port._apply_rebuild_output_picked,
                mode=FilePickerMode.SAVE_DIRECTORY,
                save_name=name,
                save_placeholder="rebuilt-backup",
            )
        elif self.active_task == "replace_recovery_docs":
            root, name = save_picker_parts(self.replace_recovery_docs_state.output_dir)
            await self._pick_paths(
                title="Replacement sheet output",
                prompt="Use a new or empty folder.",
                selected_paths=(root,),
                callback=self._mutation_port._apply_replace_recovery_output_picked,
                mode=FilePickerMode.SAVE_DIRECTORY,
                save_name=name,
                save_placeholder="replacement-recovery-docs",
            )
        elif self.active_task == "settings":
            await self.settings_controller.edit("backup_output_dir")

    async def _edit_add_files_backup_folder(self) -> None:
        selected = (
            (self.add_files_state.backup_folder,)
            if self.add_files_state.backup_folder is not None
            else ()
        )
        await self._pick_paths(
            title="Backup folder",
            prompt="Use the folder that contains the current backup.",
            selected_paths=selected,
            callback=self._mutation_port._apply_add_files_backup_picked,
            mode=FilePickerMode.OPEN_DIRECTORY,
        )

    async def action_edit_passphrase(self) -> None:
        if self.active_task == "backup":
            current = self.backup_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Backup passphrase",
                    prompt="Leave blank to generate a strong passphrase.",
                    value=current,
                    password=True,
                ),
                self._mutation_port._apply_backup_passphrase,
            )
        elif self.active_task == "restore":
            current = self.restore_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Restore passphrase",
                    prompt="Enter the passphrase for this backup.",
                    value=current,
                    password=True,
                ),
                self._mutation_port._apply_restore_passphrase,
            )
        elif self.active_task == "add_files":
            current = self.add_files_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Backup passphrase",
                    prompt="Enter the passphrase for this backup.",
                    value=current,
                    password=True,
                ),
                self._mutation_port._apply_add_files_passphrase,
            )
        elif self.active_task == "rebuild":
            current = self.rebuild_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Backup passphrase",
                    prompt="Enter the passphrase for this backup.",
                    value=current,
                    password=True,
                ),
                self._mutation_port._apply_rebuild_passphrase,
            )
        elif self.active_task == "replace_recovery_docs":
            current = self.replace_recovery_docs_state.passphrase or ""
            await self.push_screen(
                EditFieldScreen(
                    title="Backup passphrase",
                    prompt="Enter the passphrase for this backup.",
                    value=current,
                    password=True,
                ),
                self._mutation_port._apply_replace_recovery_passphrase,
            )
        elif self.active_task == "settings":
            self.query_one("#setting-control-page_size").focus()

    async def _edit_current_unlock(self) -> None:
        choice = self._selected_unlock_choice()
        if choice is None:
            if (selector := self._guided_unlock_editor_selector()) is not None:
                self.query_one(f"{selector}-methods").focus()
            self.notify("Choose an unlock method first.", severity="warning")
            return
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
                prompt="Use scanned recovery sheets from PDFs, images, or folders.",
                selected_paths=state.recovery_documents,
                callback=self._mutation_port._apply_unlock_recovery_documents_picked,
            )
            return
        await self._pick_paths(
            title="Recovery payload files",
            prompt="Use payload files exported from recovery sheets.",
            selected_paths=state.recovery_payload_files,
            callback=self._mutation_port._apply_unlock_payload_files_picked,
            mode=FilePickerMode.OPEN_FILES,
        )

    def _selected_unlock_choice(
        self,
    ) -> Literal["passphrase", "recovery_documents", "recovery_payloads"] | None:
        if (selector := self._guided_unlock_editor_selector()) is not None:
            choice = self.query_one(
                selector,
                UnlockEditor,
            ).selected_method
            if choice in {"passphrase", "recovery_documents", "recovery_payloads"}:
                return cast(
                    Literal["passphrase", "recovery_documents", "recovery_payloads"],
                    choice,
                )
            return None
        return None

    def _guided_unlock_editor_selector(self) -> str | None:
        return {
            "restore": "#workflow-restore-unlock-body",
            "add_files": "#workflow-add_files-unlock-body",
            "rebuild": "#workflow-rebuild-unlock-body-unlock",
            "replace_recovery_docs": "#workflow-replace_recovery_docs-unlock-body",
        }.get(self.active_task)

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
