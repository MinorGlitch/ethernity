from __future__ import annotations

from typing import Literal, cast

from ethernity.app.app_types import UnlockTaskState
from ethernity.app.editing.base import BaseEditingActions
from ethernity.app.editing.definitions import PassphraseEditorDefinition
from ethernity.app.path_selection import save_picker_parts
from ethernity.app.screens.edit_field import EditFieldScreen
from ethernity.app.screens.file_picker import FilePickerMode
from ethernity.app.widgets.workflow.unlock import UnlockEditor
from ethernity.app.workflow_registry import workflow_definition
from ethernity.tasks.backup import BackupTaskState


class PrimaryEditingActions(BaseEditingActions):
    async def action_edit_primary(self) -> None:
        editor = workflow_definition(self.active_task).primary_editor
        if isinstance(editor, str):
            self.query_one(editor).focus()
        elif editor is not None:
            await self._pick_paths(
                title=editor.title,
                prompt=editor.prompt,
                selected_paths=editor.selected_paths(self),
                callback=editor.callback(self),
            )

    async def action_edit_output(self) -> None:
        editor = workflow_definition(self.active_task).output_editor
        if isinstance(editor, str):
            await self.settings_controller.edit(editor)
        elif editor is not None:
            root, name = save_picker_parts(await editor.current_path(self))
            await self._pick_paths(
                title=editor.title,
                prompt=editor.prompt,
                selected_paths=(root,),
                callback=editor.callback(self),
                mode=editor.mode,
                save_name=name,
                save_placeholder=editor.placeholder,
                allow_clear=editor.allow_clear,
            )

    async def _edit_add_files_source(self) -> None:
        await self._pick_paths(
            title="Load backup documents",
            prompt=(
                "Load the original backup and the updates needed for your selected version. "
                "Include recovery sheets if you have them."
            ),
            selected_paths=self.add_files_state.source_paths,
            callback=self._editor_callbacks._apply_add_files_sources_picked,
        )

    async def action_edit_passphrase(self) -> None:
        editor = workflow_definition(self.active_task).passphrase_editor
        if isinstance(editor, str):
            self.query_one(editor).focus()
        elif isinstance(editor, PassphraseEditorDefinition):
            state = cast(BackupTaskState | UnlockTaskState, self._current_state())
            await self._push_editor(
                EditFieldScreen(
                    title=editor.title,
                    prompt=editor.prompt,
                    value=state.passphrase or "",
                    password=True,
                ),
                editor.callback(self),
            )

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
                callback=self._editor_callbacks._apply_unlock_recovery_documents_picked,
            )
            return
        await self._pick_paths(
            title="Recovery payload files",
            prompt="Use payload files exported from recovery sheets.",
            selected_paths=state.recovery_payload_files,
            callback=self._editor_callbacks._apply_unlock_payload_files_picked,
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
        return workflow_definition(self.active_task).unlock_selector

    def _unlock_state(self) -> UnlockTaskState | None:
        if self._guided_unlock_editor_selector() is None:
            return None
        return cast(UnlockTaskState, self._current_state())
