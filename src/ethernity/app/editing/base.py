from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar, cast

from textual.screen import Screen

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_types import PathSelectionCallback
from ethernity.app.editing.editor_callbacks import TaskEditorCallbacks
from ethernity.app.path_selection import picker_root
from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen

EditorValue = TypeVar("EditorValue")


class BaseEditingActions(EthernityAppContext):
    async def _push_editor(
        self,
        editor: Screen[EditorValue],
        callback: Callable[[EditorValue | None], None],
    ) -> None:
        review_task = self._review_edit_task
        self._review_edit_task = None
        if review_task is None:
            await self.push_screen(editor, callback)
            return

        async def finish_edit(value: EditorValue | None) -> None:
            callback(value)
            if self.active_task == review_task:
                await self.action_review()

        await self.push_screen(editor, finish_edit)

    @property
    def _editor_callbacks(self) -> TaskEditorCallbacks:
        return cast(TaskEditorCallbacks, self)

    async def _pick_paths(
        self,
        *,
        title: str,
        prompt: str,
        selected_paths: Sequence[Path],
        callback: PathSelectionCallback,
        mode: FilePickerMode = FilePickerMode.OPEN_PATHS,
        multiple: bool = True,
        save_name: str = "",
        save_placeholder: str = "",
        choose_label: str = "Select",
        allow_clear: bool = True,
    ) -> None:
        await self._push_editor(
            FilePickerScreen(
                title=title,
                prompt=prompt,
                root=picker_root(selected_paths),
                mode=mode,
                selected_paths=selected_paths,
                multiple=multiple,
                save_name=save_name,
                save_placeholder=save_placeholder,
                choose_label=choose_label,
                allow_clear=allow_clear,
            ),
            callback,
        )
