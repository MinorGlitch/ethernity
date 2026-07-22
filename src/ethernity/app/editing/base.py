from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_types import PathSelectionCallback
from ethernity.app.editing.mutation_port import TaskMutationPort
from ethernity.app.path_utils import picker_root
from ethernity.app.screens.file_picker import FilePickerMode, FilePickerScreen


class BaseEditingActions(EthernityAppContext):
    @property
    def _mutation_port(self) -> TaskMutationPort:
        return cast(TaskMutationPort, self)

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
        await self.push_screen(
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
