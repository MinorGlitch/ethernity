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

from ethernity.cli.features.compact.service import run_compact
from ethernity.cli.shared.types import CompactArgs
from ethernity.page_sizes import DEFAULT_PAPER_SIZE_NAME, PaperSizeName, resolve_paper_size
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
from ethernity.tasks.page_layout import (
    BACKUP_RENDER_DOC_TYPES,
    require_workflow_page_size,
)
from ethernity.tasks.presentation.recovery import auth_material_summary, unlock_material_summary
from ethernity.tasks.recovery_material import has_unlock_material
from ethernity.tasks.source_assessment import (
    SourceAssessableTaskState,
    SourceAssessmentRequest,
    folder_or_scans_source_request,
    source_freshness_status,
)


class RebuildTaskState(SourceAssessableTaskState):
    """Beginner-facing state for rebuilding a backup from its latest recoverable state."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    backup_folder: Path | None = None
    config_path: Path | None = None
    source_paths: list[Path] = Field(default_factory=list)
    output_dir: Path | None = None
    passphrase: str | None = None
    recovery_documents: list[Path] = Field(default_factory=list)
    recovery_payload_files: list[Path] = Field(default_factory=list)
    auth_text_file: Path | None = None
    auth_payloads_file: Path | None = None
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    paper_size: PaperSizeName = DEFAULT_PAPER_SIZE_NAME
    design: str = "sentinel"
    qr_chunk_size: int | None = None

    @field_validator("paper_size")
    @classmethod
    def _validate_paper_size(cls, value: str) -> PaperSizeName:
        return resolve_paper_size(value).name

    @model_validator(mode="after")
    def _validate_qr_chunk_size(self) -> RebuildTaskState:
        require_workflow_page_size(
            self.design,
            self.paper_size,
            candidate_doc_types=BACKUP_RENDER_DOC_TYPES,
        )
        if self.qr_chunk_size is not None and self.qr_chunk_size < 1:
            raise ValueError("QR chunk size must be positive")
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
            TaskSection(
                key="unlock",
                title="Unlock backup",
                status="ready" if has_unlock_material(self) else "missing",
                summary=unlock_material_summary(self),
                action_label="Set unlock method...",
            ),
            TaskSection(
                key="freshness",
                title="Scan version",
                status=source_freshness_status(
                    self.source_paths,
                    expected_head_doc_hash=self.expected_head_doc_hash,
                    allow_stale_head=self.allow_stale_head,
                ),
                summary=self._freshness_summary(),
                action_label="Confirm source",
            ),
            TaskSection(
                key="output",
                title="Save rebuilt backup to",
                status=selected_output_status(self.output_dir),
                summary=existing_output_summary(
                    self.output_dir,
                    target="output_folder",
                    missing_summary="No output folder selected.",
                ),
                action_label="Choose output folder...",
            ),
            TaskSection(
                key="advanced",
                title="Advanced",
                status=self._advanced_status(),
                summary=self._advanced_summary(),
                action_label="Review advanced options",
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
        if not has_unlock_material(self):
            issues.append(
                TaskIssue(
                    code="REBUILD_UNLOCK_REQUIRED",
                    message="Choose a passphrase, recovery sheets, or recovery payload files.",
                    section="unlock",
                )
            )
        if self.source_paths and self.expected_head_doc_hash is None and not self.allow_stale_head:
            issues.append(
                TaskIssue(
                    code="REBUILD_HEAD_TRUST_REQUIRED",
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
                    code="REBUILD_OUTPUT_REQUIRED",
                    message="Choose where rebuilt backup documents will be saved.",
                    section="output",
                )
            )
        issues.extend(self._advanced_issues())
        return TaskValidation(
            sections=self.sections(),
            issues=self.source_assessment_issues(issues),
        )

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
            *existing_output_warning(
                self.output_dir,
                code="REBUILD_OUTPUT_EXISTS",
                target="output_folder",
            ),
            *self._freshness_warnings(),
            *self._advanced_warnings(),
        )
        items = [
            PreviewItem(label="Existing backup", detail=self._source_summary()),
            PreviewItem(label="Unlock", detail=unlock_material_summary(self)),
            PreviewItem(label="Scan version", detail=self._freshness_summary()),
            PreviewItem(
                label="Verification source",
                detail=auth_material_summary(self.auth_text_file, self.auth_payloads_file),
            ),
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
            PreviewItem(
                label="Credentials",
                detail="Same passphrase and signing key",
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
        outputs = (self.output_dir,) if self.output_dir is not None else ()
        return TaskExecutionPlan(
            summary=f"Rebuild backup into {self.output_dir or 'missing output'}",
            read_paths=self._read_paths(),
            output_paths=outputs,
            writes_files=True,
            safety_notes=(
                "Ethernity will create the folder if needed and write the rebuilt PDFs inside it.",
                "Existing backup files stay unchanged.",
            ),
            trust_notes=(
                f"Scan version: {self._freshness_summary()}",
                "Latest means the newest valid version in the material you loaded.",
                "Verification source: "
                f"{auth_material_summary(self.auth_text_file, self.auth_payloads_file)}",
            ),
            recovery_notes=(
                f"Unlock: {unlock_material_summary(self)}",
                "The rebuilt backup gets a new set of recovery sheets.",
                "The passphrase and signing key stay the same.",
                "Use Create backup when you need a new passphrase or signing key.",
            ),
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        if not validation.ready:
            first_issue = validation.issues[0] if validation.issues else None
            message = first_issue.message if first_issue is not None else "Rebuild is not ready."
            raise ValueError(message)

        result = run_compact(self.to_compact_args(quiet=True))
        output_paths = (
            Path(result.qr_path),
            Path(result.recovery_path),
            *[Path(path) for path in result.shard_paths],
            *[Path(path) for path in result.signing_key_shard_paths],
        )
        if result.kit_index_path is not None:
            output_paths = (*output_paths, Path(result.kit_index_path))
        return TaskExecutionResult(
            ok=True,
            message="Rebuilt backup documents created.",
            output_paths=output_paths,
            next_steps=(
                "The rebuilt backup uses the same passphrase and signing key.",
                "Use Create backup when you need a new passphrase or signing key.",
            ),
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def to_compact_args(self, *, quiet: bool = False) -> CompactArgs:
        return CompactArgs(
            config=str(self.config_path) if self.config_path is not None else None,
            root_dir=str(self.backup_folder) if self.backup_folder is not None else None,
            scan=[str(path) for path in self.source_paths],
            output_dir=str(self.output_dir) if self.output_dir is not None else None,
            passphrase=self.passphrase,
            shard_scan=[str(path) for path in self.recovery_documents],
            shard_payloads_file=[str(path) for path in self.recovery_payload_files],
            auth_fallback_file=(
                str(self.auth_text_file) if self.auth_text_file is not None else None
            ),
            auth_payloads_file=(
                str(self.auth_payloads_file) if self.auth_payloads_file is not None else None
            ),
            expected_head_doc_hash=self.expected_head_doc_hash,
            allow_stale_head=self.allow_stale_head,
            paper=self.paper_size,
            design=self.design,
            qr_chunk_size=self.qr_chunk_size,
            quiet=quiet,
        )

    def _has_exactly_one_source(self) -> bool:
        return (self.backup_folder is not None) != bool(self.source_paths)

    def _read_paths(self) -> tuple[Path, ...]:
        paths = [
            *self.source_paths,
            *self.recovery_documents,
            *self.recovery_payload_files,
        ]
        if self.backup_folder is not None:
            paths.insert(0, self.backup_folder)
        for path in (self.auth_text_file, self.auth_payloads_file):
            if path is not None:
                paths.append(path)
        return tuple(paths)

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
            auth_material_summary(self.auth_text_file, self.auth_payloads_file)
            if has_source or self.auth_text_file is not None or self.auth_payloads_file is not None
            else "Verification available after loading a backup"
        ]
        if self.qr_chunk_size is not None:
            parts.append(f"QR {self.qr_chunk_size} bytes")
        else:
            parts.append("QR from settings")
        return ", ".join(parts)

    def _advanced_status(self) -> TaskSectionStatus:
        if self._advanced_issues():
            return "blocked"
        if self._advanced_warnings():
            return "warning"
        return "optional"

    def _advanced_warnings(self) -> tuple[TaskIssue, ...]:
        if self.qr_chunk_size is None:
            return ()
        return (
            TaskIssue(
                code="REBUILD_CUSTOM_QR_DENSITY",
                message="Custom QR density can change page count and make codes harder to scan.",
                severity="warning",
                section="advanced",
            ),
        )

    def _advanced_issues(self) -> tuple[TaskIssue, ...]:
        if self.auth_text_file is not None and self.auth_payloads_file is not None:
            return (
                TaskIssue(
                    code="REBUILD_AUTH_MATERIAL_CONFLICT",
                    message="Choose either signature text or a signature payload, not both.",
                    section="advanced",
                ),
            )
        return ()

    def _freshness_summary(self) -> str:
        if not self.source_paths:
            return "Backup folder"
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
                code="REBUILD_STALE_SOURCE_ACCEPTED",
                message="These scans may not contain the latest backup version.",
                severity="warning",
                section="freshness",
            ),
        )
