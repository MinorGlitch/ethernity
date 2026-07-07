from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.doctor import DoctorTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskIssue
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState
from ethernity.tasks.settings import SettingsTaskState

PresentationTaskKey = Literal[
    "backup",
    "restore",
    "add_files",
    "rebuild",
    "replace_recovery_docs",
    "kit",
    "doctor",
    "settings",
]
PresentationState = (
    BackupTaskState
    | RestoreTaskState
    | AddFilesTaskState
    | RebuildTaskState
    | ReplaceRecoveryDocsTaskState
    | PrintKitTaskState
    | DoctorTaskState
    | SettingsTaskState
)


@dataclass(frozen=True)
class WorkspaceAction:
    key: str
    label: str
    enabled: bool = True


@dataclass(frozen=True)
class WorkspaceChoice:
    key: str
    label: str
    selected: bool = False


@dataclass(frozen=True)
class WorkspaceValue:
    key: str
    label: str
    value: str
    status: str = "ready"


@dataclass(frozen=True)
class WorkspaceGroup:
    key: str
    title: str
    kind: str
    values: tuple[WorkspaceValue, ...] = ()
    choices: tuple[WorkspaceChoice, ...] = ()
    actions: tuple[WorkspaceAction, ...] = ()
    empty_label: str = ""


@dataclass(frozen=True)
class OutcomePresentation:
    title: str
    items: tuple[WorkspaceValue, ...]
    blockers: tuple[TaskIssue, ...]
    warnings: tuple[TaskIssue, ...]


@dataclass(frozen=True)
class TaskPresentation:
    task_key: PresentationTaskKey
    title: str
    ready_count: int
    total_count: int
    workspace_groups: tuple[WorkspaceGroup, ...]
    outcome: OutcomePresentation
    primary_action: WorkspaceAction
    diagnostics_available: bool

    @property
    def readiness_label(self) -> str:
        if self.ready_count >= self.total_count:
            if self.task_key == "doctor":
                return "All checks passed"
            return "Ready to review"
        return f"Required: {self.ready_count} of {self.total_count} complete"
