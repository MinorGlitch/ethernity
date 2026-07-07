from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.doctor import DoctorTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState

ActiveTask = Literal[
    "backup",
    "restore",
    "add_files",
    "rebuild",
    "replace_recovery_docs",
    "kit",
    "doctor",
    "settings",
]

PathSelectionCallback = Callable[[tuple[Path, ...] | None], None]

TaskState = (
    BackupTaskState
    | RestoreTaskState
    | AddFilesTaskState
    | RebuildTaskState
    | ReplaceRecoveryDocsTaskState
    | PrintKitTaskState
    | DoctorTaskState
    | SettingsTaskState
)

UnlockTaskState = (
    RestoreTaskState | AddFilesTaskState | RebuildTaskState | ReplaceRecoveryDocsTaskState
)
