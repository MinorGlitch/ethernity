from __future__ import annotations

from pathlib import Path

from ethernity.tasks.models import TaskSection
from ethernity.tasks.presentation.models import WorkspaceValue


def section_value(section: TaskSection) -> WorkspaceValue:
    value = section.summary
    if section.status != "ready":
        value = f"{status_label(section.status)}: {section.summary}"
    return WorkspaceValue(
        key=section.key,
        label=section.title,
        value=value,
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


def source_values(
    *,
    scan_paths: tuple[Path, ...],
    recovery_text_file: Path | None,
    payloads_file: Path | None,
) -> tuple[WorkspaceValue, ...]:
    values = list(path_values("scan", scan_paths))
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
                label="Payload files",
                value=middle_truncate_path(payloads_file),
            )
        )
    return tuple(values)


def auth_material_summary(auth_text_file: Path | None, auth_payloads_file: Path | None) -> str:
    if auth_text_file is not None:
        return f"Trust text: {middle_truncate_path(auth_text_file)}"
    if auth_payloads_file is not None:
        return f"Trust payload files: {middle_truncate_path(auth_payloads_file)}"
    return "From loaded backup"


def qr_chunk_size_summary(qr_chunk_size: int | None) -> str:
    if qr_chunk_size is None:
        return "Using saved default"
    return f"{qr_chunk_size} bytes"


def middle_truncate_path(path: Path | str, *, max_chars: int = 56) -> str:
    text = str(path)
    home = str(Path.home())
    if text == home:
        text = "~"
    elif text.startswith(f"{home}/"):
        text = f"~/{text[len(home) + 1 :]}"
    if len(text) <= max_chars:
        return text

    separator = "/" if "/" in text else "\\"
    parts = text.split(separator)
    if len(parts) >= 3:
        prefix = separator.join(parts[:2])
        suffix = separator.join(parts[-2:])
        shortened = f"{prefix}{separator}...{separator}{suffix}"
        if len(shortened) <= max_chars:
            return shortened

    keep = max(8, (max_chars - 3) // 2)
    return f"{text[:keep]}...{text[-keep:]}"


def status_label(status: str) -> str:
    if status == "ready":
        return "Complete"
    if status == "warning":
        return "Warning"
    if status == "blocked":
        return "Invalid"
    return "Required"
