from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ethernity.app.app_context import EthernityAppContext
from ethernity.app.app_types import PathSelectionCallback
from ethernity.app.path_utils import picker_root
from ethernity.app.screens.file_picker import FilePickerScreen


class BaseEditingActions(EthernityAppContext):
    async def _pick_paths(
        self,
        *,
        title: str,
        prompt: str,
        selected_paths: Sequence[Path],
        callback: PathSelectionCallback,
        allow_files: bool = True,
        allow_dirs: bool = True,
        multiple: bool = True,
        save_name: str | None = None,
        save_placeholder: str = "",
        choose_label: str = "Choose",
    ) -> None:
        await self.push_screen(
            FilePickerScreen(
                title=title,
                prompt=prompt,
                root=picker_root(selected_paths),
                selected_paths=selected_paths,
                allow_files=allow_files,
                allow_dirs=allow_dirs,
                multiple=multiple,
                save_name=save_name,
                save_placeholder=save_placeholder,
                choose_label=choose_label,
            ),
            callback,
        )
