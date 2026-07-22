from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ethernity.cli.features.doctor.service import reconcile_publication_transactions
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskResultDetail,
    TaskSection,
    TaskValidation,
)


class DoctorTaskState(BaseModel):
    """Inspect or repair interrupted publication transactions."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    backup_folder: Path | None = None
    passphrase: str = ""
    repair: bool = False

    def sections(self) -> tuple[TaskSection, ...]:
        return (
            TaskSection(
                key="backup",
                title="Backup folder",
                status="ready" if self._valid_backup_folder() else "blocked",
                summary=str(self.backup_folder) if self.backup_folder else "Choose a backup folder",
            ),
            TaskSection(
                key="unlock",
                title="Authentication",
                status="ready" if self.passphrase else "blocked",
                summary="Passphrase supplied" if self.passphrase else "Passphrase required",
            ),
            TaskSection(
                key="repair",
                title="Operation",
                status="warning" if self.repair else "ready",
                summary="Repair authenticated transactions" if self.repair else "Inspect only",
            ),
        )

    def validate_task(self) -> TaskValidation:
        issues: list[TaskIssue] = []
        if not self._valid_backup_folder():
            issues.append(
                TaskIssue(
                    code="DOCTOR_BACKUP_REQUIRED",
                    message="Choose an existing generated backup folder.",
                    section="backup",
                )
            )
        if not self.passphrase:
            issues.append(
                TaskIssue(
                    code="DOCTOR_PASSPHRASE_REQUIRED",
                    message="Passphrase required to authenticate the chain before repair.",
                    section="unlock",
                )
            )
        return TaskValidation(sections=self.sections(), issues=tuple(issues))

    def preview(self) -> TaskPreview:
        return TaskPreview(
            title="Publication transaction doctor",
            items=(
                PreviewItem(label="Backup", detail=str(self.backup_folder or "not selected")),
                PreviewItem(
                    label="Mode",
                    detail="Authenticate and repair" if self.repair else "Authenticate and inspect",
                ),
            ),
            writes_files=self.repair,
        )

    def execution_plan(self) -> TaskExecutionPlan:
        return TaskExecutionPlan(
            summary=(
                "Reconcile interrupted publication transactions"
                if self.repair
                else "Inspect interrupted publication transactions"
            ),
            read_paths=(self.backup_folder,) if self.backup_folder is not None else (),
            writes_files=self.repair,
            safety_notes=(
                (
                    "Only transactions matching the authenticated root, current head, signed new "
                    "document, and recorded artifact snapshot can be repaired."
                ),
            ),
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        if not validation.ready or self.backup_folder is None:
            raise ValueError(validation.issues[0].message)
        result = reconcile_publication_transactions(
            self.backup_folder,
            passphrase=self.passphrase,
            repair=self.repair,
        )
        repaired = sum(1 for item in result.transactions if item.action != "none")
        return TaskExecutionResult(
            ok=True,
            message=(
                f"Reconciled {repaired} publication transaction(s)."
                if self.repair
                else f"Inspected {len(result.transactions)} publication transaction(s)."
            ),
            details=(
                TaskResultDetail(
                    key="authenticated_head_index",
                    label="Authenticated head index",
                    value=result.authenticated_head_index,
                ),
                TaskResultDetail(
                    key="authenticated_head_hash",
                    label="Authenticated head hash",
                    value=result.authenticated_head_hash,
                ),
                TaskResultDetail(
                    key="transactions",
                    label="Transactions",
                    value=tuple(
                        f"{item.path.name}: {item.status}; {item.action}"
                        for item in result.transactions
                    ),
                ),
            ),
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def _valid_backup_folder(self) -> bool:
        return bool(
            self.backup_folder is not None
            and self.backup_folder.is_dir()
            and not self.backup_folder.is_symlink()
        )


__all__ = ["DoctorTaskState"]
