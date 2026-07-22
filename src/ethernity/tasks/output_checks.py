from __future__ import annotations

from pathlib import Path
from typing import Literal

from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import TaskIssue, TaskSectionStatus

ExistingOutputTarget = Literal["output_folder", "pdf_file"]


def selected_output_status(path: Path | None) -> TaskSectionStatus:
    if path is None:
        return "missing"
    if path.exists():
        return "warning"
    return "ready"


def existing_output_summary(
    path: Path | None,
    *,
    target: ExistingOutputTarget,
    missing_summary: str,
) -> str:
    if path is None:
        return missing_summary
    if not path.exists():
        return display_path(path)
    if target == "pdf_file":
        return f"Existing PDF: {display_path(path)}"
    return f"Existing output folder: {display_path(path)}"


def existing_output_warning(
    path: Path | None,
    *,
    code: str,
    target: ExistingOutputTarget,
) -> tuple[TaskIssue, ...]:
    if path is None or not path.exists():
        return ()
    return (
        TaskIssue(
            code=code,
            message=_existing_output_message(target),
            severity="warning",
            section="output",
        ),
    )


def _existing_output_message(target: ExistingOutputTarget) -> str:
    if target == "pdf_file":
        return "Selected PDF file already exists and may be replaced."
    return (
        "Selected output folder already exists; generated files with the same names may be "
        "replaced."
    )
