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

from pydantic import ConfigDict, Field, field_validator, model_validator

from ethernity.cli.features.mint.workflow import execute_mint
from ethernity.cli.shared.io.frames import frames_from_fallback_text
from ethernity.cli.shared.types import MintArgs
from ethernity.encoding.framing import Frame
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
from ethernity.tasks.output_checks import (
    existing_output_summary,
    existing_output_warning,
    selected_output_status,
)
from ethernity.tasks.quorum import validate_optional_shard_count, validate_required_shard_count
from ethernity.tasks.source_assessment import (
    SourceAssessableTaskState,
    SourceAssessmentRequest,
    recovery_source_request,
)

SIGNING_KEY_RECOVERY_OFF_WARNING = (
    "No separate signing-key recovery sheets will be created. The replacement documents "
    "remain signed."
)


class ReplaceRecoveryDocsTaskState(SourceAssessableTaskState):
    """Beginner-facing state for creating replacement recovery sheets."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    source_paths: list[Path] = Field(default_factory=list)
    recovery_text: str | None = None
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
        source_error = self._recovery_text_error()
        return (
            TaskSection(
                key="source",
                title="Existing backup",
                status=(
                    "blocked"
                    if source_error is not None
                    else "ready"
                    if self._has_source()
                    else "missing"
                ),
                summary=(
                    "Pasted recovery text is not valid recovery text."
                    if source_error is not None
                    else self._source_summary()
                ),
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
                title="Scan version",
                status=self._freshness_status(),
                summary=self._freshness_summary(),
                action_label="Confirm source",
            ),
            TaskSection(
                key="output",
                title="Save replacement sheets to",
                status=selected_output_status(self.output_dir),
                summary=existing_output_summary(
                    self.output_dir,
                    target="output_folder",
                    missing_summary="No output folder selected.",
                ),
                action_label="Choose output folder...",
            ),
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
        if not self._has_source():
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_SOURCE_REQUIRED",
                    message="Choose backup material.",
                    section="source",
                )
            )
        if self.recovery_text and self._recovery_text_error() is not None:
            issues.append(
                TaskIssue(
                    code="REPLACE_RECOVERY_TEXT_INVALID",
                    message="Pasted recovery text is not valid recovery text.",
                    section="source",
                )
            )
        if not self._has_unlock():
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
                    message="Set both required and total key-sheet counts.",
                    section="signature",
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
        return TaskValidation(
            sections=self.sections(),
            issues=self.source_assessment_issues(issues),
        )

    def source_assessment_request(self) -> SourceAssessmentRequest | None:
        return recovery_source_request(
            issue_section="source",
            scan_paths=self.source_paths,
            recovery_text=self.recovery_text,
            recovery_text_file=self.recovery_text_file,
            payloads_file=self.payloads_file,
            config_path=self.config_path,
        )

    def preview(self) -> TaskPreview:
        items = [
            PreviewItem(label="Existing backup", detail=self._source_summary()),
            PreviewItem(label="Unlock", detail=self._unlock_summary()),
            PreviewItem(
                label="Destination",
                detail=(
                    display_path(self.output_dir) if self.output_dir is not None else "Not selected"
                ),
            ),
            PreviewItem(
                label="Existing backup files",
                detail="Left unchanged",
            ),
        ]
        if self.mint_passphrase_recovery:
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
        warnings.extend(
            existing_output_warning(
                self.output_dir,
                code="REPLACE_RECOVERY_OUTPUT_EXISTS",
                target="output_folder",
            )
        )
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
                "Ethernity will create the folder if needed and write the replacement PDFs "
                "inside it.",
                "Existing backup files stay unchanged.",
            ),
            trust_notes=(f"Scan version: {self._freshness_summary()}",),
            recovery_notes=(
                f"Passphrase recovery: {self.passphrase_recovery_summary()}",
                f"Signing-key recovery: {self._signing_key_section_summary()}",
                "Existing recovery sheets are not modified; retire old sheets only after the new "
                "set is printed and stored.",
            ),
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
            fallback_file=(
                str(self.recovery_text_file)
                if self.recovery_text_file is not None and not self.recovery_text
                else None
            ),
            payloads_file=str(self.payloads_file) if self.payloads_file else None,
            frames=self._recovery_text_frames(quiet=quiet),
            input_label="Pasted recovery text" if self.recovery_text else None,
            input_detail=self._recovery_text_summary() if self.recovery_text else None,
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
        return bool(
            self.source_paths or self.recovery_text or self.recovery_text_file or self.payloads_file
        )

    def _has_unlock(self) -> bool:
        return bool(self.passphrase or self.recovery_documents or self.recovery_payload_files)

    def _read_paths(self) -> tuple[Path, ...]:
        paths = [
            *self.source_paths,
            *self.recovery_documents,
            *self.recovery_payload_files,
            *self.signing_key_recovery_payload_files,
        ]
        for path in (self.recovery_text_file, self.payloads_file):
            if path is not None:
                paths.append(path)
        return tuple(paths)

    def _creates_signing_key_recovery(self) -> bool:
        return bool(
            self.mint_signing_key_recovery
            or self.signing_key_replacement_count is not None
            or self.signing_key_recovery_threshold is not None
            or self.signing_key_recovery_count is not None
        )

    def _signing_key_recovery_summary(self) -> str:
        if self.signing_key_replacement_count is not None:
            return format_count(self.signing_key_replacement_count, "replacement sheet")
        threshold = self.signing_key_recovery_threshold or self.recovery_threshold
        count = self.signing_key_recovery_count or self.recovery_document_count
        return f"{count} key sheets; any {threshold} can recover the key"

    def _signing_key_section_summary(self) -> str:
        if not self._creates_signing_key_recovery():
            return "No separate key sheets"
        return self._signing_key_recovery_summary()

    def passphrase_recovery_summary(self) -> str:
        if not self.mint_passphrase_recovery:
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
        sources = len(self.source_paths)
        if sources:
            return format_count(sources, "scanned page")
        if self.recovery_text:
            return self._recovery_text_summary()
        if self.recovery_text_file is not None:
            return display_path(self.recovery_text_file)
        if self.payloads_file is not None:
            return display_path(self.payloads_file)
        return "Choose backup material."

    def _unlock_summary(self) -> str:
        if self.passphrase:
            return "Passphrase"
        if self.recovery_documents:
            return format_count(len(self.recovery_documents), "recovery sheet")
        if self.recovery_payload_files:
            return format_count(len(self.recovery_payload_files), "recovery payload file")
        return "Choose an unlock method"

    def _freshness_status(self) -> TaskSectionStatus:
        if not self.source_paths:
            return "ready"
        if self.expected_head_doc_hash is not None:
            return "ready"
        if self.allow_stale_head:
            return "warning"
        return "missing"

    def _freshness_summary(self) -> str:
        if not self.source_paths:
            return "Recovery text or backup payload"
        if self.expected_head_doc_hash is not None:
            return "Latest fingerprint provided"
        if self.allow_stale_head:
            return "Latest loaded version accepted"
        return "Confirm the scans contain the latest version"

    def _recovery_text_summary(self) -> str:
        if not self.recovery_text:
            return "Pasted recovery text"
        line_count = len([line for line in self.recovery_text.splitlines() if line.strip()])
        if line_count == 1:
            return "Pasted recovery text: 1 line"
        return f"Pasted recovery text: {line_count} lines"

    def _recovery_text_frames(self, *, quiet: bool) -> list[Frame] | None:
        if not self.recovery_text:
            return None
        return frames_from_fallback_text(self.recovery_text, quiet=quiet)

    def _recovery_text_error(self) -> str | None:
        try:
            self._recovery_text_frames(quiet=True)
        except ValueError as exc:
            return str(exc)
        return None

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
