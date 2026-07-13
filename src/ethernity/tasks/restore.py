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

from pydantic import ConfigDict, Field

from ethernity.cli.features.recover.service import execute_recover_plan, prepare_recover_plan
from ethernity.cli.shared.types import RecoverArgs
from ethernity.tasks.file_summary import display_path, format_count
from ethernity.tasks.models import (
    PreviewItem,
    TaskExecutionPlan,
    TaskExecutionResult,
    TaskIssue,
    TaskPreview,
    TaskSection,
    TaskValidation,
)
from ethernity.tasks.presentation.recovery import (
    auth_material_summary,
    recovery_text_summary,
    unlock_material_summary,
)
from ethernity.tasks.recovery_material import (
    has_recovery_source,
    has_unlock_material,
    recovery_text_error,
    recovery_text_frames,
)
from ethernity.tasks.source_assessment import (
    SourceAssessableTaskState,
    SourceAssessmentRequest,
    recovery_source_request,
)

RestoreTarget = Literal["latest", "original", "specific_update"]
RESTORE_DESTINATION_NON_EMPTY_WARNING = (
    "The restore folder contains files or folders; restored files with matching names may be "
    "replaced."
)


class RestoreTaskState(SourceAssessableTaskState):
    """Beginner-facing state for restoring files."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    source_paths: list[Path] = Field(default_factory=list)
    recovery_text: str | None = None
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
        destination_warning = self._destination_warning()
        source_error = recovery_text_error(
            self.recovery_text,
            allow_invalid_auth=self.allow_unsigned,
        )
        return (
            TaskSection(
                key="source",
                title="Backup source",
                status=(
                    "blocked"
                    if source_error is not None
                    else "ready"
                    if has_recovery_source(self)
                    else "missing"
                ),
                summary=(
                    "Pasted recovery text is not valid recovery text."
                    if source_error is not None
                    else self._source_summary()
                    if has_recovery_source(self)
                    else "Choose backup material."
                ),
                action_label="Load backup...",
            ),
            TaskSection(
                key="unlock",
                title="Unlock",
                status="ready" if has_unlock_material(self) else "missing",
                summary=unlock_material_summary(self),
                action_label="Set unlock method...",
            ),
            TaskSection(
                key="target",
                title="Version",
                status="ready",
                summary=self._target_summary(),
                action_label="Change target",
            ),
            TaskSection(
                key="output",
                title="Destination",
                status=(
                    "missing"
                    if self.output_path is None
                    else "warning"
                    if destination_warning
                    else "ready"
                ),
                summary=(
                    "No restore folder selected."
                    if self.output_path is None
                    else destination_warning or display_path(self.output_path)
                ),
                action_label="Choose restore folder...",
            ),
        )

    def validate_task(self) -> TaskValidation:
        issues: list[TaskIssue] = []
        if not has_recovery_source(self):
            issues.append(
                TaskIssue(
                    code="RESTORE_SOURCE_REQUIRED",
                    message="Choose backup material.",
                    section="source",
                )
            )
        if (
            self.recovery_text
            and recovery_text_error(
                self.recovery_text,
                allow_invalid_auth=self.allow_unsigned,
            )
            is not None
        ):
            issues.append(
                TaskIssue(
                    code="RESTORE_RECOVERY_TEXT_INVALID",
                    message="Pasted recovery text is not valid recovery text.",
                    section="source",
                )
            )
        if not has_unlock_material(self):
            issues.append(
                TaskIssue(
                    code="RESTORE_UNLOCK_REQUIRED",
                    message="Choose a passphrase, recovery sheets, or recovery payload files.",
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
                    message="Choose either signature text or a signature payload, not both.",
                    section="source",
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
            auth_text_file=self.auth_text_file,
            auth_payloads_file=self.auth_payloads_file,
            config_path=self.config_path,
            allow_unsigned=self.allow_unsigned,
        )

    def preview(self) -> TaskPreview:
        warnings: list[TaskIssue] = []
        if self.allow_unsigned:
            warnings.append(
                TaskIssue(
                    code="RESTORE_UNSIGNED_ALLOWED",
                    message="Unsigned legacy recovery is allowed; signatures will not be required.",
                    severity="warning",
                    section="authentication",
                )
            )
        destination_warning = self._destination_warning()
        if destination_warning is not None:
            warnings.append(
                TaskIssue(
                    code="RESTORE_DESTINATION_CONFLICT_WARNING",
                    message=destination_warning,
                    severity="warning",
                    section="output",
                )
            )
        return TaskPreview(
            title="Files to restore",
            items=(
                PreviewItem(label="Backup source", detail=self._source_summary()),
                PreviewItem(label="Latest fingerprint", detail=self._expected_head_summary()),
                PreviewItem(label="Unlock", detail=unlock_material_summary(self)),
                PreviewItem(label="Version", detail=self._target_summary()),
                PreviewItem(label="Signature check", detail=self._authentication_summary()),
                PreviewItem(
                    label="Verification source",
                    detail=auth_material_summary(self.auth_text_file, self.auth_payloads_file),
                ),
            ),
            warnings=tuple(warnings),
        )

    def execution_plan(self) -> TaskExecutionPlan:
        output_paths = (self.output_path,) if self.output_path is not None else ()
        return TaskExecutionPlan(
            summary=self._execution_summary(),
            read_paths=self._read_paths(),
            output_paths=output_paths,
            writes_files=True,
            safety_notes=self._destination_safety_notes(),
            trust_notes=(
                f"Signature check: {self._authentication_summary()}",
                "Verification source: "
                f"{auth_material_summary(self.auth_text_file, self.auth_payloads_file)}",
                f"Latest fingerprint: {self._expected_head_summary()}",
            ),
            recovery_notes=(f"Unlock: {unlock_material_summary(self)}",),
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

    def _destination_safety_notes(self) -> tuple[str, ...]:
        if self.output_path is None:
            return ()
        if not self.output_path.exists():
            return ("The restore folder does not exist and will be created.",)
        if not self.output_path.is_dir():
            return ("The restore path exists but is not a folder.",)
        try:
            has_existing_entries = any(self.output_path.iterdir())
        except OSError as exc:
            return (f"Ethernity could not inspect the restore folder: {exc}",)
        if has_existing_entries:
            return (RESTORE_DESTINATION_NON_EMPTY_WARNING,)
        return ("The restore folder exists and is empty.",)

    def _destination_warning(self) -> str | None:
        if self.output_path is None or not self.output_path.exists():
            return None
        if not self.output_path.is_dir():
            return "The restore path exists but is not a folder."
        try:
            has_existing_entries = any(self.output_path.iterdir())
        except OSError as exc:
            return f"Ethernity could not inspect the restore folder: {exc}"
        if has_existing_entries:
            return RESTORE_DESTINATION_NON_EMPTY_WARNING
        return None

    def to_recover_args(self, *, assume_yes: bool = False, quiet: bool = False) -> RecoverArgs:
        return RecoverArgs(
            config=str(self.config_path) if self.config_path is not None else None,
            frames=recovery_text_frames(
                self.recovery_text,
                allow_invalid_auth=self.allow_unsigned,
                quiet=quiet,
            ),
            fallback_file=(
                str(self.recovery_text_file)
                if self.recovery_text_file is not None and not self.recovery_text
                else None
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

    def _read_paths(self) -> tuple[Path, ...]:
        paths = [
            *self.source_paths,
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

    def _source_summary(self) -> str:
        if self.source_paths:
            return format_count(len(self.source_paths), "scanned page")
        if self.recovery_text:
            return recovery_text_summary(self.recovery_text)
        if self.recovery_text_file is not None:
            return f"Recovery text: {display_path(self.recovery_text_file)}"
        if self.payloads_file is not None:
            return f"Backup payload file: {display_path(self.payloads_file)}"
        return "Load scanned pages, paste recovery text, or load a backup payload file."

    def _expected_head_summary(self) -> str:
        if self.expected_head_doc_hash is None:
            return "Not provided"
        return "Provided"

    def _target_summary(self) -> str:
        if self.target == "original":
            return "Initial backup only"
        if self.target == "specific_update":
            if self.extension_index is not None:
                return f"Update {self.extension_index}"
            if self.extension_doc_hash is not None:
                return "Version matching fingerprint"
            return "Specific version"
        return "Newest loaded version"

    def _authentication_summary(self) -> str:
        if self.allow_unsigned:
            return "Unsigned legacy backups allowed"
        return "Trusted signatures required"

    def _recover_extension_index(self) -> int | None:
        if self.target == "original":
            return 0
        if self.target == "specific_update":
            return self.extension_index
        return None

    def _execution_summary(self) -> str:
        output = str(self.output_path) if self.output_path is not None else "missing output"
        return f"Recover files into {output}"
