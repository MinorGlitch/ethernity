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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ethernity.cli.features.mint.workflow import execute_mint
from ethernity.cli.shared.types import MintArgs
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
from ethernity.tasks.quorum import validate_optional_shard_count, validate_required_shard_count


class ReplaceRecoveryDocsTaskState(BaseModel):
    """Beginner-facing state for creating replacement recovery sheets."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    source_paths: list[Path] = Field(default_factory=list)
    recovery_text_file: Path | None = None
    payloads_file: Path | None = None
    config_path: Path | None = None
    output_dir: Path | None = None
    passphrase: str | None = None
    recovery_documents: list[Path] = Field(default_factory=list)
    recovery_payload_files: list[Path] = Field(default_factory=list)
    signing_key_recovery_payload_files: list[Path] = Field(default_factory=list)
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    recovery_threshold: int = 2
    recovery_document_count: int = 3
    mint_passphrase_recovery: bool = True
    mint_signing_key_recovery: bool = False
    signing_key_recovery_threshold: int | None = None
    signing_key_recovery_count: int | None = None
    passphrase_replacement_count: int | None = None
    signing_key_replacement_count: int | None = None
    paper_size: str = "A4"
    design: str = "sentinel"

    @field_validator("recovery_threshold", "recovery_document_count")
    @classmethod
    def _validate_recovery_shard_count(cls, value: int) -> int:
        return validate_required_shard_count(value, label="recovery document count")

    @field_validator("signing_key_recovery_threshold", "signing_key_recovery_count")
    @classmethod
    def _validate_signing_key_recovery_count(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(value, label="signing key recovery document count")

    @model_validator(mode="after")
    def _validate_recovery_document_counts(self) -> ReplaceRecoveryDocsTaskState:
        if self.recovery_threshold < 1:
            raise ValueError("recovery document threshold must be at least 1")
        if self.recovery_document_count < self.recovery_threshold:
            raise ValueError("recovery document count must be at least the threshold")
        if self.passphrase_replacement_count is not None and self.passphrase_replacement_count < 1:
            raise ValueError("passphrase replacement count must be at least 1")
        if (
            self.signing_key_recovery_threshold is not None
            and self.signing_key_recovery_count is not None
            and self.signing_key_recovery_count < self.signing_key_recovery_threshold
        ):
            raise ValueError("signing key recovery document count must be at least the threshold")
        if (
            self.signing_key_replacement_count is not None
            and self.signing_key_replacement_count < 1
        ):
            raise ValueError("signing key replacement count must be at least 1")
        return self

    def sections(self) -> tuple[TaskSection, ...]:
        return (
            TaskSection(
                key="source",
                title="Existing backup",
                status="ready" if self._has_source() else "missing",
                summary=self._source_summary(),
                action_label="Load backup...",
            ),
            TaskSection(
                key="unlock",
                title="Unlock existing backup",
                status="ready" if self._has_unlock() else "missing",
                summary=self._unlock_summary(),
                action_label="Set unlock method...",
            ),
            TaskSection(
                key="freshness",
                title="Freshness",
                status=self._freshness_status(),
                summary=self._freshness_summary(),
                action_label="Confirm source",
            ),
            TaskSection(
                key="output",
                title="Save replacement sheets to",
                status="ready" if self.output_dir is not None else "missing",
                summary=(
                    str(self.output_dir)
                    if self.output_dir is not None
                    else "No output folder selected."
                ),
                action_label="Choose output folder...",
            ),
            TaskSection(
                key="recovery",
                title="New recovery method",
                status="ready",
                summary=(
                    f"{self.recovery_document_count} new recovery sheets; "
                    f"any {self.recovery_threshold} can restore"
                ),
                action_label="Change recovery method...",
            ),
        )

    def validate_task(self) -> TaskValidation:
        issues: list[TaskIssue] = []
        if not self._has_source():
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_SOURCE_REQUIRED",
                    message="Load a backup before continuing.",
                    section="source",
                )
            )
        if not self._has_unlock():
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_UNLOCK_REQUIRED",
                    message="Provide the passphrase or current recovery sheets.",
                    section="unlock",
                )
            )
        if self.source_paths and self.expected_head_doc_hash is None and not self.allow_stale_head:
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_HEAD_TRUST_REQUIRED",
                    message=(
                        "When using scans, provide the expected latest backup fingerprint "
                        "or explicitly allow a stale source."
                    ),
                    section="freshness",
                )
            )
        if self.output_dir is None:
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_OUTPUT_REQUIRED",
                    message="Choose where replacement recovery sheets will be saved.",
                    section="output",
                )
            )
        if (
            self.signing_key_recovery_threshold is not None
            or self.signing_key_recovery_count is not None
        ) and (
            self.signing_key_recovery_threshold is None or self.signing_key_recovery_count is None
        ):
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_SIGNING_KEY_QUORUM_REQUIRED",
                    message="Set both signing key recovery threshold and document count.",
                    section="recovery",
                )
            )
        if not self.mint_passphrase_recovery and not self._creates_signing_key_recovery():
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_DOCUMENT_TYPE_REQUIRED",
                    message="Choose at least one replacement recovery sheet type.",
                    section="recovery",
                )
            )
        if self.passphrase_replacement_count is not None and not self.mint_passphrase_recovery:
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_PASSPHRASE_REPLACEMENT_DISABLED",
                    message="Passphrase replacement count requires passphrase recovery output.",
                    section="recovery",
                )
            )
        if self.passphrase_replacement_count is not None and not (
            self.recovery_documents or self.recovery_payload_files
        ):
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_PASSPHRASE_REPLACEMENT_INPUT_REQUIRED",
                    message="Passphrase replacement count requires existing recovery documents.",
                    section="unlock",
                )
            )
        if (
            self.signing_key_replacement_count is not None
            and not self.signing_key_recovery_payload_files
        ):
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_SIGNING_KEY_REPLACEMENT_INPUT_REQUIRED",
                    message=(
                        "Signing key replacement count requires existing signing-key "
                        "recovery payloads."
                    ),
                    section="recovery",
                )
            )
        return TaskValidation(sections=self.sections(), issues=tuple(issues))

    def preview(self) -> TaskPreview:
        items = [
            PreviewItem(label="Existing backup", detail=self._source_summary()),
            PreviewItem(label="Unlock method", detail=self._unlock_summary()),
            PreviewItem(label="Output folder", detail=str(self.output_dir or "missing")),
        ]
        if self.mint_passphrase_recovery:
            if self.passphrase_replacement_count is not None:
                items.append(
                    PreviewItem(
                        label="Passphrase recovery replacements",
                        detail=f"{self.passphrase_replacement_count} sheet(s)",
                    )
                )
            else:
                items.append(
                    PreviewItem(
                        label=f"{self.recovery_document_count} recovery sheets",
                        detail=f"any {self.recovery_threshold} can restore",
                    )
                )
        if self._creates_signing_key_recovery():
            items.append(
                PreviewItem(
                    label="Signing-key recovery sheets",
                    detail=self._signing_key_recovery_summary(),
                )
            )
        if self.signing_key_recovery_payload_files:
            items.append(
                PreviewItem(
                    label="Signing key recovery payloads",
                    detail=f"{len(self.signing_key_recovery_payload_files)} file(s)",
                )
            )
        warnings = (
            TaskIssue(
                code="FINAL_REVIEW_REQUIRED",
                message="Nothing will be written until final review.",
                severity="warning",
            ),
        )
        return TaskPreview(
            title="Replacement recovery sheets to create",
            items=tuple(items),
            warnings=warnings,
        )

    def execution_plan(self) -> TaskExecutionPlan:
        outputs = (self.output_dir,) if self.output_dir is not None else ()
        return TaskExecutionPlan(
            summary=(
                f"Create replacement recovery sheets in {self.output_dir or 'missing output'}"
            ),
            output_paths=outputs,
            writes_files=True,
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        if not validation.ready:
            first_issue = validation.issues[0] if validation.issues else None
            message = (
                first_issue.message
                if first_issue is not None
                else "Replacement recovery sheets are not ready."
            )
            raise ValueError(message)

        result = execute_mint(self.to_mint_args(quiet=True))
        output_paths = (
            Path(result.output_dir),
            *[Path(path) for path in result.shard_paths],
            *[Path(path) for path in result.signing_key_shard_paths],
        )
        return TaskExecutionResult(
            ok=True,
            message="Replacement recovery sheets created.",
            output_paths=output_paths,
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def to_mint_args(self, *, quiet: bool = False) -> MintArgs:
        return MintArgs(
            config=str(self.config_path) if self.config_path is not None else None,
            paper=self.paper_size,
            design=self.design,
            fallback_file=str(self.recovery_text_file) if self.recovery_text_file else None,
            payloads_file=str(self.payloads_file) if self.payloads_file else None,
            scan=[str(path) for path in self.source_paths],
            passphrase=self.passphrase,
            shard_scan=[str(path) for path in self.recovery_documents],
            shard_payloads_file=[str(path) for path in self.recovery_payload_files],
            signing_key_shard_payloads_file=[
                str(path) for path in self.signing_key_recovery_payload_files
            ],
            expected_head_doc_hash=self.expected_head_doc_hash,
            allow_stale_head=self.allow_stale_head,
            output_dir=str(self.output_dir) if self.output_dir is not None else None,
            output_dir_existing_parent=False,
            shard_threshold=self.recovery_threshold,
            shard_count=self.recovery_document_count,
            signing_key_shard_threshold=self.signing_key_recovery_threshold,
            signing_key_shard_count=self.signing_key_recovery_count,
            passphrase_replacement_count=self.passphrase_replacement_count,
            signing_key_replacement_count=self.signing_key_replacement_count,
            mint_passphrase_shards=self.mint_passphrase_recovery,
            mint_signing_key_shards=self._creates_signing_key_recovery(),
            quiet=quiet,
        )

    def _has_source(self) -> bool:
        return bool(self.source_paths or self.recovery_text_file or self.payloads_file)

    def _has_unlock(self) -> bool:
        return bool(self.passphrase or self.recovery_documents or self.recovery_payload_files)

    def _creates_signing_key_recovery(self) -> bool:
        return bool(
            self.mint_signing_key_recovery
            or self.signing_key_replacement_count is not None
            or self.signing_key_recovery_threshold is not None
            or self.signing_key_recovery_count is not None
        )

    def _signing_key_recovery_summary(self) -> str:
        if self.signing_key_replacement_count is not None:
            return f"{self.signing_key_replacement_count} replacement document(s)"
        threshold = self.signing_key_recovery_threshold or self.recovery_threshold
        count = self.signing_key_recovery_count or self.recovery_document_count
        return f"need any {threshold} of {count}"

    def passphrase_recovery_summary(self) -> str:
        if not self.mint_passphrase_recovery:
            return "Do not create passphrase recovery documents"
        if self.passphrase_replacement_count is not None:
            return f"Replace {self.passphrase_replacement_count} existing document(s)"
        return (
            f"Create {self.recovery_document_count} document(s), need any {self.recovery_threshold}"
        )

    def signing_key_recovery_payloads_summary(self) -> str:
        if not self.signing_key_recovery_payload_files:
            return "No signing key payloads selected"
        return f"{len(self.signing_key_recovery_payload_files)} signing key payload file(s)"

    def _source_summary(self) -> str:
        sources = len(self.source_paths)
        if sources:
            return f"{sources} scanned page path(s)"
        if self.recovery_text_file is not None:
            return str(self.recovery_text_file)
        if self.payloads_file is not None:
            return str(self.payloads_file)
        return "Load scanned pages, paste recovery text, or load payload files."

    def _unlock_summary(self) -> str:
        if self.passphrase:
            return "Passphrase provided"
        if self.recovery_documents:
            return f"{len(self.recovery_documents)} recovery sheet(s)"
        if self.recovery_payload_files:
            return f"{len(self.recovery_payload_files)} recovery payload file(s)"
        return "Choose passphrase or current recovery sheets"

    def _freshness_status(self) -> TaskSectionStatus:
        if not self.source_paths:
            return "ready"
        if self.expected_head_doc_hash is not None or self.allow_stale_head:
            return "ready"
        return "missing"

    def _freshness_summary(self) -> str:
        if not self.source_paths:
            return "Recovery text source"
        if self.expected_head_doc_hash is not None:
            return "Expected latest backup fingerprint provided"
        if self.allow_stale_head:
            return "Stale source risk accepted"
        return "Confirm these scans are latest"
