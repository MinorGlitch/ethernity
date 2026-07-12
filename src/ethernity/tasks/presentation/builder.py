from __future__ import annotations

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskPreview, TaskValidation
from ethernity.tasks.presentation.common import validation_readiness
from ethernity.tasks.presentation.models import (
    PresentationState,
    PresentationTaskKey,
    SummaryPresentation,
    TaskPresentation,
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.workflow_add_files import add_files_auxiliary_groups
from ethernity.tasks.presentation.workflow_backup import backup_groups
from ethernity.tasks.presentation.workflow_kit import kit_groups
from ethernity.tasks.presentation.workflow_rebuild import rebuild_auxiliary_groups
from ethernity.tasks.presentation.workflow_replace_recovery import (
    replace_recovery_auxiliary_groups,
)
from ethernity.tasks.presentation.workflow_restore import restore_auxiliary_groups
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.replace_recovery_docs import ReplaceRecoveryDocsTaskState
from ethernity.tasks.restore import RestoreTaskState


def build_task_presentation(
    *,
    task_key: PresentationTaskKey,
    title: str,
    state: PresentationState,
    validation: TaskValidation,
    preview: TaskPreview,
    primary_label: str,
    diagnostics_available: bool,
) -> TaskPresentation:
    groups = workspace_groups(task_key, state, validation)
    ready_count, total_count = validation_readiness(validation)
    return TaskPresentation(
        task_key=task_key,
        title=title,
        ready_count=ready_count,
        total_count=total_count,
        workspace_groups=groups,
        summary=SummaryPresentation(
            title=preview.title,
            items=tuple(
                WorkspaceValue(
                    key=f"summary-{index}",
                    label=item.label,
                    value=item.detail or "",
                )
                for index, item in enumerate(preview.items)
            ),
            blockers=tuple(issue for issue in validation.issues if issue.severity == "error"),
            warnings=preview.warnings,
        ),
        primary_action=_primary_action(primary_label, validation),
        diagnostics_available=diagnostics_available,
        validation_ready=validation.ready,
    )


def workspace_groups(
    task_key: PresentationTaskKey,
    state: PresentationState,
    validation: TaskValidation,
) -> tuple[WorkspaceGroup, ...]:
    sections = {section.key: section for section in validation.sections}
    if task_key == "backup" and isinstance(state, BackupTaskState):
        return backup_groups(state, sections)
    if task_key == "restore" and isinstance(state, RestoreTaskState):
        return restore_auxiliary_groups(state)
    if task_key == "add_files" and isinstance(state, AddFilesTaskState):
        return add_files_auxiliary_groups(state, sections["advanced"])
    if task_key == "rebuild" and isinstance(state, RebuildTaskState):
        return rebuild_auxiliary_groups(state, sections["advanced"])
    if task_key == "replace_recovery_docs" and isinstance(state, ReplaceRecoveryDocsTaskState):
        return replace_recovery_auxiliary_groups(state, sections["signature"])
    if task_key == "kit" and isinstance(state, PrintKitTaskState):
        return kit_groups(state, sections)
    return ()


def _primary_action(primary_label: str, validation: TaskValidation) -> WorkspaceAction:
    return WorkspaceAction("primary", primary_label, enabled=validation.ready)


__all__ = ["build_task_presentation", "workspace_groups"]
