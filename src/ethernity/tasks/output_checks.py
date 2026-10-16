from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import TaskIssue, TaskSectionStatus
from ethernity.workflows.shared.outputs import backup_output_path

ExistingOutputTarget = Literal["output_folder", "pdf_file"]
BACKUP_OUTPUT_NOTE = (
    "A new backup-<id> folder will be created inside the destination. "
    "Existing backups stay unchanged."
)


def planned_backup_output(parent: Path | None) -> Path:
    return backup_output_path(parent, "<id>")


def backup_destination_issues(parent: Path | None) -> tuple[TaskIssue, ...]:
    directory = planned_backup_output(parent).parent
    for ancestor in (directory, *directory.parents):
        if ancestor.exists() and not ancestor.is_dir():
            return (
                TaskIssue(
                    code="BACKUP_DESTINATION_NOT_DIRECTORY",
                    message=f"Choose a folder; this path is a file: {display_path(ancestor)}",
                    section="output",
                ),
            )
    return ()


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


class GeneratedBackupOutputs(Protocol):
    @property
    def qr_path(self) -> Path: ...
    @property
    def recovery_path(self) -> Path: ...
    @property
    def shard_paths(self) -> tuple[Path, ...]: ...
    @property
    def signing_key_shard_paths(self) -> tuple[Path, ...]: ...
    @property
    def kit_index_path(self) -> Path | None: ...


def generated_output_paths(result: GeneratedBackupOutputs) -> tuple[Path, ...]:
    documents = (
        result.qr_path,
        result.recovery_path,
        *result.shard_paths,
        *result.signing_key_shard_paths,
    )
    return documents if result.kit_index_path is None else (*documents, Path(result.kit_index_path))


def generated_recovery_check_paths(result: GeneratedBackupOutputs) -> tuple[Path, ...]:
    return (result.qr_path, *result.shard_paths, *result.signing_key_shard_paths)
