from __future__ import annotations

from typing import Literal, TypeVar

from pydantic import BaseModel

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState

TaskKey = Literal[
    "backup",
    "restore",
    "add_files",
    "rebuild",
    "replace_recovery_docs",
    "kit",
    "settings",
]

TaskState = (
    BackupTaskState
    | RestoreTaskState
    | AddFilesTaskState
    | RebuildTaskState
    | ReplaceRecoveryDocsTaskState
    | PrintKitTaskState
    | SettingsTaskState
)


State = TypeVar("State", bound=BaseModel)


def require_state(state: object, expected: type[State]) -> State:
    """Check the concrete state at a heterogeneous task dispatch boundary."""
    if not isinstance(state, expected):
        raise TypeError(f"Expected {expected.__name__}, got {type(state).__name__}")
    return state
