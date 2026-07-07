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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ethernity.cli.features.compact.service import run_compact
from ethernity.cli.shared.types import CompactArgs
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


class RebuildTaskState(BaseModel):
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
    paper_size: str = "A4"
    design: str = "sentinel"
    qr_chunk_size: int | None = None

    @model_validator(mode="after")
    def _validate_qr_chunk_size(self) -> RebuildTaskState:
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
                title="Save rebuilt backup documents to",
                status="ready" if self.output_dir is not None else "missing",
                summary=(
                    str(self.output_dir)
                    if self.output_dir is not None
                    else "No output folder selected."
                ),
                action_label="Choose output folder...",
            ),
        )

    def validate_task(self) -> TaskValidation:
        issues: list[TaskIssue] = []
        if not self._has_exactly_one_source():
            issues.append(
                TaskIssue(
                    code="REBUILD_SOURCE_REQUIRED",
                    message="Choose either a generated backup folder or backup scans.",
                    section="source",
                )
            )
        if not self._has_unlock():
            issues.append(
                TaskIssue(
                    code="REBUILD_UNLOCK_REQUIRED",
                    message="Choose a passphrase or recovery sheets.",
                    section="unlock",
                )
            )
        if self.source_paths and self.expected_head_doc_hash is None and not self.allow_stale_head:
            issues.append(
                TaskIssue(
                    code="REBUILD_HEAD_TRUST_REQUIRED",
                    message=(
                        "When rebuilding from scans, provide the expected latest backup "
                        "fingerprint or explicitly allow a stale source."
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
        if self.auth_text_file is not None and self.auth_payloads_file is not None:
            issues.append(
                TaskIssue(
                    code="REBUILD_AUTH_MATERIAL_CONFLICT",
                    message="Use authentication text or authentication payloads, not both.",
                    section="unlock",
                )
            )
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
            PreviewItem(label="Existing backup", detail=self._source_summary()),
            PreviewItem(label="Unlock method", detail=self._unlock_summary()),
            PreviewItem(label="Trust source", detail=self._auth_material_summary()),
            PreviewItem(label="Output folder", detail=str(self.output_dir or "missing")),
            PreviewItem(label="New backup documents", detail="main, recovery, and shards"),
        ]
        if self.qr_chunk_size is not None:
            items.append(PreviewItem(label="QR chunk size", detail=f"{self.qr_chunk_size} bytes"))
        return TaskPreview(
            title="Rebuilt backup to create",
            items=tuple(items),
            warnings=warnings,
        )

    def execution_plan(self) -> TaskExecutionPlan:
        outputs = (self.output_dir,) if self.output_dir is not None else ()
        return TaskExecutionPlan(
            summary=f"Rebuild backup into {self.output_dir or 'missing output'}",
            output_paths=outputs,
            writes_files=True,
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

    def _has_unlock(self) -> bool:
        return bool(self.passphrase or self.recovery_documents or self.recovery_payload_files)

    def _source_summary(self) -> str:
        if self.backup_folder is not None and self.source_paths:
            return "Choose folder or scans, not both"
        if self.backup_folder is not None:
            return str(self.backup_folder)
        if self.source_paths:
            return f"{len(self.source_paths)} scanned page path(s)"
        return "Choose backup folder or load scanned pages"

    def _unlock_summary(self) -> str:
        if self.passphrase:
            return "Passphrase provided"
        if self.recovery_documents:
            return f"{len(self.recovery_documents)} recovery sheet(s)"
        if self.recovery_payload_files:
            return f"{len(self.recovery_payload_files)} recovery payload file(s)"
        return "Choose passphrase or recovery sheets"

    def _auth_material_summary(self) -> str:
        if self.auth_text_file is not None:
            return f"Trust text: {self.auth_text_file}"
        if self.auth_payloads_file is not None:
            return f"Trust payload files: {self.auth_payloads_file}"
        return "From loaded backup"

    def _freshness_status(self) -> TaskSectionStatus:
        if not self.source_paths:
            return "ready"
        if self.expected_head_doc_hash is not None or self.allow_stale_head:
            return "ready"
        return "missing"

    def _freshness_summary(self) -> str:
        if not self.source_paths:
            return "Generated backup folder"
        if self.expected_head_doc_hash is not None:
            return "Expected latest backup fingerprint provided"
        if self.allow_stale_head:
            return "Stale source risk accepted"
        return "Confirm these scans are latest"
