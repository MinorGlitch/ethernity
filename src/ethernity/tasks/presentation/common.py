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


def unlock_material_values(
    *,
    recovery_documents: tuple[Path, ...],
    recovery_payload_files: tuple[Path, ...],
) -> tuple[WorkspaceValue, ...]:
    return (
        *path_values("recovery-document", recovery_documents),
        *path_values("recovery-payload", recovery_payload_files),
    )


def source_values(
    *,
    scan_paths: tuple[Path, ...],
    recovery_text: str | None = None,
    recovery_text_file: Path | None = None,
    payloads_file: Path | None = None,
) -> tuple[WorkspaceValue, ...]:
    values = list(path_values("scan", scan_paths))
    if recovery_text:
        values.append(
            WorkspaceValue(
                key="recovery-text",
                label="Recovery text",
                value=_pasted_text_summary(recovery_text),
            )
        )
    if recovery_text_file is not None:
        values.append(
            WorkspaceValue(
                key="recovery-text",
                label="Recovery text",
                value=middle_truncate_path(recovery_text_file),
            )
        )
    if payloads_file is not None:
        values.append(
            WorkspaceValue(
                key="payloads",
                label="Backup payload file",
                value=middle_truncate_path(payloads_file),
            )
        )
    return tuple(values)


def _pasted_text_summary(text: str) -> str:
    line_count = len([line for line in text.splitlines() if line.strip()])
    if line_count == 1:
        return "Pasted text, 1 line"
    return f"Pasted text, {line_count} lines"


def auth_material_summary(auth_text_file: Path | None, auth_payloads_file: Path | None) -> str:
    if auth_text_file is not None:
        return f"Signature text: {middle_truncate_path(auth_text_file)}"
    if auth_payloads_file is not None:
        return f"Signature payload: {middle_truncate_path(auth_payloads_file)}"
    return "Loaded backup"


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
