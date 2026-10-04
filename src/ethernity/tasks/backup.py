#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ethernity.crypto.passphrases import MNEMONIC_WORD_COUNTS
from ethernity.page_sizes import DEFAULT_PAPER_SIZE_NAME, paper_size_display_name
from ethernity.render.recovery_kit_index import supports_recovery_kit_index_style
from ethernity.tasks.backup_debug import build_backup_internals_diagnostics
from ethernity.tasks.backup_estimate import BackupEstimate
from ethernity.tasks.backup_inputs import has_selected_inputs
from ethernity.tasks.file_summary import display_path, format_count, selected_paths_summary
from ethernity.tasks.models import (
    PreviewItem,
    TaskDiagnosticBlock,
    TaskDiagnostics,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskResultDetail,
    TaskSection,
    TaskSectionStatus,
    TaskValidation,
    optional_section_status,
)
from ethernity.tasks.output_checks import (
    existing_output_summary,
    existing_output_warning,
    selected_output_status,
)
from ethernity.tasks.page_layout import (
    BACKUP_RENDER_DOC_TYPES,
    ValidatedPaperSizeName,
    require_workflow_page_size,
)
from ethernity.tasks.quorum import validate_optional_shard_count, validate_required_shard_count
from ethernity.workflows.execution import (
    BackupRequest,
    execute_backup,
    prepare_backup,
)

RecoveryMethod = Literal["recommended_shards", "single_phrase", "custom_shards"]
SigningKeyMode = Literal["embedded", "sharded"]
AUTO_BACKUP_OUTPUT_LABEL = "Automatic folder named for backup ID"
AUTO_BACKUP_OUTPUT_PATH = Path("backup-<backup id>")


class BackupTaskState(BaseModel):
    """Beginner-facing state for creating a backup."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    input_paths: list[Path] = Field(default_factory=list)
    input_dirs: list[Path] = Field(default_factory=list)
    base_dir: Path | None = None
    output_dir: Path | None = None
    config_path: Path | None = None
    recovery_method: RecoveryMethod = "recommended_shards"
    shard_threshold: int = 2
    shard_count: int = 3
    passphrase: str | None = None
    passphrase_words: int | None = None
    paper_size: ValidatedPaperSizeName = DEFAULT_PAPER_SIZE_NAME
    design: str = "sentinel"
    qr_chunk_size: int | None = None
    signing_key_mode: SigningKeyMode | None = "embedded"
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None
    _estimate_request: BackupRequest | None = PrivateAttr(default=None)
    _estimate: BackupEstimate | None = PrivateAttr(default=None)
    _estimate_error: str | None = PrivateAttr(default=None)

    @field_validator("shard_threshold")
    @classmethod
    def _validate_recovery_shard_threshold(cls, value: int) -> int:
        return validate_required_shard_count(value, label="recovery document threshold")

    @field_validator("shard_count")
    @classmethod
    def _validate_recovery_shard_count(cls, value: int) -> int:
        if value == 0:
            return value
        return validate_required_shard_count(value, label="recovery document count")

    @field_validator("signing_key_shard_threshold", "signing_key_shard_count")
    @classmethod
    def _validate_signing_key_shard_count(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(value, label="signing key recovery document count")

    @model_validator(mode="after")
    def _validate_shards(self) -> BackupTaskState:
        require_workflow_page_size(
            self.design,
            self.paper_size,
            candidate_doc_types=BACKUP_RENDER_DOC_TYPES,
        )
        if self.passphrase == "":
            raise ValueError("passphrase cannot be empty")
        if (
            self.passphrase is not None
            and self.recovery_method == "single_phrase"
            and not self.passphrase.isprintable()
        ):
            raise ValueError(
                "directly printed passphrase must contain only manually enterable printable text"
            )
        if self.passphrase_words is not None and self.passphrase_words not in MNEMONIC_WORD_COUNTS:
            allowed = ", ".join(str(count) for count in MNEMONIC_WORD_COUNTS)
            raise ValueError(f"generated passphrase word count must be one of {allowed}")
        if self.passphrase is not None and self.passphrase_words is not None:
            raise ValueError("use either a passphrase or generated passphrase words, not both")
        if self.qr_chunk_size is not None and self.qr_chunk_size < 1:
            raise ValueError("QR chunk size must be positive")
        if self.signing_key_shard_threshold is not None and self.signing_key_shard_threshold < 1:
            raise ValueError("signing key threshold must be at least 1")
        if (
            self.signing_key_shard_threshold is not None
            and self.signing_key_shard_count is not None
            and self.signing_key_shard_count < self.signing_key_shard_threshold
        ):
            raise ValueError("signing key shard count must be at least the threshold")
        if self.recovery_method == "single_phrase":
            return self
        if self.shard_threshold < 1:
            raise ValueError("recovery sheet threshold must be at least 1")
        if self.shard_count < self.shard_threshold:
            raise ValueError("recovery sheet count must be at least the threshold")
        return self

    def sections(self) -> tuple[TaskSection, ...]:
        return (
            TaskSection(
                key="files",
                title="Files to back up",
                status=(
                    "ready" if has_selected_inputs(self.input_paths, self.input_dirs) else "missing"
                ),
                summary=selected_paths_summary(
                    input_paths=self.input_paths,
                    input_dirs=self.input_dirs,
                    base_dir=self.base_dir,
                    empty_label="Choose at least one file or folder.",
                ),
                action_label="Choose files...",
            ),
            TaskSection(
                key="recovery",
                title="Recovery method",
                status=self._recovery_status(),
                summary=self._recovery_summary(),
                action_label="Change recovery method...",
            ),
            TaskSection(
                key="print",
                title="Print setup",
                status="ready",
                summary=f"{paper_size_display_name(self.paper_size)}, {self.design.title()}",
                action_label="Change print setup",
            ),
            TaskSection(
                key="output",
                title="Save documents to",
                status=self._output_status(),
                summary=self._output_summary(),
                action_label="Choose custom output folder...",
            ),
            TaskSection(
                key="advanced",
                title="Advanced",
                status=optional_section_status(
                    self._advanced_issues(),
                    self._advanced_warnings(),
                ),
                summary=self._advanced_summary(),
                action_label="Change advanced options",
            ),
        )

    def validate_task(self) -> TaskValidation:
        issues: list[TaskIssue] = []
        if not has_selected_inputs(self.input_paths, self.input_dirs):
            issues.append(
                TaskIssue(
                    code="BACKUP_FILES_REQUIRED",
                    message="Choose at least one file or folder to back up.",
                    section="files",
                )
            )
        issues.extend(self._advanced_issues())
        return TaskValidation(sections=self.sections(), issues=tuple(issues))

    def preview(self) -> TaskPreview:
        estimate = self.current_estimate()
        items = [
            PreviewItem(
                label=(
                    f"About {format_count(estimate.backup_pages, 'backup page')}"
                    if estimate is not None
                    else "Backup pages"
                ),
                detail="Contain your encrypted files",
            ),
            PreviewItem(label="Recovery guide", detail="Instructions and a full text backup"),
        ]
        if self.recovery_method == "single_phrase":
            items.append(PreviewItem(label="One recovery phrase"))
        else:
            items.append(
                PreviewItem(
                    label=f"{self.shard_count} recovery sheets",
                    detail=f"Any {self.shard_threshold} unlock the backup",
                )
            )
            if self.signing_key_mode == "sharded":
                signing_threshold = self.signing_key_shard_threshold or self.shard_threshold
                signing_count = self.signing_key_shard_count or self.shard_count
                items.append(
                    PreviewItem(
                        label=f"{signing_count} signing-key recovery sheets",
                        detail=f"any {signing_threshold} can restore",
                    )
                )
        if supports_recovery_kit_index_style(self.design):
            items.append(PreviewItem(label="Document inventory", detail="Lists the printed kit"))
        items.append(
            PreviewItem(
                label="Print setup",
                detail=f"{paper_size_display_name(self.paper_size)}, {self.design.title()}",
            )
        )
        if self.qr_chunk_size is not None:
            items.append(PreviewItem(label="QR density", detail=f"{self.qr_chunk_size} bytes"))
        warnings = (
            *existing_output_warning(
                self.output_dir,
                code="BACKUP_OUTPUT_EXISTS",
                target="output_folder",
            ),
            *self._recovery_warnings(),
            *self._advanced_warnings(),
        )
        return TaskPreview(title="Documents to create", items=tuple(items), warnings=warnings)

    def execution_plan(self) -> TaskExecutionPlan:
        output_paths = (
            (self.output_dir,) if self.output_dir is not None else (AUTO_BACKUP_OUTPUT_PATH,)
        )
        return TaskExecutionPlan(
            summary=self._execution_summary(),
            read_paths=(*self.input_paths, *self.input_dirs),
            output_paths=output_paths,
            writes_files=True,
            safety_notes=(self._output_safety_note(),),
            trust_notes=(self._signing_review_note(),),
            recovery_notes=(
                self._recovery_summary(),
                "Store recovery sheets separately from encrypted backup documents.",
            ),
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        if not validation.ready:
            first_issue = validation.issues[0] if validation.issues else None
            message = first_issue.message if first_issue is not None else "Backup is not ready."
            raise ValueError(message)

        result = execute_backup(self.to_backup_request())
        output_paths = (
            result.qr_path,
            result.recovery_path,
            *result.shard_paths,
            *result.signing_key_shard_paths,
        )
        if result.kit_index_path is not None:
            output_paths = (*output_paths, Path(result.kit_index_path))
        return TaskExecutionResult(
            status="succeeded",
            message="Backup documents created.",
            output_paths=output_paths,
            recovery_check_paths=(
                result.qr_path,
                *result.shard_paths,
                *result.signing_key_shard_paths,
            ),
            details=_created_document_details(output_paths, result.qr_path, result.doc_hash),
            next_steps=("Verify recovery before relying on the printed documents.",),
        )

    def estimate_request(self) -> BackupRequest | None:
        """Return the inputs that affect print estimates, without recovery secrets."""

        if not has_selected_inputs(self.input_paths, self.input_dirs):
            return None
        return BackupRequest(
            config_path=self.config_path,
            input_paths=tuple(self.input_paths),
            input_dirs=tuple(self.input_dirs),
            base_dir=self.base_dir,
            paper_size=self.paper_size,
            design=self.design,
            qr_chunk_size=self.qr_chunk_size,
            signing_key_mode="embedded",
        )

    def store_estimate(
        self,
        request: BackupRequest,
        estimate: BackupEstimate | None,
        *,
        error: str | None = None,
    ) -> bool:
        if request != self.estimate_request():
            return False
        self._estimate_request = request
        self._estimate = estimate
        self._estimate_error = error
        return True

    def clear_estimate(self) -> None:
        self._estimate_request = None
        self._estimate = None
        self._estimate_error = None

    def current_estimate(self) -> BackupEstimate | None:
        if self._estimate_request != self.estimate_request():
            return None
        return self._estimate

    def estimate_error(self) -> str | None:
        if self._estimate_request != self.estimate_request():
            return None
        return self._estimate_error

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def diagnostics_available(self) -> bool:
        return has_selected_inputs(self.input_paths, self.input_dirs)

    def diagnostics(self) -> TaskDiagnostics:
        if not has_selected_inputs(self.input_paths, self.input_dirs):
            return TaskDiagnostics(title="Backup diagnostics")

        try:
            prepared = prepare_backup(self.to_backup_request())
        except Exception as exc:
            return TaskDiagnostics(
                title="Backup diagnostics",
                blocks=(
                    TaskDiagnosticBlock(
                        title="Preparation Error",
                        content=f"{type(exc).__name__}: {exc}",
                    ),
                ),
            )

        return build_backup_internals_diagnostics(prepared, passphrase=self.passphrase)

    def to_backup_request(self) -> BackupRequest:
        shard_threshold, shard_count = self._shard_configuration()
        return BackupRequest(
            config_path=self.config_path,
            input_paths=tuple(self.input_paths),
            input_dirs=tuple(self.input_dirs),
            base_dir=self.base_dir,
            output_dir=self.output_dir,
            passphrase=self.passphrase,
            passphrase_words=self.passphrase_words,
            shard_threshold=shard_threshold,
            shard_count=shard_count,
            signing_key_mode=self.signing_key_mode,
            signing_key_shard_threshold=self.signing_key_shard_threshold,
            signing_key_shard_count=self.signing_key_shard_count,
            paper_size=self.paper_size,
            design=self.design,
            qr_chunk_size=self.qr_chunk_size,
        )

    def _shard_configuration(self) -> tuple[int | None, int | None]:
        if self.recovery_method == "single_phrase":
            return None, None
        return self.shard_threshold, self.shard_count

    def _execution_summary(self) -> str:
        output = (
            str(self.output_dir)
            if self.output_dir is not None
            else "an automatic folder named for the backup ID"
        )
        return f"Create backup documents in {output}"

    def _output_status(self) -> TaskSectionStatus:
        if self.output_dir is None:
            return "ready"
        return selected_output_status(self.output_dir)

    def _output_summary(self) -> str:
        if self.output_dir is None:
            return AUTO_BACKUP_OUTPUT_LABEL
        return existing_output_summary(
            self.output_dir,
            target="output_folder",
            missing_summary=AUTO_BACKUP_OUTPUT_LABEL,
        )

    def _output_safety_note(self) -> str:
        if self.output_dir is None:
            return "Ethernity will create a folder named for the backup ID in the current folder."
        return "Ethernity will create the folder if needed and write the backup PDFs inside it."

    def _recovery_summary(self) -> str:
        if self.recovery_method == "single_phrase":
            return "One recovery phrase"
        if self.recovery_method == "recommended_shards":
            return "3 recovery sheets; any 2 can restore (recommended)"
        return f"{self.shard_count} recovery sheets; any {self.shard_threshold} required"

    def _recovery_status(self) -> TaskSectionStatus:
        if self.recovery_method == "recommended_shards":
            return "ready"
        return "warning"

    def _recovery_warnings(self) -> tuple[TaskIssue, ...]:
        if self.recovery_method == "single_phrase":
            return (
                TaskIssue(
                    code="BACKUP_SINGLE_RECOVERY_PHRASE",
                    message=(
                        "One recovery phrase is a single secret; store it carefully because "
                        "there are no spare recovery sheets."
                    ),
                    severity="warning",
                    section="recovery",
                ),
            )
        if self.recovery_method == "custom_shards":
            return (
                TaskIssue(
                    code="BACKUP_CUSTOM_RECOVERY_QUORUM",
                    message="A custom quorum changes how many sheets you need to restore.",
                    severity="warning",
                    section="recovery",
                ),
            )
        return ()

    def _signing_review_note(self) -> str:
        if self.signing_key_mode == "sharded":
            return "Separate signing-key recovery sheets will be created."
        if self.signing_key_mode == "embedded":
            return "The signing key will be embedded in the backup documents."
        return "Signing-key recovery follows the configured backup policy."

    def _advanced_summary(self) -> str:
        parts: list[str] = []
        if self.base_dir is not None:
            parts.append(f"base folder {display_path(self.base_dir)}")
        if self.passphrase is not None:
            parts.append("custom passphrase")
        elif self.passphrase_words is not None:
            parts.append(f"{self.passphrase_words} generated words")
        if self.signing_key_mode == "sharded":
            threshold = self.signing_key_shard_threshold or self.shard_threshold
            count = self.signing_key_shard_count or self.shard_count
            parts.append(f"{count} key sheets, any {threshold} required")
        else:
            parts.append("signing key embedded")
        if self.qr_chunk_size is not None:
            parts.append(f"QR {self.qr_chunk_size} bytes")
        return ", ".join(parts)

    def _advanced_warnings(self) -> tuple[TaskIssue, ...]:
        if self.qr_chunk_size is None:
            return ()
        return (
            TaskIssue(
                code="BACKUP_CUSTOM_QR_DENSITY",
                message=("Custom QR density can change page count and make codes harder to scan."),
                severity="warning",
                section="advanced",
            ),
        )

    def _advanced_issues(self) -> list[TaskIssue]:
        issues: list[TaskIssue] = []
        has_signing_threshold = self.signing_key_shard_threshold is not None
        has_signing_count = self.signing_key_shard_count is not None
        if has_signing_threshold != has_signing_count:
            issues.append(
                TaskIssue(
                    code="BACKUP_SIGNING_KEY_QUORUM_INCOMPLETE",
                    message="Set both required and total key-sheet counts.",
                    severity="error",
                    section="advanced",
                )
            )
        if (has_signing_threshold or has_signing_count) and self.signing_key_mode != "sharded":
            issues.append(
                TaskIssue(
                    code="BACKUP_SIGNING_KEY_QUORUM_MODE_REQUIRED",
                    message="Choose separate key sheets before setting their quorum.",
                    severity="error",
                    section="advanced",
                )
            )
        if self.signing_key_mode == "sharded" and self.recovery_method == "single_phrase":
            issues.append(
                TaskIssue(
                    code="BACKUP_SIGNING_KEY_SHARDS_REQUIRE_RECOVERY_DOCS",
                    message="Separate key sheets require recovery sheets.",
                    severity="error",
                    section="recovery",
                )
            )
        return issues


def _created_document_details(
    output_paths: tuple[Path, ...], backup_path: Path, doc_hash: bytes | None
) -> tuple[TaskResultDetail, ...]:
    """Report generated identity and page counts available from the created PDFs."""

    identity = (
        (TaskResultDetail(key="doc_hash", label="Full fingerprint", value=doc_hash.hex()),)
        if doc_hash is not None
        else ()
    )
    try:
        if not output_paths or any(not path.is_file() for path in output_paths):
            return identity
        counts = {path: len(PdfReader(path).pages) for path in output_paths}
    except (OSError, ValueError, PdfReadError):
        return identity
    return (
        *identity,
        TaskResultDetail(key="backup_pages", label="Backup pages", value=counts[backup_path]),
        TaskResultDetail(
            key="printed_pages", label="Total printed pages", value=sum(counts.values())
        ),
        TaskResultDetail(key="documents", label="PDF documents", value=len(output_paths)),
    )
