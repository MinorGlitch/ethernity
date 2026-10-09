"""Editor bindings owned by the application workflow registry."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from ethernity.app.app_types import PathSelectionCallback
from ethernity.app.screens.file_picker import FilePickerMode
from ethernity.tasks.task_types import TaskState

if TYPE_CHECKING:
    from ethernity.app.editing.base import BaseEditingActions


@dataclass(frozen=True, slots=True)
class PathEditorDefinition:
    title: str
    prompt: str
    selected_paths: Callable[[BaseEditingActions], Sequence[Path]]
    callback: Callable[[BaseEditingActions], PathSelectionCallback]


@dataclass(frozen=True, slots=True)
class OutputEditorDefinition:
    title: str
    prompt: str
    attribute: Literal["output_path", "output_dir"]
    callback: Callable[[BaseEditingActions], PathSelectionCallback]
    placeholder: str
    mode: FilePickerMode = FilePickerMode.SAVE_DIRECTORY
    allow_clear: bool = True
    prepare_path: Callable[[BaseEditingActions], Awaitable[Path | None]] | None = None

    async def current_path(self, host: BaseEditingActions) -> Path | None:
        if self.prepare_path is not None:
            return await self.prepare_path(host)
        return cast(Path | None, getattr(host._current_state(), self.attribute))

    def set_path(self, state: TaskState, path: Path | None) -> None:
        setattr(state, self.attribute, path)


@dataclass(frozen=True, slots=True)
class PassphraseEditorDefinition:
    title: str
    prompt: str
    callback: Callable[[BaseEditingActions], Callable[[str | None], None]]


async def update_output_path(host: BaseEditingActions) -> Path | None:
    state = host.add_files_state
    if (path := state.resolved_output_dir()) is not None:
        return path
    snapshot = state.model_copy(deep=True)
    await asyncio.to_thread(snapshot.prepare_review)
    return snapshot.resolved_output_dir()


def rebuild_source_paths(host: BaseEditingActions) -> Sequence[Path]:
    state = host.rebuild_state
    return (state.backup_folder,) if state.backup_folder is not None else state.source_paths
