"""Convert task state into values displayed by workspace presenters."""

from __future__ import annotations

from pathlib import Path

from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import TaskSection, TaskValidation
from ethernity.tasks.presentation.models import WorkspaceAction, WorkspaceGroup, WorkspaceValue
from ethernity.tasks.presentation.recovery import (
    signature_source_control_value,
    signature_source_summary,
)


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


def base_directory_value(base_dir: Path | None) -> WorkspaceValue:
    return WorkspaceValue(
        "base-dir",
        "Base folder",
        display_path(base_dir) if base_dir is not None else "Based on selected files",
        control_value="custom" if base_dir is not None else "automatic",
    )


def qr_density_value(chunk_size: int | None) -> WorkspaceValue:
    return WorkspaceValue(
        "qr-chunk-size",
        "QR density",
        qr_chunk_size_summary(chunk_size),
        control_value=qr_chunk_size_control_value(chunk_size),
    )


def signature_source_value(
    text_file: Path | None, payloads_file: Path | None, *, source_loaded: bool = True
) -> WorkspaceValue:
    summary = (
        signature_source_summary(text_file, payloads_file)
        if source_loaded or text_file is not None or payloads_file is not None
        else "Choose a backup first"
    )
    return WorkspaceValue(
        "signature-source",
        "Verification source",
        summary,
        control_value=signature_source_control_value(text_file, payloads_file),
    )


def advanced_fields_group(
    section: TaskSection,
    *,
    values: tuple[WorkspaceValue, ...],
    actions: tuple[WorkspaceAction, ...],
) -> WorkspaceGroup:
    return WorkspaceGroup(
        key="advanced",
        title="Advanced",
        kind="fields",
        values=values,
        actions=actions,
        status=section.status,
        status_summary=section.summary,
    )


def print_layout_group(paper_size: str, design: str, section: TaskSection) -> WorkspaceGroup:
    return WorkspaceGroup(
        key=section.key,
        title="Print setup",
        kind="layout",
        values=(
            WorkspaceValue("paper", "Paper size", paper_size),
            WorkspaceValue("design", "Print design", design),
        ),
        status=section.status,
        status_summary=section.summary,
    )
