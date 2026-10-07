"""One presentation owner per task, shared by workspaces and final review."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from ethernity.tasks import task_types
from ethernity.tasks.models import TaskExecutionPlan, TaskSection
from ethernity.tasks.presentation import (
    workflow_add_files,
    workflow_backup,
    workflow_kit,
    workflow_rebuild,
    workflow_replace_recovery,
    workflow_restore,
)
from ethernity.tasks.presentation.models import ReviewDetail, WorkspaceGroup

State = TypeVar("State", bound=BaseModel)
Sections = dict[str, TaskSection]


@dataclass(frozen=True, slots=True)
class TaskPresenter:
    state_type: type[BaseModel]
    groups: Callable[[task_types.TaskState, Sections], tuple[WorkspaceGroup, ...]]
    review: Callable[[task_types.TaskState, TaskExecutionPlan], tuple[ReviewDetail, ...]]


def _presenter(
    model: type[State],
    groups: Callable[[State, Sections], tuple[WorkspaceGroup, ...]],
    review: Callable[[State, TaskExecutionPlan], tuple[ReviewDetail, ...]],
) -> TaskPresenter:
    return TaskPresenter(
        model,
        lambda state, sections: groups(task_types.require_state(state, model), sections),
        lambda state, plan: review(task_types.require_state(state, model), plan),
    )


_PRESENTERS: dict[task_types.TaskKey, TaskPresenter] = {
    "backup": _presenter(
        task_types.BackupTaskState, workflow_backup.backup_groups, workflow_backup.review_details
    ),
    "restore": _presenter(
        task_types.RestoreTaskState,
        lambda state, _sections: workflow_restore.restore_auxiliary_groups(state),
        workflow_restore.review_details,
    ),
    "add_files": _presenter(
        task_types.AddFilesTaskState,
        lambda state, sections: workflow_add_files.add_files_auxiliary_groups(
            state, sections["advanced"]
        ),
        workflow_add_files.review_details,
    ),
    "rebuild": _presenter(
        task_types.RebuildTaskState,
        lambda state, sections: workflow_rebuild.rebuild_auxiliary_groups(
            state, sections["advanced"]
        ),
        workflow_rebuild.review_details,
    ),
    "replace_recovery_docs": _presenter(
        task_types.ReplaceRecoveryDocsTaskState,
        lambda state, sections: workflow_replace_recovery.replace_recovery_auxiliary_groups(
            state, sections["signature"]
        ),
        workflow_replace_recovery.review_details,
    ),
    "kit": _presenter(
        task_types.PrintKitTaskState, workflow_kit.kit_groups, workflow_kit.review_details
    ),
    "settings": _presenter(
        task_types.SettingsTaskState, lambda _state, _sections: (), lambda _state, _plan: ()
    ),
}


def task_presenter(task: task_types.TaskKey) -> TaskPresenter:
    return _PRESENTERS[task]


def build_review_details(
    task: task_types.TaskKey,
    state: task_types.TaskState,
    plan: TaskExecutionPlan,
) -> tuple[ReviewDetail, ...]:
    return task_presenter(task).review(state, plan)
