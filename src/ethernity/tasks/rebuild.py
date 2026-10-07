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

from pydantic import ConfigDict, model_validator

from ethernity.page_sizes import DEFAULT_PAPER_SIZE_NAME
from ethernity.tasks.common_sections import (
    advanced_section,
    backup_destination_section,
    confirmed_source_section,
    destination_preview,
    qr_density_warnings,
    stale_source_warnings,
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
    TaskResultDetail,
    TaskSection,
    TaskValidation,
)
from ethernity.tasks.output_checks import (
    BACKUP_OUTPUT_NOTE,
    backup_destination_issues,
    generated_output_paths,
    generated_recovery_check_paths,
    planned_backup_output,
)
from ethernity.tasks.page_layout import (
    ValidatedPaperSizeName,
    validate_backup_print_options,
)
from ethernity.tasks.presentation.recovery import signature_source_summary, unlock_input_summary
from ethernity.tasks.recovery_inputs import has_unlock_inputs
from ethernity.tasks.source_assessment import (
    RecoveryTaskState,
    SourceAssessmentRequest,
    folder_or_scans_source_request,
)
from ethernity.workflows.execution import execute_rebuild
from ethernity.workflows.shared.requests import RebuildRequest


class RebuildTaskState(RecoveryTaskState):
    """Beginner-facing state for rebuilding a backup from its latest recoverable state."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    backup_folder: Path | None = None
    output_dir: Path | None = None
    allow_stale_head: bool = False
    paper_size: ValidatedPaperSizeName = DEFAULT_PAPER_SIZE_NAME
    design: str = "sentinel"
    qr_chunk_size: int | None = None

    @model_validator(mode="after")
    def _validate_qr_chunk_size(self) -> RebuildTaskState:
        validate_backup_print_options(self.design, self.paper_size, self.qr_chunk_size)
        return self

    def sections(self) -> tuple[TaskSection, ...]:
        return (
            TaskSection(
                key="source",
                title="Existing backup",
                status="ready" if self._has_exactly_one_source() else "missing",
                summary=self._source_summary(),
                action_label="Choose backup folder...",
            ),
            unlock_section(self, "Unlock backup"),
            confirmed_source_section(
                self.expected_head_doc_hash, self.allow_stale_head, self._freshness_summary()
            ),
            backup_destination_section(self.output_dir, "Save rebuilt backup to", required=True),
            advanced_section(
                self._advanced_issues(), self._advanced_warnings(), self._advanced_summary()
            ),
        )

    def validate_task(self) -> TaskValidation:
        issues: list[TaskIssue] = []
        if not self._has_exactly_one_source():
            issues.append(
                TaskIssue(
                    code="REBUILD_SOURCE_REQUIRED",
                    message="Choose a backup folder or scanned pages.",
                    section="source",
                )
            )
        if not has_unlock_inputs(self):
            issues.append(
                TaskIssue(
                    code="REBUILD_UNLOCK_REQUIRED",
                    message="Choose a passphrase, recovery sheets, or recovery payload files.",
                    section="unlock",
                )
            )
        if (
            self._has_exactly_one_source()
            and self.expected_head_doc_hash is None
            and not self.allow_stale_head
        ):
            issues.append(
                TaskIssue(
                    code="REBUILD_HEAD_TRUST_REQUIRED",
                    message=(
                        "Enter the expected latest fingerprint, or accept the newest loaded "
                        "version."
                    ),
                    section="freshness",
                )
            )
        if self.output_dir is None:
            issues.append(
                TaskIssue(
                    code="REBUILD_OUTPUT_REQUIRED",
                    message="Choose where rebuilt backup documents will be saved.",
                    section="output",
                )
            )
        issues.extend(self._advanced_issues())
        issues.extend(backup_destination_issues(self.output_dir))
        return self.validation_with_source_issues(issues)

    def source_assessment_request(self) -> SourceAssessmentRequest | None:
        return folder_or_scans_source_request(
            issue_section="source",
            backup_folder=self.backup_folder,
            scan_paths=self.source_paths,
            config_path=self.config_path,
            auth_text_file=self.auth_text_file,
            auth_payloads_file=self.auth_payloads_file,
        )

    def preview(self) -> TaskPreview:
        warnings = (
            *self._freshness_warnings(),
            *self._advanced_warnings(),
        )
        items = [
            PreviewItem(label="Existing backup", detail=self._source_summary()),
            PreviewItem(label="Unlock", detail=unlock_input_summary(self)),
            PreviewItem(label="Backup version", detail=self._freshness_summary()),
            PreviewItem(
                label="Verification source",
                detail=signature_source_summary(self.auth_text_file, self.auth_payloads_file),
            ),
            destination_preview(
                planned_backup_output(self.output_dir) if self.output_dir is not None else None
            ),
            unchanged_backup_preview(),
            PreviewItem(
                label="Credentials",
                detail="Same passphrase; embedded signing key preserved",
            ),
            PreviewItem(
                label="New documents",
                detail="Backup, recovery guide, and recovery sheets",
            ),
        ]
        if self.qr_chunk_size is not None:
            items.append(PreviewItem(label="QR density", detail=f"{self.qr_chunk_size} bytes"))
        return TaskPreview(
            title="Rebuilt backup to create",
            items=tuple(items),
            warnings=warnings,
        )

    def execution_plan(self) -> TaskExecutionPlan:
        output = planned_backup_output(self.output_dir) if self.output_dir is not None else None
        outputs = (output,) if output is not None else ()
        return TaskExecutionPlan(
            summary=f"Rebuild backup into {display_path(output) if output else 'missing output'}",
            read_paths=self._read_paths(),
            output_paths=outputs,
            writes_files=True,
            safety_notes=(BACKUP_OUTPUT_NOTE,),
            trust_notes=(
                f"Backup version: {self._freshness_summary()}",
                "Latest means the newest valid version in the documents you loaded.",
                "Verification source: "
                f"{signature_source_summary(self.auth_text_file, self.auth_payloads_file)}",
            ),
            recovery_notes=(
                f"Unlock: {unlock_input_summary(self)}",
                "The rebuilt backup gets a new set of recovery sheets.",
                "The passphrase stays the same; an embedded signing key is preserved.",
                "Use Create backup when you need a new passphrase or signing key.",
            ),
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        validation.require_ready("Rebuild is not ready.")

        result = execute_rebuild(self.to_rebuild_request())
        output_paths = generated_output_paths(result)
        signing_note = "An embedded signing key is preserved."
        if result.signing_key_preserved is True:
            signing_note = "The signing key is preserved."
        elif result.signing_key_preserved is False:
            signing_note = "The sealed backup has a new signing key."
        return TaskExecutionResult(
            status="succeeded",
            message="Rebuilt backup documents created.",
            output_paths=output_paths,
            recovery_check_paths=generated_recovery_check_paths(result),
            details=(
                (
                    TaskResultDetail(
                        key="doc_hash", label="Full fingerprint", value=result.doc_hash.hex()
                    ),
                )
                if result.doc_hash is not None
                else ()
            ),
            next_steps=(
                "Verify the rebuilt backup and new recovery sheets before retiring old documents.",
                f"The rebuilt backup uses the same passphrase. {signing_note}",
                "Use Create backup when you need a new passphrase or signing key.",
            ),
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def to_rebuild_request(self) -> RebuildRequest:
        return RebuildRequest(
            config_path=self.config_path,
            backup_folder=self.backup_folder,
            scan_paths=tuple(self.source_paths),
            output_dir=self.output_dir,
            **self.unlock_request_fields(),
            expected_head_doc_hash=self.expected_head_doc_hash,
            allow_stale_head=self.allow_stale_head,
            paper_size=self.paper_size,
            design=self.design,
            qr_chunk_size=self.qr_chunk_size,
            quiet=True,
        )

    def _has_exactly_one_source(self) -> bool:
        return (self.backup_folder is not None) != bool(self.source_paths)

    def _read_paths(self) -> tuple[Path, ...]:
        paths = self.recovery_read_paths(
            trailing_paths=(self.auth_text_file, self.auth_payloads_file)
        )
        return (self.backup_folder, *paths) if self.backup_folder is not None else paths

    def _source_summary(self) -> str:
        if self.backup_folder is not None and self.source_paths:
            return "Choose a folder or scans, not both"
        if self.backup_folder is not None:
            return display_path(self.backup_folder)
        if self.source_paths:
            return format_count(len(self.source_paths), "scanned page")
        return "Choose a backup folder or scanned pages."

    def _advanced_summary(self) -> str:
        has_source = self.backup_folder is not None or bool(self.source_paths)
        parts = [
            signature_source_summary(self.auth_text_file, self.auth_payloads_file)
            if has_source or self.auth_text_file is not None or self.auth_payloads_file is not None
            else "Verification available after loading a backup"
        ]
        if self.qr_chunk_size is not None:
            parts.append(f"QR {self.qr_chunk_size} bytes")
        else:
            parts.append("QR from settings")
        return ", ".join(parts)

    def _advanced_warnings(self) -> tuple[TaskIssue, ...]:
        return qr_density_warnings(self.qr_chunk_size, "REBUILD_CUSTOM_QR_DENSITY")

    def _advanced_issues(self) -> tuple[TaskIssue, ...]:
        if self.auth_text_file is not None and self.auth_payloads_file is not None:
            return (
                TaskIssue(
                    code="REBUILD_SIGNATURE_SOURCE_CONFLICT",
                    message="Choose either signature text or a signature payload, not both.",
                    section="advanced",
                ),
            )
        return ()

    def _freshness_summary(self) -> str:
        if self.expected_head_doc_hash is not None:
            return "Latest fingerprint provided"
        if self.allow_stale_head:
            return "Latest loaded version accepted"
        return "Confirm the loaded documents contain the latest version"

    def _freshness_warnings(self) -> tuple[TaskIssue, ...]:
        return stale_source_warnings(self.allow_stale_head, "REBUILD_STALE_SOURCE_ACCEPTED")
