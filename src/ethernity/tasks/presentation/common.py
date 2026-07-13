from __future__ import annotations

from pathlib import Path

from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import TaskSection, TaskValidation
from ethernity.tasks.presentation.models import WorkspaceValue


def section_value(section: TaskSection) -> WorkspaceValue:
    return WorkspaceValue(
        key=section.key,
        label=section.title,
        value=section.summary,
        status=section.status,
    )


def path_values(prefix: str, paths: tuple[Path, ...]) -> tuple[WorkspaceValue, ...]:
    return tuple(
        WorkspaceValue(
            key=f"{prefix}-{index}",
            label=Path(path).name or str(path),
            value=middle_truncate_path(path),
        )
        for index, path in enumerate(paths)
    )


def qr_chunk_size_summary(qr_chunk_size: int | None) -> str:
    if qr_chunk_size is None:
        return "From settings"
    return f"{qr_chunk_size} bytes"


def qr_chunk_size_control_value(qr_chunk_size: int | None) -> str:
    return "default" if qr_chunk_size is None else "custom"


def middle_truncate_path(path: Path | str, *, max_chars: int = 56) -> str:
    return display_path(path, max_chars=max_chars)


def status_label(status: str) -> str:
    if status == "ready":
        return "Ready"
    if status == "optional":
        return "Optional"
    if status == "warning":
        return "Warning"
    if status == "blocked":
        return "Needs input"
    return "Required"


def validation_readiness(validation: TaskValidation) -> tuple[int, int]:
    """Return presentation counts without contradicting domain validation."""
    required_count = max(
        sum(1 for section in validation.sections if section.status != "optional"),
        1,
    )
    error_sections = {
        issue.section
        for issue in validation.issues
        if issue.severity == "error" and issue.section is not None
    }
    ready_count = sum(
        1
        for section in validation.sections
        if section.status in {"ready", "warning"} and section.key not in error_sections
    )
    if not validation.ready and ready_count >= required_count:
        ready_count = required_count - 1
    return ready_count, required_count
