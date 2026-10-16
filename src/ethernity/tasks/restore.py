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

from pydantic import ConfigDict

from ethernity.tasks.common_sections import unlock_section
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
from ethernity.tasks.presentation.recovery import (
    recovery_text_summary,
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
    ContentRecoveryTaskState,
    SourceAssessmentRequest,
)
from ethernity.workflows.execution import execute_recovery
from ethernity.workflows.shared.requests import RecoveryRequest

RestoreTarget = Literal["latest", "original", "specific_update"]
RESTORE_DESTINATION_NON_EMPTY_WARNING = (
    "The restore folder contains files or folders; restored files with matching names may be "
    "replaced."
)


class RestoreTaskState(ContentRecoveryTaskState):
    """Beginner-facing state for restoring files."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    target: RestoreTarget = "latest"
    extension_index: int | None = None
    extension_doc_hash: str | None = None
    output_path: Path | None = None
    allow_unsigned: bool = False

    def sections(self) -> tuple[TaskSection, ...]:
        destination_warning = self._destination_warning()
        source_error = recovery_text_error(
            self.recovery_text,
            allow_invalid_auth=self.allow_unsigned,
        )
        return (
            self.source_section(
                "Backup source",
                source_error,
                self._source_summary() if has_recovery_source(self) else "Choose backup documents.",
            ),
            unlock_section(self, "Unlock"),
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
                    message="Choose backup documents.",
                    section="source",
                )
            )
        issues.extend(
            self.recovery_text_issues(
                "RESTORE_RECOVERY_TEXT_INVALID", allow_unsigned=self.allow_unsigned
            )
        )
        if not has_unlock_inputs(self):
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
                    code="RESTORE_SIGNATURE_SOURCE_CONFLICT",
                    message="Choose either signature text or a signature payload, not both.",
                    section="source",
                )
            )
        return self.validation_with_source_issues(issues)

    def source_assessment_request(self) -> SourceAssessmentRequest | None:
        return self.content_source_request(
            auth_text_file=self.auth_text_file,
            auth_payloads_file=self.auth_payloads_file,
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
                PreviewItem(label="Unlock", detail=unlock_input_summary(self)),
                PreviewItem(label="Version", detail=self._target_summary()),
                PreviewItem(label="Signature check", detail=self._authentication_summary()),
                PreviewItem(
                    label="Verification source",
                    detail=signature_source_summary(self.auth_text_file, self.auth_payloads_file),
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
                f"{signature_source_summary(self.auth_text_file, self.auth_payloads_file)}",
                f"Latest fingerprint: {self._expected_head_summary()}",
            ),
            recovery_notes=(f"Unlock: {unlock_input_summary(self)}",),
        )

    def execute(self) -> TaskExecutionResult:
        validation = self.validate_task()
        validation.require_ready("Restore is not ready.")

        result = execute_recovery(self.to_recovery_request())
        return TaskExecutionResult(
            status="succeeded",
            message="Recovered files written.",
            output_paths=result.written_paths,
            details=(
                TaskResultDetail(
                    key="trust_basis",
                    label="Verification",
                    value={
                        "matched_expected_head": "Matched the trusted full fingerprint",
                        "internally_consistent": "Internally consistent; freshness unknown",
                        "unauthenticated": "Unauthenticated recovery",
                    }[result.trust_basis],
                ),
                *(
                    (
                        TaskResultDetail(
                            key="signing_key_verified",
                            label="Signing key",
                            value="Verified against the trusted full fingerprint",
                        ),
                    )
                    if result.signing_key_verified
                    else ()
                ),
            ),
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

    def to_recovery_request(self) -> RecoveryRequest:
        return RecoveryRequest(
            config_path=self.config_path,
            frames=tuple(
                recovery_text_frames(
                    self.recovery_text,
                    allow_invalid_auth=self.allow_unsigned,
                    quiet=True,
                )
                or ()
            ),
            recovery_text_file=self.external_recovery_text_file,
            payloads_file=self.payloads_file,
            scan_paths=tuple(self.source_paths),
            **self.unlock_request_fields(),
            extension_index=self._recover_extension_index(),
            extension_doc_hash=self.extension_doc_hash,
            expected_head_doc_hash=self.expected_head_doc_hash,
            output_path=self.output_path,
            allow_unsigned=self.allow_unsigned,
            quiet=True,
        )

    def _read_paths(self) -> tuple[Path, ...]:
        return self.content_read_paths(
            auth_text_file=self.auth_text_file,
            auth_payloads_file=self.auth_payloads_file,
            content_paths=(),
        )

    def _source_summary(self) -> str:
        request = self.source_assessment_request()
        if request is not None and request.source_kind == "recovery_inputs":
            return request.source_summary
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
