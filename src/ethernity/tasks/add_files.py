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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ethernity.cli.features.extend.execution import execute_prepared_extend
from ethernity.cli.features.extend.prepare import prepare_extend_run
from ethernity.cli.shared.types import ExtendArgs
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskSection,
    TaskSectionStatus,
    TaskValidation,
)
from ethernity.tasks.quorum import validate_optional_shard_count

AddFilesUnlockPolicy = Literal["self-contained", "reuse-root"]
AddFilesSigningKeyMode = Literal["not-stored", "sharded"]


class AddFilesTaskState(BaseModel):
    """Beginner-facing state for adding files to an existing backup."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    backup_folder: Path | None = None
    config_path: Path | None = None
    source_paths: list[Path] = Field(default_factory=list)
    input_paths: list[Path] = Field(default_factory=list)
    input_dirs: list[Path] = Field(default_factory=list)
    base_dir: Path | None = None
    passphrase: str | None = None
    recovery_documents: list[Path] = Field(default_factory=list)
    recovery_payload_files: list[Path] = Field(default_factory=list)
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    unlock_policy: AddFilesUnlockPolicy = "self-contained"
    recovery_document_threshold: int | None = None
    recovery_document_count: int | None = None
    signing_key_mode: AddFilesSigningKeyMode | None = None
    signing_key_recovery_threshold: int | None = None
    signing_key_recovery_count: int | None = None
    paper_size: str = "A4"
    design: str = "sentinel"
    qr_chunk_size: int | None = None

    @field_validator("recovery_document_threshold")
    @classmethod
    def _validate_recovery_threshold(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(value, label="recovery document threshold")

    @field_validator("recovery_document_count")
    @classmethod
    def _validate_recovery_count(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(
            value,
            label="recovery document count",
            allow_zero=True,
        )

    @field_validator("signing_key_recovery_threshold")
    @classmethod
    def _validate_signing_key_threshold(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(value, label="signing key recovery threshold")

    @field_validator("signing_key_recovery_count")
    @classmethod
    def _validate_signing_key_count(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(value, label="signing key recovery count")

    @model_validator(mode="after")
    def _validate_qr_chunk_size(self) -> AddFilesTaskState:
        if self.qr_chunk_size is not None and self.qr_chunk_size < 1:
            raise ValueError("QR chunk size must be positive")
        return self

    def sections(self) -> tuple[TaskSection, ...]:
        return (
            TaskSection(
                key="backup",
                title="Existing backup",
                status="ready" if self.backup_folder is not None else "missing",
                summary=str(self.backup_folder)
                if self.backup_folder is not None
                else "No existing backup selected.",
                action_label="Choose backup folder...",
            ),
            TaskSection(
                key="source",
                title="Loaded backup source",
                status=self._source_status(),
                summary=self._source_summary(),
                action_label="Load scanned pages...",
            ),
            TaskSection(
                key="files",
                title="Files to add",
                status="ready" if self._has_inputs() else "missing",
                summary=self._input_summary(),
                action_label="Choose files...",
            ),
            TaskSection(
                key="unlock",
                title="Unlock backup",
                status="ready" if self._has_unlock() else "missing",
                summary=self._unlock_summary(),
                action_label="Set unlock method...",
            ),
            TaskSection(
                key="output",
                title="Save updated backup documents to",
                status="ready" if self.backup_folder is not None else "missing",
                summary=self._output_summary(),
                action_label="Choose backup folder...",
            ),
            TaskSection(
                key="advanced",
                title="Advanced update options",
                status="ready" if not self._advanced_issues() else "missing",
                summary=self._advanced_summary(),
                action_label="Review options",
            ),
        )

    def validate_task(self) -> TaskValidation:
        issues: list[TaskIssue] = []
        if self.backup_folder is None:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_BACKUP_REQUIRED",
                    message="Choose the generated backup folder to update.",
                    section="backup",
                )
            )
        if not self._has_inputs():
            issues.append(
                TaskIssue(
                    code="ADD_FILES_INPUT_REQUIRED",
                    message="Choose at least one file or folder to add.",
                    section="files",
                )
            )
        if not self._has_unlock():
            issues.append(
                TaskIssue(
                    code="ADD_FILES_UNLOCK_REQUIRED",
                    message="Choose a passphrase or recovery sheets.",
                    section="unlock",
                )
            )
        if self.source_paths and self.expected_head_doc_hash is None and not self.allow_stale_head:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_HEAD_TRUST_REQUIRED",
                    message=(
                        "When using scans as the current source, provide the expected latest "
                        "backup fingerprint or explicitly allow a stale source."
                    ),
                    section="source",
                )
            )
        issues.extend(self._advanced_issues())
        return TaskValidation(sections=self.sections(), issues=tuple(issues))

    def preview(self) -> TaskPreview:
        warnings = (
            TaskIssue(
                code="FINAL_REVIEW_REQUIRED",
                message="Nothing will be written until final review.",
                severity="warning",
            ),
        )
        items = [
            PreviewItem(label="Existing backup", detail=str(self.backup_folder or "missing")),
            PreviewItem(label="Files to add", detail=self._input_summary()),
            PreviewItem(label="Unlock method", detail=self._unlock_summary()),
            PreviewItem(label="Output location", detail=self._output_summary()),
            PreviewItem(label="Recovery sheets", detail=self._recovery_documents_summary()),
            PreviewItem(label="Signing key", detail=self._signing_key_summary()),
            PreviewItem(label="New update documents", detail="main, recovery, and any sheets"),
        ]
        if self.qr_chunk_size is not None:
            items.append(PreviewItem(label="QR chunk size", detail=f"{self.qr_chunk_size} bytes"))
        return TaskPreview(
            title="Backup update to create",
            items=tuple(items),
            warnings=warnings,
        )

    def execution_plan(self) -> TaskExecutionPlan:
        outputs = (self.backup_folder,) if self.backup_folder is not None else ()
        return TaskExecutionPlan(
            summary=f"Add files to {self.backup_folder or 'missing backup folder'}",
            output_paths=outputs,
            writes_files=True,
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        if not validation.ready:
            first_issue = validation.issues[0] if validation.issues else None
            message = first_issue.message if first_issue is not None else "Add-files is not ready."
            raise ValueError(message)

        executed = execute_prepared_extend(prepare_extend_run(self.to_extend_args(quiet=True)))
        result = executed.result
        output_paths = (
            result.qr_document_path,
            result.recovery_document_path,
            *result.shard_paths,
            *result.signing_key_shard_paths,
        )
        if result.recovery_kit_index_path is not None:
            output_paths = (*output_paths, result.recovery_kit_index_path)
        return TaskExecutionResult(
            ok=True,
            message=f"Added files as backup update {result.index:02d}.",
            output_paths=output_paths,
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def to_extend_args(self, *, quiet: bool = False) -> ExtendArgs:
        return ExtendArgs(
            config=str(self.config_path) if self.config_path is not None else None,
            root_dir=str(self.backup_folder) if self.backup_folder is not None else None,
            scan=[str(path) for path in self.source_paths],
            input=[str(path) for path in self.input_paths],
            input_dir=[str(path) for path in self.input_dirs],
            base_dir=str(self.base_dir) if self.base_dir is not None else None,
            passphrase=self.passphrase,
            shard_scan=[str(path) for path in self.recovery_documents],
            shard_payloads_file=[str(path) for path in self.recovery_payload_files],
            unlock_policy=self.unlock_policy,
            shard_threshold=self.recovery_document_threshold,
            shard_count=self.recovery_document_count,
            signing_key_mode=self.signing_key_mode,
            signing_key_shard_threshold=self.signing_key_recovery_threshold,
            signing_key_shard_count=self.signing_key_recovery_count,
            expected_head_doc_hash=self.expected_head_doc_hash,
            allow_stale_head=self.allow_stale_head,
            paper=self.paper_size,
            design=self.design,
            qr_chunk_size=self.qr_chunk_size,
            quiet=quiet,
        )

    def _has_inputs(self) -> bool:
        return bool(self.input_paths or self.input_dirs)

    def _has_unlock(self) -> bool:
        return bool(self.passphrase or self.recovery_documents or self.recovery_payload_files)

    def _source_status(self) -> TaskSectionStatus:
        if not self.source_paths:
            return "ready"
        if self.expected_head_doc_hash is not None or self.allow_stale_head:
            return "ready"
        return "missing"

    def _source_summary(self) -> str:
        if self.source_paths:
            if self.expected_head_doc_hash is not None:
                return "Expected latest backup fingerprint provided"
            if self.allow_stale_head:
                return "Stale source risk accepted"
            return f"{len(self.source_paths)} scanned page path(s)"
        return "Use backup folder"

    def _input_summary(self) -> str:
        count = len(self.input_paths) + len(self.input_dirs)
        if count == 0:
            return "No files selected yet."
        return f"{count} path(s) selected"

    def _unlock_summary(self) -> str:
        if self.passphrase:
            return "Passphrase provided"
        if self.recovery_documents:
            return f"{len(self.recovery_documents)} recovery sheet(s)"
        if self.recovery_payload_files:
            return f"{len(self.recovery_payload_files)} recovery payload file(s)"
        return "Choose passphrase or recovery sheets"

    def _output_summary(self) -> str:
        if self.backup_folder is None:
            return "No destination selected. Updates are saved in the existing backup folder."
        return f"Updates will be saved in {self.backup_folder}"

    def _advanced_summary(self) -> str:
        parts = [
            self.unlock_policy.replace("-", " "),
            self._recovery_documents_summary(),
            self._signing_key_summary(),
        ]
        if self.base_dir is not None:
            parts.append(f"base {self.base_dir}")
        if self.qr_chunk_size is not None:
            parts.append(f"QR {self.qr_chunk_size} bytes")
        return ", ".join(parts)

    def _recovery_documents_summary(self) -> str:
        if self.recovery_document_count == 0:
            return "No new recovery sheets"
        if (
            self.recovery_document_threshold is not None
            and self.recovery_document_count is not None
        ):
            return (
                f"{self.recovery_document_count} recovery sheets; "
                f"any {self.recovery_document_threshold} required"
            )
        return "Using saved recovery-sheet defaults"

    def _signing_key_summary(self) -> str:
        if self.signing_key_mode is None:
            return "Default signing key policy"
        if self.signing_key_mode == "not-stored":
            return "Signing key not stored"
        if (
            self.signing_key_recovery_threshold is not None
            and self.signing_key_recovery_count is not None
        ):
            return (
                "Signing key shards any "
                f"{self.signing_key_recovery_threshold} of {self.signing_key_recovery_count}"
            )
        return "Signing key sharded"

    def _advanced_issues(self) -> tuple[TaskIssue, ...]:
        issues: list[TaskIssue] = []
        if self.unlock_policy == "reuse-root" and (
            self.recovery_document_threshold is not None or self.recovery_document_count is not None
        ):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_REUSE_ROOT_RECOVERY_OVERRIDE",
                    message=(
                        "Reuse root recovery cannot be combined with new recovery sheet settings."
                    ),
                    section="advanced",
                )
            )
        if self.recovery_document_count == 0 and self.recovery_document_threshold is not None:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_RECOVERY_THRESHOLD_WITHOUT_DOCUMENTS",
                    message="Clear the recovery threshold or create recovery sheets.",
                    section="advanced",
                )
            )
        if (
            self.recovery_document_threshold is not None
            and self.recovery_document_count is not None
            and self.recovery_document_count > 0
            and self.recovery_document_threshold > self.recovery_document_count
        ):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_RECOVERY_QUORUM_INVALID",
                    message="Recovery threshold cannot be greater than recovery sheet count.",
                    section="advanced",
                )
            )
        if self.signing_key_mode == "not-stored" and (
            self.signing_key_recovery_threshold is not None
            or self.signing_key_recovery_count is not None
        ):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SIGNING_KEY_SHARDS_NOT_STORED",
                    message="Signing key shard settings require signing key mode to be sharded.",
                    section="advanced",
                )
            )
        if (
            self.signing_key_recovery_threshold is not None
            and self.signing_key_recovery_count is not None
            and self.signing_key_recovery_threshold > self.signing_key_recovery_count
        ):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SIGNING_KEY_QUORUM_INVALID",
                    message="Signing-key threshold cannot be greater than signing-key shard count.",
                    section="advanced",
                )
            )
        if self.signing_key_mode == "sharded" and self.recovery_document_count == 0:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SIGNING_KEY_REQUIRES_RECOVERY_DOCS",
                    message="Signing-key shards require passphrase recovery sheets.",
                    section="advanced",
                )
            )
        return tuple(issues)
