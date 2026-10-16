"""Section policies shared by backup and recovery tasks."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import (
    PreviewItem,
    TaskIssue,
    TaskSection,
    TaskSectionStatus,
    optional_section_status,
)
from ethernity.tasks.output_checks import (
    backup_destination_issues,
    existing_output_summary,
    planned_backup_output,
    selected_output_status,
)
from ethernity.tasks.presentation.recovery import unlock_input_summary
from ethernity.tasks.recovery_inputs import UnlockInputs, has_unlock_inputs


def unlock_section(inputs: UnlockInputs, title: str) -> TaskSection:
    return TaskSection(
        key="unlock",
        title=title,
        status="ready" if has_unlock_inputs(inputs) else "missing",
        summary=unlock_input_summary(inputs),
        action_label="Set unlock method...",
    )


def freshness_section(
    status: TaskSectionStatus, summary: str, title: str = "Backup version"
) -> TaskSection:
    return TaskSection(
        key="freshness", title=title, status=status, summary=summary, action_label="Confirm source"
    )


def advanced_section(
    issues: Collection[TaskIssue], warnings: Collection[TaskIssue], summary: str
) -> TaskSection:
    return TaskSection(
        key="advanced",
        title="Advanced",
        status=optional_section_status(issues, warnings),
        summary=summary,
        action_label="Review advanced options",
    )


def output_folder_section(path: Path | None, title: str) -> TaskSection:
    return TaskSection(
        key="output",
        title=title,
        status=selected_output_status(path),
        summary=existing_output_summary(
            path, target="output_folder", missing_summary="No output folder selected."
        ),
        action_label="Choose output folder...",
    )


def backup_destination_section(
    parent: Path | None, title: str, *, required: bool = False
) -> TaskSection:
    if required and parent is None:
        return TaskSection(
            key="output", title=title, status="missing", summary="Choose a parent folder."
        )
    return TaskSection(
        key="output",
        title=title,
        status="blocked" if backup_destination_issues(parent) else "ready",
        summary=display_path(planned_backup_output(parent)),
        action_label="Choose parent folder...",
    )


def qr_density_warnings(chunk_size: int | None, code: str) -> tuple[TaskIssue, ...]:
    if chunk_size is None:
        return ()
    return (
        TaskIssue(
            code=code,
            message="Custom QR density can change page count and make codes harder to scan.",
            severity="warning",
            section="advanced",
        ),
    )


def stale_source_warnings(accepted: bool, code: str) -> tuple[TaskIssue, ...]:
    if not accepted:
        return ()
    return (
        TaskIssue(
            code=code,
            message="The loaded documents may omit a newer backup version.",
            severity="warning",
            section="freshness",
        ),
    )


def destination_preview(path: Path | None) -> PreviewItem:
    return PreviewItem(
        label="Destination", detail=display_path(path) if path is not None else "Not selected"
    )


def unchanged_backup_preview() -> PreviewItem:
    return PreviewItem(label="Existing backup files", detail="Left unchanged")


def confirmed_source_section(
    expected_fingerprint: str | None, allow_stale: bool, summary: str
) -> TaskSection:
    return freshness_section(
        "ready" if expected_fingerprint is not None or allow_stale else "missing", summary
    )
