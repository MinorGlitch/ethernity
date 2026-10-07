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

from pydantic import ConfigDict, Field, model_validator

from ethernity.page_sizes import DEFAULT_PAPER_SIZE_NAME
from ethernity.tasks.common_sections import (
    destination_preview,
    freshness_section,
    unchanged_backup_preview,
    unlock_section,
)
from ethernity.tasks.file_summary import display_path, format_count
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
from ethernity.tasks.page_layout import (
    BACKUP_RENDER_DOC_TYPES,
    ValidatedPaperSizeName,
    require_workflow_page_size,
)
from ethernity.tasks.presentation.recovery import recovery_text_summary, unlock_input_summary
from ethernity.tasks.quorum import (
    OptionalSigningDocumentCount,
    RecoveryDocumentCount,
    validate_required_shard_count,
)
from ethernity.tasks.recovery_inputs import (
    has_recovery_source,
    has_unlock_inputs,
    recovery_text_error,
    recovery_text_frames,
)
from ethernity.tasks.source_assessment import (
    ContentRecoveryTaskState,
    SourceAssessmentRequest,
    source_freshness_status,
)
from ethernity.workflows.execution import execute_replacement_recovery
from ethernity.workflows.replacement_recovery.service import (
    require_replacement_recovery_output_available,
)
from ethernity.workflows.shared.requests import ReplacementRecoveryRequest

SIGNING_KEY_RECOVERY_OFF_WARNING = (
    "No separate signing-key recovery sheets will be created. The replacement documents "
    "remain signed."
)


class ReplaceRecoveryDocsTaskState(ContentRecoveryTaskState):
    """Beginner-facing state for creating replacement recovery sheets."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    output_dir: Path | None = None
    signing_key_recovery_payload_files: list[Path] = Field(default_factory=list)
    allow_stale_head: bool = False
    recovery_threshold: RecoveryDocumentCount = 2
    recovery_document_count: RecoveryDocumentCount = 3
    create_passphrase_recovery: bool = True
    create_signing_key_recovery: bool = False
    signing_key_recovery_threshold: OptionalSigningDocumentCount = None
    signing_key_recovery_count: OptionalSigningDocumentCount = None
    passphrase_replacement_count: int | None = None
    signing_key_replacement_count: int | None = None
    paper_size: ValidatedPaperSizeName = DEFAULT_PAPER_SIZE_NAME
    design: str = "sentinel"

    @model_validator(mode="after")
    def _validate_recovery_document_counts(self) -> ReplaceRecoveryDocsTaskState:
        require_workflow_page_size(
            self.design,
            self.paper_size,
            candidate_doc_types=BACKUP_RENDER_DOC_TYPES,
        )
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
        source_error = recovery_text_error(self.recovery_text)
        return (
            self.source_section("Existing backup", source_error, self._source_summary()),
            unlock_section(self, "Unlock existing backup"),
            freshness_section(
                source_freshness_status(
                    self.source_paths,
                    expected_head_doc_hash=self.expected_head_doc_hash,
                    allow_stale_head=self.allow_stale_head,
                ),
                self._freshness_summary(),
                "Scan version",
            ),
            self._output_section(),
            TaskSection(
                key="signature",
                title="Signing-key recovery",
                status="ready" if self._creates_signing_key_recovery() else "warning",
                summary=self._signing_key_section_summary(),
                action_label="Change key-sheet options",
            ),
            TaskSection(
                key="recovery",
                title="Recovery sheets",
                status=self._recovery_status(),
                summary=(
                    f"{self.recovery_document_count} new recovery sheets; "
                    f"any {self.recovery_threshold} can restore"
                ),
                action_label="Change recovery method...",
            ),
        )

    def set_recovery_quorum(self, threshold: int, count: int) -> None:
        """Apply an already validated quorum without an invalid intermediate assignment."""

        if threshold < 1 or count < threshold:
            raise ValueError("recovery quorum must use 1 <= required <= total")
        validate_required_shard_count(threshold, label="recovery document threshold")
        validate_required_shard_count(count, label="recovery document count")
        if count < self.recovery_threshold:
            self.recovery_threshold = threshold
            self.recovery_document_count = count
        else:
            self.recovery_document_count = count
            self.recovery_threshold = threshold

    def validate_task(self) -> TaskValidation:
        issues: list[TaskIssue] = []
        if not has_recovery_source(self):
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_SOURCE_REQUIRED",
                    message="Choose backup documents.",
                    section="source",
                )
            )
        issues.extend(self.recovery_text_issues("REPLACE_RECOVERY_TEXT_INVALID"))
        if not has_unlock_inputs(self):
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_UNLOCK_REQUIRED",
                    message=(
                        "Choose the passphrase, current recovery sheets, or recovery payload files."
                    ),
                    section="unlock",
                )
            )
        if self.source_paths and self.expected_head_doc_hash is None and not self.allow_stale_head:
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_HEAD_TRUST_REQUIRED",
                    message=(
                        "Enter the expected latest fingerprint, or accept that the scans may "
                        "be stale."
                    ),
                    section="freshness",
                )
            )
        issues.extend(self._output_issues())
        issues.extend(self._replacement_option_issues())
        return self.validation_with_source_issues(issues)

    def _output_issues(self) -> tuple[TaskIssue, ...]:
        if self.output_dir is None:
            return (
                TaskIssue(
                    code="REPLACE_RECOVERY_OUTPUT_REQUIRED",
                    message="Choose where replacement recovery sheets will be saved.",
                    section="output",
                ),
            )
        try:
            require_replacement_recovery_output_available(self.output_dir)
        except ValueError as exc:
            return (
                TaskIssue(
                    code="REPLACE_RECOVERY_OUTPUT_EXISTS",
                    message=str(exc),
                    section="output",
                ),
            )
        return ()

    def _output_section(self) -> TaskSection:
        issues = self._output_issues()
        return TaskSection(
            key="output",
            title="Save replacement sheets to",
            status="missing" if self.output_dir is None else "blocked" if issues else "ready",
            summary=display_path(self.output_dir)
            if self.output_dir
            else "No output folder selected.",
            detail=issues[0].message if issues else None,
            action_label="Choose folder...",
        )

    def _replacement_option_issues(self) -> list[TaskIssue]:
        issues: list[TaskIssue] = []
        if (
            self.signing_key_recovery_threshold is not None
            or self.signing_key_recovery_count is not None
        ) and (
            self.signing_key_recovery_threshold is None or self.signing_key_recovery_count is None
        ):
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_SIGNING_KEY_QUORUM_REQUIRED",
                    message="Set both required and total key-sheet counts.",
                    section="signature",
                )
            )
        if not self.create_passphrase_recovery and not self._creates_signing_key_recovery():
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_DOCUMENT_TYPE_REQUIRED",
                    message="Choose at least one replacement recovery sheet type.",
                    section="recovery",
                )
            )
        if self.passphrase_replacement_count is not None and not self.create_passphrase_recovery:
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_PASSPHRASE_REPLACEMENT_DISABLED",
                    message="Choose passphrase recovery before setting a replacement count.",
                    section="recovery",
                )
            )
        if self.passphrase_replacement_count is not None and not (
            self.recovery_documents or self.recovery_payload_files
        ):
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_PASSPHRASE_REPLACEMENT_INPUT_REQUIRED",
                    message="Load the existing recovery sheets before replacing them.",
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
                    message="Load existing signing-key payloads before replacing key sheets.",
                    section="signature",
                )
            )
        return issues

    def source_assessment_request(self) -> SourceAssessmentRequest | None:
        return self.content_source_request()

    def preview(self) -> TaskPreview:
        items = [
            PreviewItem(label="Existing backup", detail=self._source_summary()),
            PreviewItem(label="Unlock", detail=unlock_input_summary(self)),
            destination_preview(self.output_dir),
            unchanged_backup_preview(),
        ]
        if self.create_passphrase_recovery:
            if self.passphrase_replacement_count is not None:
                items.append(
                    PreviewItem(
                        label="Passphrase replacement sheets",
                        detail=format_count(self.passphrase_replacement_count, "sheet"),
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
                    label="Signing-key sheets",
                    detail=self._signing_key_recovery_summary(),
                )
            )
        if self.signing_key_recovery_payload_files:
            items.append(
                PreviewItem(
                    label="Existing key payloads",
                    detail=format_count(len(self.signing_key_recovery_payload_files), "file"),
                )
            )
        warnings: list[TaskIssue] = []
        warnings.extend(self._freshness_warnings())
        warnings.extend(self._recovery_warnings())
        if not self._creates_signing_key_recovery():
            warnings.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_SIGNING_KEY_RECOVERY_OFF",
                    message=SIGNING_KEY_RECOVERY_OFF_WARNING,
                    severity="warning",
                    section="signature",
                )
            )
        return TaskPreview(
            title="Replacement recovery sheets to create",
            items=tuple(items),
            warnings=tuple(warnings),
        )

    def execution_plan(self) -> TaskExecutionPlan:
        outputs = (self.output_dir,) if self.output_dir is not None else ()
        return TaskExecutionPlan(
            summary=(
                f"Create replacement recovery sheets in {self.output_dir or 'missing output'}"
            ),
            read_paths=self._read_paths(),
            output_paths=outputs,
            writes_files=True,
            safety_notes=(
                "Ethernity will create a new folder and write the replacement PDFs inside it. "
                "The selected output path must not already exist.",
                "Existing backup files stay unchanged.",
            ),
            trust_notes=(f"Scan version: {self._freshness_summary()}",),
            recovery_notes=(
                f"Passphrase recovery: {self.passphrase_recovery_summary()}",
                f"Signing-key recovery: {self._signing_key_section_summary()}",
                "The new recovery sheets unlock the original backup and any intact version "
                "of its update chain.",
                "Test the new recovery sheets before retiring old sheets. Existing sheets "
                "remain valid while the credentials stay unchanged.",
            ),
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        validation.require_ready("Replacement recovery sheets are not ready.")

        result = execute_replacement_recovery(self.to_replacement_recovery_request())
        output_paths = (
            *result.shard_paths,
            *result.signing_key_shard_paths,
        )
        return TaskExecutionResult(
            status="succeeded",
            message="Replacement recovery sheets created.",
            output_paths=output_paths,
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def to_replacement_recovery_request(self) -> ReplacementRecoveryRequest:
        return ReplacementRecoveryRequest(
            config_path=self.config_path,
            paper_size=self.paper_size,
            design=self.design,
            recovery_text_file=self.external_recovery_text_file,
            payloads_file=self.payloads_file,
            frames=tuple(recovery_text_frames(self.recovery_text, quiet=True) or ()),
            input_label="Pasted recovery text" if self.recovery_text else None,
            input_detail=recovery_text_summary(self.recovery_text) if self.recovery_text else None,
            scan_paths=tuple(self.source_paths),
            passphrase=self.passphrase,
            shard_scan_paths=tuple(self.recovery_documents),
            shard_payload_files=tuple(self.recovery_payload_files),
            signing_key_shard_payload_files=tuple(self.signing_key_recovery_payload_files),
            expected_head_doc_hash=self.expected_head_doc_hash,
            allow_stale_head=self.allow_stale_head,
            output_dir=self.output_dir,
            shard_threshold=self.recovery_threshold,
            shard_count=self.recovery_document_count,
            signing_key_shard_threshold=self.signing_key_recovery_threshold,
            signing_key_shard_count=self.signing_key_recovery_count,
            passphrase_replacement_count=self.passphrase_replacement_count,
            signing_key_replacement_count=self.signing_key_replacement_count,
            create_passphrase_shards=self.create_passphrase_recovery,
            create_signing_key_shards=self._creates_signing_key_recovery(),
            quiet=True,
        )

    def _read_paths(self) -> tuple[Path, ...]:
        return self.recovery_read_paths(
            content_paths=(),
            trailing_paths=(
                *self.signing_key_recovery_payload_files,
                self.recovery_text_file,
                self.payloads_file,
            ),
        )

    def _creates_signing_key_recovery(self) -> bool:
        return bool(
            self.create_signing_key_recovery
            or self.signing_key_replacement_count is not None
            or self.signing_key_recovery_threshold is not None
            or self.signing_key_recovery_count is not None
        )

    def signing_key_recovery_quorum(self) -> tuple[int, int]:
        return (
            self.signing_key_recovery_threshold or self.recovery_threshold,
            self.signing_key_recovery_count or self.recovery_document_count,
        )

    def _signing_key_recovery_summary(self) -> str:
        if self.signing_key_replacement_count is not None:
            return format_count(self.signing_key_replacement_count, "replacement sheet")
        threshold, count = self.signing_key_recovery_quorum()
        return f"{count} key sheets; any {threshold} can recover the key"

    def _signing_key_section_summary(self) -> str:
        if not self._creates_signing_key_recovery():
            return "No separate key sheets"
        return self._signing_key_recovery_summary()

    def passphrase_recovery_summary(self) -> str:
        if not self.create_passphrase_recovery:
            return "No passphrase recovery sheets"
        if self.passphrase_replacement_count is not None:
            return f"Replace {format_count(self.passphrase_replacement_count, 'sheet')}"
        return (
            f"{format_count(self.recovery_document_count, 'sheet')}; "
            f"any {self.recovery_threshold} can restore"
        )

    def _recovery_status(self) -> TaskSectionStatus:
        if self.recovery_threshold == 2 and self.recovery_document_count == 3:
            return "ready"
        return "warning"

    def _recovery_warnings(self) -> tuple[TaskIssue, ...]:
        if self.recovery_threshold == 2 and self.recovery_document_count == 3:
            return ()
        return (
            TaskIssue(
                code="REPLACE_RECOVERY_CUSTOM_QUORUM",
                message="A custom quorum changes how many sheets you need to restore.",
                severity="warning",
                section="recovery",
            ),
        )

    def signing_key_recovery_payloads_summary(self) -> str:
        if not self.signing_key_recovery_payload_files:
            return "No key payloads loaded"
        return format_count(len(self.signing_key_recovery_payload_files), "key payload file")

    def _source_summary(self) -> str:
        request = self.source_assessment_request()
        if request is not None and request.source_kind == "recovery_inputs":
            return request.source_summary
        sources = len(self.source_paths)
        if sources:
            return format_count(sources, "scanned page")
        if self.recovery_text:
            return recovery_text_summary(self.recovery_text)
        if self.recovery_text_file is not None:
            return display_path(self.recovery_text_file)
        if self.payloads_file is not None:
            return display_path(self.payloads_file)
        return "Choose backup documents."

    def _freshness_summary(self) -> str:
        if not self.source_paths:
            return "Recovery text or backup payload"
        if self.expected_head_doc_hash is not None:
            return "Latest fingerprint provided"
        if self.allow_stale_head:
            return "Latest loaded version accepted"
        return "Confirm the scans contain the latest version"

    def _freshness_warnings(self) -> tuple[TaskIssue, ...]:
        if not self.source_paths or not self.allow_stale_head:
            return ()
        return (
            TaskIssue(
                code="REPLACE_RECOVERY_STALE_SOURCE_ACCEPTED",
                message="These scans may not contain the latest backup version.",
                severity="warning",
                section="freshness",
            ),
        )
