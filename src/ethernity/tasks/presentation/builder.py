from __future__ import annotations

from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.backup import BackupTaskState
from ethernity.tasks.doctor import DoctorTaskState
from ethernity.tasks.kit import PrintKitTaskState
from ethernity.tasks.models import TaskPreview, TaskValidation
from ethernity.tasks.presentation.models import (
    OutcomePresentation,
    PresentationState,
    PresentationTaskKey,
    TaskPresentation,
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.workflow_add_files import add_files_groups
from ethernity.tasks.presentation.workflow_backup import backup_groups
from ethernity.tasks.presentation.workflow_doctor import doctor_groups
from ethernity.tasks.presentation.workflow_kit import kit_groups
from ethernity.tasks.presentation.workflow_rebuild import rebuild_groups
from ethernity.tasks.presentation.workflow_replace_recovery import replace_recovery_groups
from ethernity.tasks.presentation.workflow_restore import restore_groups
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
    return TaskPresentation(
        task_key=task_key,
        title=title,
        ready_count=_ready_section_count(task_key, validation),
        total_count=max(len(validation.sections), 1),
        workspace_groups=groups,
        outcome=OutcomePresentation(
            title=preview.title,
            items=tuple(
                WorkspaceValue(
                    key=f"outcome-{index}",
                    label=item.label,
                    value=item.detail or "",
                )
                for index, item in enumerate(preview.items)
            ),
            blockers=tuple(issue for issue in validation.issues if issue.severity == "error"),
            warnings=tuple(
                issue for issue in preview.warnings if issue.code != "FINAL_REVIEW_REQUIRED"
            ),
        ),
        primary_action=_primary_action(primary_label, validation),
        diagnostics_available=diagnostics_available,
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
        return restore_groups(state, sections)
    if task_key == "add_files" and isinstance(state, AddFilesTaskState):
        return add_files_groups(state, sections)
    if task_key == "rebuild" and isinstance(state, RebuildTaskState):
        return rebuild_groups(state, sections)
    if task_key == "replace_recovery_docs" and isinstance(state, ReplaceRecoveryDocsTaskState):
        return replace_recovery_groups(state, sections)
    if task_key == "kit" and isinstance(state, PrintKitTaskState):
        return kit_groups(state, sections)
    if task_key == "doctor" and isinstance(state, DoctorTaskState):
        return doctor_groups(validation.sections)
    return ()


def _primary_action(primary_label: str, validation: TaskValidation) -> WorkspaceAction:
    if validation.ready:
        return WorkspaceAction("primary", primary_label, enabled=True)
    sections = {section.key: section for section in validation.sections}
    first_issue = next((issue for issue in validation.issues if issue.severity == "error"), None)
    action_label = "fix required field"
    if first_issue is not None and first_issue.section in sections:
        section = sections[first_issue.section]
        if section.action_label:
            action_label = section.action_label
        else:
            action_label = section.title
    return WorkspaceAction("primary", f"Fix: {action_label}", enabled=True)


def _ready_section_count(task_key: PresentationTaskKey, validation: TaskValidation) -> int:
    ready_statuses = {"ready"} if task_key == "doctor" else {"ready", "warning"}
    return sum(1 for section in validation.sections if section.status in ready_statuses)


__all__ = ["build_task_presentation", "workspace_groups"]
