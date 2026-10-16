from __future__ import annotations

from ethernity.tasks.models import TaskPreview, TaskValidation
from ethernity.tasks.presentation.models import (
    SummaryPresentation,
    TaskPresentation,
    WorkspaceAction,
    WorkspaceGroup,
    WorkspaceValue,
)
from ethernity.tasks.presentation.presentation_values import validation_readiness
from ethernity.tasks.presentation.registry import task_presenter
from ethernity.tasks.task_types import TaskKey, TaskState


def build_task_presentation(
    *,
    task_key: TaskKey,
    title: str,
    state: TaskState,
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
    task_key: TaskKey,
    state: TaskState,
    validation: TaskValidation,
) -> tuple[WorkspaceGroup, ...]:
    sections = {section.key: section for section in validation.sections}
    return task_presenter(task_key).groups(state, sections)


def _primary_action(primary_label: str, validation: TaskValidation) -> WorkspaceAction:
    return WorkspaceAction("primary", primary_label, enabled=validation.ready)


__all__ = ["build_task_presentation", "workspace_groups"]
