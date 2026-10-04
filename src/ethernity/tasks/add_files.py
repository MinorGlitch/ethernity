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

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ConfigDict, Field, PrivateAttr, model_validator

from ethernity.config import load_cli_defaults, resolve_config_snapshot_path
from ethernity.tasks.backup_inputs import has_selected_inputs
from ethernity.tasks.file_summary import (
    display_path,
    selected_paths_summary,
)
from ethernity.tasks.models import (
    PreviewItem,
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
from ethernity.tasks.page_layout import (
    BACKUP_RENDER_DOC_TYPES,
    ValidatedPaperSizeName,
    require_workflow_page_size,
)
from ethernity.tasks.presentation.recovery import (
    signature_source_summary,
    unlock_input_summary,
)
from ethernity.tasks.recovery_inputs import (
    has_recovery_source,
    has_unlock_inputs,
    recovery_text_error,
    recovery_text_frames,
)
from ethernity.tasks.source_assessment import (
    SourceAssessableTaskState,
    SourceAssessmentRequest,
    recovery_source_request,
)
from ethernity.workflows.add_files.request import (
    AddFilesRequest,
    validate_recovery_sheet_counts,
)
from ethernity.workflows.add_files.service import (
    AddFilesAssessment,
    AddFilesIssue,
    assess_add_files,
    execute_add_files,
)
from ethernity.workflows.shared import api_codes


@dataclass(frozen=True)
class _AssessmentCache:
    key: bytes
    assessment: AddFilesAssessment | None = None
    issue: TaskIssue | None = None


class AddFilesTaskState(SourceAssessableTaskState):
    """Beginner-facing state for adding files to an existing backup."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    source_paths: list[Path] = Field(default_factory=list)
    recovery_text: str | None = None
    recovery_text_file: Path | None = None
    payloads_file: Path | None = None
    auth_text_file: Path | None = None
    auth_payloads_file: Path | None = None
    output_dir: Path | None = None
    config_path: Path | None = None
    input_paths: list[Path] = Field(default_factory=list)
    input_dirs: list[Path] = Field(default_factory=list)
    base_dir: Path | None = None
    passphrase: str | None = None
    recovery_documents: list[Path] = Field(default_factory=list)
    recovery_payload_files: list[Path] = Field(default_factory=list)
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    paper_size: ValidatedPaperSizeName | None = None
    design: str | None = None
    qr_chunk_size: int | None = None
    create_recovery_sheets: bool = False
    recovery_threshold: int = 2
    recovery_sheet_count: int = 3

    _assessment_cache: _AssessmentCache | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _validate_advanced_options(self) -> AddFilesTaskState:
        if self.design is not None and self.paper_size is not None:
            require_workflow_page_size(
                self.design,
                self.paper_size,
                candidate_doc_types=BACKUP_RENDER_DOC_TYPES,
            )
        if self.qr_chunk_size is not None and self.qr_chunk_size < 1:
            raise ValueError("QR chunk size must be positive")
        validate_recovery_sheet_counts(self.recovery_threshold, self.recovery_sheet_count)
        return self

    def sections(self) -> tuple[TaskSection, ...]:
        sections = (
            TaskSection(
                key="source",
                title="Current backup",
                status=self._source_status(),
                summary=self._source_summary(),
                action_label="Choose backup source...",
            ),
            TaskSection(
                key="files",
                title="Files to add or replace",
                status=(
                    "ready" if has_selected_inputs(self.input_paths, self.input_dirs) else "missing"
                ),
                summary=self._input_summary(),
                action_label="Choose files...",
            ),
            TaskSection(
                key="unlock",
                title="Unlock backup",
                status="ready" if has_unlock_inputs(self) else "missing",
                summary=unlock_input_summary(self),
                action_label="Set unlock method...",
            ),
            TaskSection(
                key="freshness",
                title="Backup version",
                status=(
                    "ready"
                    if self.expected_head_doc_hash is not None or self.allow_stale_head
                    else "missing"
                ),
                summary=self._freshness_summary(),
                action_label="Confirm source",
            ),
            TaskSection(
                key="output",
                title="Save update to",
                status="ready" if self.output_dir is not None else "missing",
                summary=display_path(self.output_dir)
                if self.output_dir is not None
                else "Choose an output folder.",
                action_label="Choose output folder...",
            ),
            TaskSection(
                key="advanced",
                title="Advanced",
                status=optional_section_status(
                    (),
                    self._advanced_warnings(),
                ),
                summary=self._advanced_summary(),
                action_label="Review options",
            ),
        )
        cache = self._current_assessment_cache()
        if cache is None or cache.issue is None:
            return sections
        issue_section = cache.issue.section or "source"
        return tuple(
            section.model_copy(
                update={
                    "status": "blocked",
                    "detail": cache.issue.message,
                }
            )
            if section.key == issue_section
            else section
            for section in sections
        )

    def validate_task(self) -> TaskValidation:
        issues = list(self._basic_issues())
        cache = self._current_assessment_cache()
        if not issues and cache is not None and cache.issue is not None:
            issues.append(cache.issue)
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
            auth_text_file=self.auth_text_file,
            auth_payloads_file=self.auth_payloads_file,
            config_path=self.config_path,
        )

    def prepare_review(self, *, force: bool = False) -> None:
        """Prime one execution-grade assessment for preview, review, and execution."""

        if not force and self._current_assessment_cache() is not None:
            return
        basic_issues = self._basic_issues()
        if basic_issues:
            self._assessment_cache = None
            return
        key = self._assessment_key()
        assessment = assess_add_files(self.to_add_files_request(quiet=True))
        if assessment.issues:
            issue = assessment.issues[0]
            self._assessment_cache = _AssessmentCache(
                key=key,
                issue=TaskIssue(
                    code=issue.code,
                    message=issue.message,
                    section=_assessment_issue_section(issue),
                ),
            )
            return
        self._assessment_cache = _AssessmentCache(key=key, assessment=assessment)

    def _basic_issues(self) -> tuple[TaskIssue, ...]:
        issues: list[TaskIssue] = []
        if not has_recovery_source(self):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SOURCE_REQUIRED",
                    message="Choose backup documents, recovery text, or exported payloads.",
                    section="source",
                )
            )
        if self.recovery_text and recovery_text_error(self.recovery_text) is not None:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_RECOVERY_TEXT_INVALID",
                    message="Pasted recovery text is not valid recovery text.",
                    section="source",
                )
            )
        if self.auth_text_file is not None and self.auth_payloads_file is not None:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SIGNATURE_SOURCE_CONFLICT",
                    message="Choose either signature text or a signature payload, not both.",
                    section="advanced",
                )
            )
        if not has_selected_inputs(self.input_paths, self.input_dirs):
            issues.append(
                TaskIssue(
                    code=api_codes.ADD_FILES_INPUT_REQUIRED,
                    message="Choose at least one file or folder to add.",
                    section="files",
                )
            )
        if not has_unlock_inputs(self):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_UNLOCK_REQUIRED",
                    message="Choose a passphrase, recovery sheets, or recovery payload files.",
                    section="unlock",
                )
            )
        if (
            has_recovery_source(self)
            and self.expected_head_doc_hash is None
            and not self.allow_stale_head
        ):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_HEAD_TRUST_REQUIRED",
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
                    code="ADD_FILES_OUTPUT_REQUIRED",
                    message="Choose where the new update documents will be saved.",
                    section="output",
                )
            )
        return tuple(issues)

    def preview(self) -> TaskPreview:
        cache = self._current_assessment_cache()
        assessment = cache.assessment if cache is not None else None
        assessed = assessment.assessed if assessment is not None else None
        warnings = (*self._freshness_warnings(), *self._advanced_warnings())
        items = [
            PreviewItem(label="Backup source", detail=self._source_summary()),
            PreviewItem(label="Files", detail=self._input_summary()),
            PreviewItem(label="Unlock", detail=unlock_input_summary(self)),
            PreviewItem(
                label="Destination",
                detail=display_path(self.output_dir)
                if self.output_dir is not None
                else "Not selected",
            ),
            PreviewItem(label="Backup version", detail=self._freshness_summary()),
            PreviewItem(
                label="Verification source",
                detail=signature_source_summary(self.auth_text_file, self.auth_payloads_file),
            ),
            PreviewItem(label="Recovery sheets", detail=self.recovery_sheet_summary()),
            PreviewItem(
                label="New documents",
                detail="Backup update and recovery guide",
            ),
        ]
        if assessed is not None:
            assert assessment is not None
            prepared = assessed.prepared
            encrypted = assessed.encrypted
            stats = encrypted.built.stats
            items.extend(
                (
                    PreviewItem(label="Next update", detail=f"{prepared.next_index:02d}"),
                    PreviewItem(
                        label="Recovery chain",
                        detail=self._chain_recovery_guidance(prepared.next_index),
                    ),
                    PreviewItem(
                        label="File changes",
                        detail=(
                            f"{len(prepared.changed_paths)} changed, "
                            f"{len(prepared.new_paths)} new, "
                            f"{len(prepared.unchanged_paths)} unchanged"
                        ),
                    ),
                    PreviewItem(
                        label="Chunk reuse",
                        detail=f"{stats.new_chunks} new, {stats.reused_chunks} reused",
                    ),
                    PreviewItem(
                        label="Parent fingerprint",
                        detail=prepared.parent_doc_hash.hex(),
                    ),
                    PreviewItem(label="New fingerprint", detail=encrypted.doc_hash.hex()),
                    PreviewItem(
                        label="Update folder",
                        detail=str(self.output_dir),
                    ),
                    PreviewItem(
                        label="Print layout",
                        detail=(
                            f"{assessed.output_settings.config.paper_size}, "
                            f"{assessed.output_settings.config.design_name}, "
                            f"{assessed.output_settings.qr_chunk_size} bytes per QR"
                        ),
                    ),
                )
            )
            recovery_output = assessment.recovery_sheet_output_dir
            if recovery_output is not None:
                items.append(
                    PreviewItem(
                        label="Recovery sheet folder",
                        detail=str(recovery_output),
                    )
                )
        if self.qr_chunk_size is not None:
            items.append(PreviewItem(label="QR density", detail=f"{self.qr_chunk_size} bytes"))
        return TaskPreview(
            title="Backup update to create",
            items=tuple(items),
            warnings=warnings,
        )

    def execution_plan(self) -> TaskExecutionPlan:
        output_folder = self.output_dir
        cache = self._current_assessment_cache()
        assessment = cache.assessment if cache is not None else None
        assessed = assessment.assessed if assessment is not None else None
        recovery_output = self._recovery_sheet_output_path(assessment)
        outputs = tuple(path for path in (output_folder, recovery_output) if path is not None)
        summary = (
            f"Create backup update {assessed.prepared.next_index:02d} in {output_folder}"
            if assessed is not None
            else f"Add files to {output_folder or 'missing output folder'}"
        )
        return TaskExecutionPlan(
            summary=summary,
            read_paths=self._read_paths(),
            output_paths=outputs,
            writes_files=True,
            safety_notes=(
                "New update documents are written to the selected output folder.",
                "Matching paths are replaced. Other paths are not deleted or renamed.",
            ),
            trust_notes=(
                f"Backup version: {self._freshness_summary()}",
                "Latest means the newest valid version in the documents you loaded.",
            ),
            recovery_notes=(
                f"Unlock: {unlock_input_summary(self)}",
                self._chain_recovery_guidance(
                    assessed.prepared.next_index if assessed is not None else None
                ),
                self._recovery_plan_note(),
            ),
        )

    def execute(self) -> TaskExecutionResult:
        if self._current_assessment_cache() is None:
            self.prepare_review()
        validation = self.validate_task()
        if not validation.ready:
            first_issue = validation.issues[0] if validation.issues else None
            message = first_issue.message if first_issue is not None else "The update is not ready."
            raise ValueError(message)

        cache = self._current_assessment_cache()
        if cache is None or cache.assessment is None:
            raise ValueError("The update could not be prepared for review.")
        execution = execute_add_files(
            cache.assessment,
            config_path=str(self.config_path) if self.config_path is not None else None,
        )
        if not execution.ok or execution.executed is None:
            issue = execution.issues[0]
            raise ValueError(issue.message)
        executed = execution.executed
        result = executed.result
        output_paths = (
            result.qr_document_path,
            result.recovery_document_path,
        )
        prepared = executed.prepared
        encrypted = executed.publish.encrypted
        stats = encrypted.built.stats
        details = (
            TaskResultDetail(key="index", label="Update index", value=result.index),
            TaskResultDetail(key="doc_id", label="Document ID", value=result.doc_id.hex()),
            TaskResultDetail(
                key="doc_hash",
                label="New full fingerprint",
                value=result.doc_hash.hex(),
            ),
            TaskResultDetail(
                key="parent_head_index",
                label="Parent update index",
                value=result.parent_head_index,
            ),
            TaskResultDetail(
                key="parent_head_doc_hash",
                label="Parent full fingerprint",
                value=prepared.parent_doc_hash.hex(),
            ),
            TaskResultDetail(
                key="output_dir",
                label="Update output folder",
                value=str(result.final_dir),
            ),
            TaskResultDetail(
                key="changed_path_count",
                label="Changed paths",
                value=len(prepared.changed_paths),
            ),
            TaskResultDetail(
                key="new_path_count",
                label="New paths",
                value=len(prepared.new_paths),
            ),
            TaskResultDetail(
                key="unchanged_path_count",
                label="Unchanged selected paths",
                value=len(prepared.unchanged_paths),
            ),
            TaskResultDetail(
                key="file_bytes",
                label="Changed logical bytes",
                value=stats.file_bytes,
            ),
            TaskResultDetail(key="new_chunks", label="New chunks", value=stats.new_chunks),
            TaskResultDetail(
                key="reused_chunks",
                label="Reused chunks",
                value=stats.reused_chunks,
            ),
            TaskResultDetail(
                key="extension_plaintext_bytes",
                label="Update payload bytes",
                value=len(encrypted.plaintext),
            ),
            TaskResultDetail(
                key="extension_ciphertext_bytes",
                label="Encrypted update bytes",
                value=len(encrypted.ciphertext),
            ),
        )
        next_steps = (
            (
                "Keep the original backup, every update through "
                f"{result.index:02d}, and the recovery kit."
            ),
            "Use Rebuild when you want a new standalone backup instead of the full update chain.",
            "Save the new fingerprint as the expected latest version before the next update.",
        )
        recovery_sheets = execution.recovery_sheets
        if recovery_sheets.status == "failed":
            return TaskExecutionResult(
                status="partially_succeeded",
                message=(
                    f"Added files as backup update {result.index:02d}, but recovery sheets "
                    "were not created."
                ),
                output_paths=output_paths,
                recovery_check_paths=(result.qr_document_path,),
                details=(
                    *details,
                    TaskResultDetail(
                        key="recovery_sheets",
                        label="Recovery sheets",
                        value=f"Not created: {recovery_sheets.error}",
                    ),
                ),
                next_steps=(
                    (
                        "The update is already published. Do not run Add Files again; run "
                        "Replace Recovery Docs for the new fingerprint."
                    ),
                    *next_steps,
                ),
            )
        if recovery_sheets.status == "created":
            output_paths = (*output_paths, *recovery_sheets.paths)
            details = (
                *details,
                TaskResultDetail(
                    key="recovery_sheets",
                    label="Recovery sheets",
                    value=(
                        f"{self.recovery_sheet_count} created; "
                        f"{self.recovery_threshold} needed to restore"
                    ),
                ),
            )
            next_steps = (
                "Keep the new recovery sheets separate from the backup and from one another.",
                *next_steps,
            )
        return TaskExecutionResult(
            status="succeeded",
            message=f"Added files as backup update {result.index:02d}.",
            output_paths=output_paths,
            recovery_check_paths=(
                result.qr_document_path,
                *(recovery_sheets.paths if recovery_sheets.status == "created" else ()),
            ),
            details=details,
            next_steps=next_steps,
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def to_add_files_request(self, *, quiet: bool = False) -> AddFilesRequest:
        base_dir = self.base_dir
        if base_dir is None:
            defaults = load_cli_defaults(self.config_path).add_files
            base_dir = Path(defaults.base_dir) if defaults.base_dir is not None else None
        return AddFilesRequest(
            config_path=str(self.config_path) if self.config_path is not None else None,
            scan_paths=tuple(str(path) for path in self.source_paths),
            recovery_text_file=str(self.recovery_text_file)
            if self.recovery_text_file is not None
            else None,
            payloads_file=str(self.payloads_file) if self.payloads_file is not None else None,
            frames=tuple(recovery_text_frames(self.recovery_text, quiet=quiet) or ()),
            auth_text_file=str(self.auth_text_file) if self.auth_text_file is not None else None,
            auth_payloads_file=str(self.auth_payloads_file)
            if self.auth_payloads_file is not None
            else None,
            output_dir=str(self.output_dir) if self.output_dir is not None else None,
            input_paths=tuple(str(path) for path in self.input_paths),
            input_directories=tuple(str(path) for path in self.input_dirs),
            base_directory=str(base_dir) if base_dir is not None else None,
            passphrase=self.passphrase,
            shard_scan_paths=tuple(str(path) for path in self.recovery_documents),
            shard_payload_files=tuple(str(path) for path in self.recovery_payload_files),
            expected_head_doc_hash=self.expected_head_doc_hash,
            allow_stale_head=self.allow_stale_head,
            create_recovery_sheets=self.create_recovery_sheets,
            recovery_threshold=self.recovery_threshold,
            recovery_sheet_count=self.recovery_sheet_count,
            paper_size=self.paper_size,
            design=self.design,
            qr_chunk_size=self.qr_chunk_size,
            quiet=quiet,
        )

    def _assessment_key(self) -> bytes:
        state_payload = self.model_dump_json(exclude={"config_path"}).encode("utf-8")
        try:
            config_path = resolve_config_snapshot_path(self.config_path)
            config_payload = config_path.read_bytes()
        except OSError as exc:
            config_payload = f"{type(exc).__qualname__}:{exc}".encode("utf-8")
        return hashlib.sha256(state_payload + b"\0" + config_payload).digest()

    def _current_assessment_cache(self) -> _AssessmentCache | None:
        cache = self._assessment_cache
        if cache is None:
            return None
        return cache if cache.key == self._assessment_key() else None

    def _source_status(self) -> TaskSectionStatus:
        return "ready" if has_recovery_source(self) else "missing"

    def _source_summary(self) -> str:
        request = self.source_assessment_request()
        if request is not None:
            return request.source_summary
        return "Choose backup documents, recovery text, or exported payloads."

    def _read_paths(self) -> tuple[Path, ...]:
        paths = [
            *self.source_paths,
            *self.input_paths,
            *self.input_dirs,
            *self.recovery_documents,
            *self.recovery_payload_files,
        ]
        for path in (
            self.recovery_text_file,
            self.payloads_file,
            self.auth_text_file,
            self.auth_payloads_file,
        ):
            if path is not None:
                paths.append(path)
        return tuple(paths)

    def _freshness_summary(self) -> str:
        if self.expected_head_doc_hash is not None:
            return "Latest fingerprint provided"
        if self.allow_stale_head:
            return "Newest loaded version accepted"
        return "Confirm the loaded documents contain the latest version"

    def _freshness_warnings(self) -> tuple[TaskIssue, ...]:
        if not self.allow_stale_head:
            return ()
        return (
            TaskIssue(
                code="ADD_FILES_STALE_SOURCE_ACCEPTED",
                message="The loaded documents may omit a newer backup version.",
                severity="warning",
                section="freshness",
            ),
        )

    def _input_summary(self) -> str:
        base_dir = self.base_dir
        cache = self._current_assessment_cache()
        assessment = cache.assessment if cache is not None else None
        if (
            base_dir is None
            and assessment is not None
            and assessment.assessed is not None
            and assessment.assessed.prepared.request.base_directory is not None
        ):
            base_dir = Path(assessment.assessed.prepared.request.base_directory)
        return selected_paths_summary(
            input_paths=self.input_paths,
            input_dirs=self.input_dirs,
            base_dir=base_dir,
            empty_label="No files selected.",
        )

    def _advanced_summary(self) -> str:
        cache = self._current_assessment_cache()
        assessment = cache.assessment if cache is not None else None
        assessed = assessment.assessed if assessment is not None else None
        if assessed is not None:
            return ", ".join(
                (
                    self.recovery_sheet_summary(),
                    f"{assessed.output_settings.config.paper_size} "
                    f"{assessed.output_settings.config.design_name}",
                )
            )
        parts = [self.recovery_sheet_summary()]
        if self.base_dir is not None:
            parts.append(f"base {display_path(self.base_dir)}")
        if self.qr_chunk_size is not None:
            parts.append(f"QR {self.qr_chunk_size} bytes")
        return ", ".join(parts)

    def _advanced_warnings(self) -> tuple[TaskIssue, ...]:
        warnings: list[TaskIssue] = []
        if self.qr_chunk_size is not None:
            warnings.append(
                TaskIssue(
                    code="ADD_FILES_CUSTOM_QR_DENSITY",
                    message=(
                        "Custom QR density can change page count and make codes harder to scan."
                    ),
                    severity="warning",
                    section="advanced",
                )
            )
        return tuple(warnings)

    def recovery_sheet_summary(self) -> str:
        if not self.create_recovery_sheets:
            return "No new recovery sheets"
        return (
            f"{self.recovery_sheet_count} new recovery sheets, "
            f"{self.recovery_threshold} needed to restore"
        )

    def _recovery_plan_note(self) -> str:
        inherited = "The update inherits the backup's passphrase and signing key."
        if not self.create_recovery_sheets:
            return f"{inherited} No new recovery sheets will be created."
        return (
            f"{inherited} After publication, Replace Recovery Docs will create "
            f"{self.recovery_sheet_count} passphrase recovery sheets bound to the new head."
        )

    @staticmethod
    def _chain_recovery_guidance(next_index: int | None) -> str:
        if next_index is None:
            return (
                "Recovery requires the original backup and every update. Rebuild creates a new "
                "standalone backup when carrying the full chain is inconvenient."
            )
        return (
            f"Recovery requires the original backup and updates 01 through {next_index:02d}. "
            "Rebuild after publication to create a new standalone backup."
        )

    def _recovery_sheet_output_path(
        self,
        assessment: AddFilesAssessment | None,
    ) -> Path | None:
        return assessment.recovery_sheet_output_dir if assessment is not None else None


def _assessment_issue_section(issue: AddFilesIssue) -> str:
    code = issue.code
    if code in {
        "DELETE_NOT_SUPPORTED",
        api_codes.ADD_FILES_INPUT_REQUIRED,
        api_codes.ADD_FILES_NO_CHANGES,
        api_codes.ADD_FILES_NOT_REBUILDABLE,
        api_codes.EXTENSION_TOO_LARGE,
        api_codes.ADD_FILES_RECOVERY_OUTPUT_EXISTS,
    }:
        return "advanced" if code == api_codes.ADD_FILES_RECOVERY_OUTPUT_EXISTS else "files"
    if code in {api_codes.EXTENSION_PUBLISH_TARGET_INVALID, api_codes.OUTPUT_REQUIRED}:
        return "output"
    if code == "ADD_FILES_HEAD_TRUST_REQUIRED":
        return "freshness"
    if code == api_codes.RECOVERY_HEAD_UNTRUSTED and (
        "expected_head_doc_hash" in issue.details or "freshness_scope" in issue.details
    ):
        return "freshness"
    return "source"
