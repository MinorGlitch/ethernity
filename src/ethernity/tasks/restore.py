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

from pydantic import BaseModel, ConfigDict, Field

from ethernity.cli.features.recover.service import execute_recover_plan, prepare_recover_plan
from ethernity.cli.shared.types import RecoverArgs
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskSection,
    TaskValidation,
)

RestoreTarget = Literal["latest", "original", "specific_update"]


class RestoreTaskState(BaseModel):
    """Beginner-facing state for restoring files."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    source_paths: list[Path] = Field(default_factory=list)
    recovery_text_file: Path | None = None
    payloads_file: Path | None = None
    auth_text_file: Path | None = None
    auth_payloads_file: Path | None = None
    config_path: Path | None = None
    passphrase: str | None = None
    recovery_documents: list[Path] = Field(default_factory=list)
    recovery_payload_files: list[Path] = Field(default_factory=list)
    target: RestoreTarget = "latest"
    extension_index: int | None = None
    extension_doc_hash: str | None = None
    expected_head_doc_hash: str | None = None
    output_path: Path | None = None
    allow_unsigned: bool = False

    def sections(self) -> tuple[TaskSection, ...]:
        return (
            TaskSection(
                key="source",
                title="Backup to restore",
                status="ready" if self._has_source() else "missing",
                summary=self._source_summary(),
                action_label="Load backup...",
            ),
            TaskSection(
                key="unlock",
                title="Unlock backup",
                status="ready" if self._has_unlock() else "missing",
                summary=self._unlock_summary(),
                action_label="Set unlock method...",
            ),
            TaskSection(
                key="target",
                title="Version to restore",
                status="ready",
                summary=self._target_summary(),
                action_label="Change target",
            ),
            TaskSection(
                key="output",
                title="Restore files to",
                status="ready" if self.output_path is not None else "missing",
                summary=(
                    str(self.output_path)
                    if self.output_path is not None
                    else "No restore folder selected."
                ),
                action_label="Choose restore folder...",
            ),
        )

    def validate_task(self) -> TaskValidation:
        issues: list[TaskIssue] = []
        if not self._has_source():
            issues.append(
                TaskIssue(
                    code="RESTORE_SOURCE_REQUIRED",
                    message="Load a backup before continuing.",
                    section="source",
                )
            )
        if not self._has_unlock():
            issues.append(
                TaskIssue(
                    code="RESTORE_UNLOCK_REQUIRED",
                    message="Choose a passphrase or recovery sheets.",
                    section="unlock",
                )
            )
        if self.output_path is None:
            issues.append(
                TaskIssue(
                    code="RESTORE_OUTPUT_REQUIRED",
                    message="Choose where recovered files will be written.",
                    section="output",
                )
            )
        if (
            self.target == "specific_update"
            and self.extension_index is None
            and self.extension_doc_hash is None
        ):
            issues.append(
                TaskIssue(
                    code="RESTORE_UPDATE_REQUIRED",
                    message="Choose the backup update to restore.",
                    section="target",
                )
            )
        if self.auth_text_file is not None and self.auth_payloads_file is not None:
            issues.append(
                TaskIssue(
                    code="RESTORE_AUTH_MATERIAL_CONFLICT",
                    message="Use authentication text or authentication payloads, not both.",
                    section="source",
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
        return TaskPreview(
            title="Files to restore",
            items=(
                PreviewItem(label="Backup to restore", detail=self._source_summary()),
                PreviewItem(label="Newest loaded version", detail=self._expected_head_summary()),
                PreviewItem(label="Unlock method", detail=self._unlock_summary()),
                PreviewItem(label="Version to restore", detail=self._target_summary()),
                PreviewItem(label="Signature check", detail=self._authentication_summary()),
                PreviewItem(label="Trust source", detail=self._auth_material_summary()),
            ),
            warnings=warnings,
        )

    def execution_plan(self) -> TaskExecutionPlan:
        output_paths = (self.output_path,) if self.output_path is not None else ()
        return TaskExecutionPlan(
            summary=self._execution_summary(),
            output_paths=output_paths,
            writes_files=True,
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        if not validation.ready:
            first_issue = validation.issues[0] if validation.issues else None
            message = first_issue.message if first_issue is not None else "Restore is not ready."
            raise ValueError(message)

        args = self.to_recover_args(assume_yes=True, quiet=True)
        plan = prepare_recover_plan(args)
        result = execute_recover_plan(plan, quiet=True)
        output_paths = tuple(Path(path) for path in result.written_paths)
        return TaskExecutionResult(
            ok=True,
            message="Recovered files written.",
            output_paths=output_paths,
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def to_recover_args(self, *, assume_yes: bool = False, quiet: bool = False) -> RecoverArgs:
        return RecoverArgs(
            config=str(self.config_path) if self.config_path is not None else None,
            fallback_file=(
                str(self.recovery_text_file) if self.recovery_text_file is not None else None
            ),
            payloads_file=str(self.payloads_file) if self.payloads_file is not None else None,
            scan=[str(path) for path in self.source_paths] or None,
            passphrase=self.passphrase,
            shard_scan=[str(path) for path in self.recovery_documents] or None,
            shard_payloads_file=[str(path) for path in self.recovery_payload_files] or None,
            auth_fallback_file=(
                str(self.auth_text_file) if self.auth_text_file is not None else None
            ),
            auth_payloads_file=(
                str(self.auth_payloads_file) if self.auth_payloads_file is not None else None
            ),
            extension_index=self._recover_extension_index(),
            extension_doc_hash=self.extension_doc_hash,
            expected_head_doc_hash=self.expected_head_doc_hash,
            output=str(self.output_path) if self.output_path is not None else None,
            allow_unsigned=self.allow_unsigned,
            assume_yes=assume_yes,
            quiet=quiet,
        )

    def _has_source(self) -> bool:
        return bool(self.source_paths or self.recovery_text_file or self.payloads_file)

    def _has_unlock(self) -> bool:
        return bool(self.passphrase or self.recovery_documents or self.recovery_payload_files)

    def _source_summary(self) -> str:
        if self.source_paths:
            return f"{len(self.source_paths)} scanned page path(s)"
        if self.recovery_text_file is not None:
            return f"Recovery text: {self.recovery_text_file}"
        if self.payloads_file is not None:
            return f"Payload files: {self.payloads_file}"
        return "Load scanned pages, paste recovery text, or load payload files."

    def _expected_head_summary(self) -> str:
        if self.expected_head_doc_hash is None:
            return "Not set"
        return "Expected latest backup fingerprint provided"

    def _unlock_summary(self) -> str:
        if self.passphrase:
            return "Passphrase provided"
        if self.recovery_documents:
            return f"{len(self.recovery_documents)} recovery sheet(s)"
        if self.recovery_payload_files:
            return f"{len(self.recovery_payload_files)} recovery payload file(s)"
        return "Choose passphrase or recovery sheets"

    def _target_summary(self) -> str:
        if self.target == "original":
            return "Initial backup only"
        if self.target == "specific_update":
            if self.extension_index is not None:
                return f"Version/update {self.extension_index}"
            if self.extension_doc_hash is not None:
                return "Specific version/update by fingerprint"
            return "Specific version/update"
        return "Newest loaded version"

    def _authentication_summary(self) -> str:
        if self.allow_unsigned:
            return "Allow unsigned legacy recovery"
        return "Require trusted signature"

    def _auth_material_summary(self) -> str:
        if self.auth_text_file is not None:
            return f"Trust text: {self.auth_text_file}"
        if self.auth_payloads_file is not None:
            return f"Trust payload files: {self.auth_payloads_file}"
        return "From loaded backup"

    def _recover_extension_index(self) -> int | None:
        if self.target == "original":
            return 0
        if self.target == "specific_update":
            return self.extension_index
        return None

    def _execution_summary(self) -> str:
        output = str(self.output_path) if self.output_path is not None else "missing output"
        return f"Recover files into {output}"
