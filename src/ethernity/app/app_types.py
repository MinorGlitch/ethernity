from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState

PathSelectionCallback = Callable[[tuple[Path, ...] | None], None]

UnlockTaskState = (
    RestoreTaskState | AddFilesTaskState | RebuildTaskState | ReplaceRecoveryDocsTaskState
)

SignatureTaskState = RestoreTaskState | AddFilesTaskState | RebuildTaskState
