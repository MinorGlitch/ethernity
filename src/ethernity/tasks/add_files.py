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
from typing import Literal

from pydantic import ConfigDict, Field, PrivateAttr, field_validator, model_validator

from ethernity.cli.features.extend.execution import (
    AssessedExtendRun,
    assess_prepared_extend,
    execute_assessed_extend,
)
from ethernity.cli.features.extend.models import (
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    PlaintextPassphrase,
    ReuseRootPassphraseShards,
)
from ethernity.cli.features.extend.prepare import prepare_extend_run
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import ExtendArgs
from ethernity.config import load_cli_defaults, resolve_config_snapshot_path
from ethernity.extensions.discovery import EXTENSIONS_DIR_NAME
from ethernity.extensions.layout import canonical_extension_dir_name, loose_extension_dir_name
from ethernity.tasks.file_summary import display_path, format_count, selected_paths_summary
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
)
from ethernity.tasks.quorum import validate_optional_shard_count
from ethernity.tasks.source_assessment import (
    SourceAssessableTaskState,
    SourceAssessmentRequest,
    folder_or_scans_source_request,
)

AddFilesUnlockPolicy = Literal["self-contained", "reuse-root"]
AddFilesSigningKeyMode = Literal["not-stored", "sharded"]


@dataclass(frozen=True)
class _AssessmentCache:
    key: bytes
    assessed: AssessedExtendRun | None = None
    issue: TaskIssue | None = None


class AddFilesTaskState(SourceAssessableTaskState):
    """Beginner-facing state for adding files to an existing backup."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    backup_folder: Path | None = None
    loose_output_folder: Path | None = None
    config_path: Path | None = None
    source_paths: list[Path] = Field(default_factory=list)
    input_paths: list[Path] = Field(default_factory=list)
    input_dirs: list[Path] = Field(default_factory=list)
    base_dir: Path | None = None
    passphrase: str | None = None
    recovery_documents: list[Path] = Field(default_factory=list)
    recovery_payload_files: list[Path] = Field(default_factory=list)
    expected_head_doc_hash: str | None = None
    allow_stale_head: bool = False
    unlock_policy: AddFilesUnlockPolicy | None = None
    recovery_document_threshold: int | None = None
    recovery_document_count: int | None = None
    signing_key_mode: AddFilesSigningKeyMode | None = None
    signing_key_recovery_threshold: int | None = None
    signing_key_recovery_count: int | None = None
    paper_size: str | None = None
    design: str | None = None
    qr_chunk_size: int | None = None

    _assessment_cache: _AssessmentCache | None = PrivateAttr(default=None)

    @field_validator("recovery_document_threshold")
    @classmethod
    def _validate_recovery_threshold(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(value, label="recovery document threshold")

    @field_validator("recovery_document_count")
    @classmethod
    def _validate_recovery_count(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(
            value,
            label="recovery document count",
            allow_zero=True,
        )

    @field_validator("signing_key_recovery_threshold")
    @classmethod
    def _validate_signing_key_threshold(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(value, label="signing key recovery threshold")

    @field_validator("signing_key_recovery_count")
    @classmethod
    def _validate_signing_key_count(cls, value: int | None) -> int | None:
        return validate_optional_shard_count(value, label="signing key recovery count")

    @model_validator(mode="after")
    def _validate_qr_chunk_size(self) -> AddFilesTaskState:
        if self.qr_chunk_size is not None and self.qr_chunk_size < 1:
            raise ValueError("QR chunk size must be positive")
        return self

    def sections(self) -> tuple[TaskSection, ...]:
        sections = (
            TaskSection(
                key="backup",
                title="Current backup",
                status=self._backup_source_status(),
                summary=self._backup_source_summary(),
                action_label="Choose backup source...",
            ),
            TaskSection(
                key="source",
                title="Scan version",
                status=self._source_status(),
                summary=self._source_summary(),
                action_label="Load scanned pages...",
            ),
            TaskSection(
                key="files",
                title="Files to add or replace",
                status="ready" if self._has_inputs() else "missing",
                summary=self._input_summary(),
                action_label="Choose files...",
            ),
            TaskSection(
                key="unlock",
                title="Unlock backup",
                status="ready" if self._has_unlock() else "missing",
                summary=self._unlock_summary(),
                action_label="Set unlock method...",
            ),
            TaskSection(
                key="output",
                title="Save update to",
                status="ready" if self._output_folder() is not None else "missing",
                summary=self._output_summary(),
                action_label="Choose output folder...",
            ),
            TaskSection(
                key="advanced",
                title="Advanced",
                status=self._advanced_status(),
                summary=self._advanced_summary(),
                action_label="Review options",
            ),
        )
        cache = self._current_assessment_cache()
        if cache is None or cache.issue is None:
            return sections
        issue_section = cache.issue.section or "backup"
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
        return folder_or_scans_source_request(
            issue_section="backup",
            backup_folder=self.backup_folder,
            scan_paths=self.source_paths,
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
        try:
            assessed = assess_prepared_extend(prepare_extend_run(self.to_extend_args(quiet=True)))
        except ApiCommandError as exc:
            self._assessment_cache = _AssessmentCache(
                key=key,
                issue=TaskIssue(
                    code=exc.code,
                    message=exc.message,
                    section=_assessment_issue_section(exc.code),
                ),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._assessment_cache = _AssessmentCache(
                key=key,
                issue=TaskIssue(
                    code="ADD_FILES_ASSESSMENT_FAILED",
                    message=str(exc),
                    section="output" if _looks_like_output_error(str(exc)) else "backup",
                ),
            )
        else:
            self._assessment_cache = _AssessmentCache(key=key, assessed=assessed)

    def _basic_issues(self) -> tuple[TaskIssue, ...]:
        issues: list[TaskIssue] = []
        if self.backup_folder is None and not self.source_paths:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SOURCE_REQUIRED",
                    message="Choose a backup folder or scanned pages.",
                    section="backup",
                )
            )
        if self.backup_folder is not None and self.source_paths:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SOURCE_CONFLICT",
                    message="Choose either a backup folder or scanned pages, not both.",
                    section="backup",
                )
            )
        if not self._has_inputs():
            issues.append(
                TaskIssue(
                    code="ADD_FILES_INPUT_REQUIRED",
                    message="Choose at least one file or folder to add.",
                    section="files",
                )
            )
        if not self._has_unlock():
            issues.append(
                TaskIssue(
                    code="ADD_FILES_UNLOCK_REQUIRED",
                    message="Choose a passphrase, recovery sheets, or recovery payload files.",
                    section="unlock",
                )
            )
        if self.source_paths and self.loose_output_folder is None:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_OUTPUT_REQUIRED",
                    message="Choose a new or empty folder for the scan-based update documents.",
                    section="output",
                )
            )
        if self.backup_folder is not None and self.loose_output_folder is not None:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_OUTPUT_MODE_CONFLICT",
                    message=(
                        "A separate output folder is only used when scanned pages are the "
                        "backup source."
                    ),
                    section="output",
                )
            )
        if self.source_paths and self.expected_head_doc_hash is None and not self.allow_stale_head:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_HEAD_TRUST_REQUIRED",
                    message=(
                        "Enter the expected latest fingerprint, or accept that the scans may "
                        "be stale."
                    ),
                    section="source",
                )
            )
        issues.extend(self._advanced_issues())
        return tuple(issues)

    def preview(self) -> TaskPreview:
        cache = self._current_assessment_cache()
        assessed = cache.assessed if cache is not None else None
        recovery_summary = (
            _resolved_recovery_summary(assessed)
            if assessed is not None
            else self._recovery_documents_summary()
        )
        signing_summary = (
            _resolved_signing_summary(assessed)
            if assessed is not None
            else self._signing_key_summary()
        )
        warnings = (
            *self._source_warnings(),
            *self._advanced_warnings(),
        )
        items = [
            PreviewItem(label="Backup source", detail=self._backup_source_summary()),
            PreviewItem(label="Files", detail=self._input_summary()),
            PreviewItem(label="Unlock", detail=self._unlock_summary()),
            PreviewItem(label="Destination", detail=self._output_summary()),
            PreviewItem(label="Recovery sheets", detail=recovery_summary),
            PreviewItem(label="Signing-key recovery", detail=signing_summary),
            PreviewItem(
                label="New documents",
                detail="Backup update, recovery guide, and selected sheets",
            ),
        ]
        if assessed is not None:
            prepared = assessed.prepared
            encrypted = assessed.encrypted
            stats = encrypted.built.stats
            items.extend(
                (
                    PreviewItem(label="Next update", detail=f"{prepared.next_index:02d}"),
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
                        detail=str(
                            self._planned_output_path(
                                assessed,
                                output_folder=self._output_folder(),
                            )
                        ),
                    ),
                    PreviewItem(
                        label="Print layout",
                        detail=(
                            f"{assessed.runtime.config.paper_size}, "
                            f"{assessed.runtime.config.design_name}, "
                            f"{assessed.runtime.qr_chunk_size} bytes per QR"
                        ),
                    ),
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
        output_folder = self._output_folder()
        cache = self._current_assessment_cache()
        assessed = cache.assessed if cache is not None else None
        planned_output = self._planned_output_path(assessed, output_folder=output_folder)
        outputs = (planned_output,) if planned_output is not None else ()
        summary = (
            f"Create backup update {assessed.prepared.next_index:02d} in {output_folder}"
            if assessed is not None
            else f"Add files to {output_folder or 'missing output folder'}"
        )
        source_safety_note = (
            (
                "A scan-based update writes separate update documents; choose a new or empty "
                "destination folder."
            )
            if self.source_paths
            else (
                "Update documents are appended under the existing backup folder; existing "
                "backup documents are not replaced."
            )
        )
        return TaskExecutionPlan(
            summary=summary,
            read_paths=self._read_paths(),
            output_paths=outputs,
            writes_files=True,
            safety_notes=(
                source_safety_note,
                "Matching paths are replaced. Other paths are not deleted or renamed.",
            ),
            trust_notes=(
                f"Scan version: {self._source_summary()}",
                "Latest means the newest valid version in the material you loaded.",
            ),
            recovery_notes=(
                f"Unlock: {self._unlock_summary()}",
                "Recovery sheets: "
                + (
                    _resolved_recovery_summary(assessed)
                    if assessed is not None
                    else self._recovery_documents_summary()
                ),
                "Signing-key recovery: "
                + (
                    _resolved_signing_summary(assessed)
                    if assessed is not None
                    else self._signing_key_summary()
                ),
                (
                    "The original backup and enough recovery material authorize this update. "
                    "Key sheets recover the signing key; they do not add another approval."
                ),
                *(
                    (
                        "Keep these scan-based update documents with the original backup and "
                        "every earlier update; they cannot restore files on their own.",
                    )
                    if self.source_paths
                    else ()
                ),
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
        if cache is None or cache.assessed is None:
            raise ValueError("The update could not be prepared for review.")
        executed = execute_assessed_extend(
            cache.assessed,
            config_path=str(self.config_path) if self.config_path is not None else None,
        )
        result = executed.result
        output_paths = (
            result.qr_document_path,
            result.recovery_document_path,
            *result.shard_paths,
            *result.signing_key_shard_paths,
        )
        if result.recovery_kit_index_path is not None:
            output_paths = (*output_paths, result.recovery_kit_index_path)
        prepared = executed.prepared
        encrypted = executed.publish.encrypted
        stats = encrypted.built.stats
        publish_layout = executed.publish.artifacts.publish_layout
        next_steps = (
            (
                "Keep the original backup, every earlier update, and this update together. "
                "This scan-based update cannot restore files by itself."
            ),
            "Save the new fingerprint as the expected latest version before the next update.",
        )
        return TaskExecutionResult(
            ok=True,
            message=f"Added files as backup update {result.index:02d}.",
            output_paths=output_paths,
            details=(
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
                    key="publish_layout",
                    label="Publication layout",
                    value=publish_layout,
                ),
                TaskResultDetail(
                    key="publish_root",
                    label="Publication root",
                    value=str(result.publish_root or result.final_dir.parent),
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
                    key="logical_bytes",
                    label="Changed logical bytes",
                    value=stats.logical_bytes,
                ),
                TaskResultDetail(
                    key="new_chunks",
                    label="New chunks",
                    value=stats.new_chunks,
                ),
                TaskResultDetail(
                    key="reused_chunks",
                    label="Reused chunks",
                    value=stats.reused_chunks,
                ),
                TaskResultDetail(
                    key="extension_plaintext_bytes",
                    label="Extension payload bytes",
                    value=len(encrypted.plaintext),
                ),
                TaskResultDetail(
                    key="extension_ciphertext_bytes",
                    label="Encrypted extension bytes",
                    value=len(encrypted.ciphertext),
                ),
            ),
            next_steps=(
                next_steps
                if self.source_paths
                else (
                    "Save the new fingerprint as the expected latest version before the next "
                    "update.",
                )
            ),
        )

    def recoverable_errors(self) -> tuple[TaskIssue, ...]:
        return self.validate_task().issues

    def to_extend_args(self, *, quiet: bool = False) -> ExtendArgs:
        root_dir = self.loose_output_folder if self.source_paths else self.backup_folder
        base_dir = self.base_dir
        if base_dir is None:
            defaults = load_cli_defaults(self.config_path).extend
            base_dir = Path(defaults.base_dir) if defaults.base_dir is not None else None
        return ExtendArgs(
            config=str(self.config_path) if self.config_path is not None else None,
            root_dir=str(root_dir) if root_dir is not None else None,
            scan=[str(path) for path in self.source_paths],
            input=[str(path) for path in self.input_paths],
            input_dir=[str(path) for path in self.input_dirs],
            base_dir=str(base_dir) if base_dir is not None else None,
            passphrase=self.passphrase,
            shard_scan=[str(path) for path in self.recovery_documents],
            shard_payloads_file=[str(path) for path in self.recovery_payload_files],
            unlock_policy=self.unlock_policy,
            shard_threshold=self.recovery_document_threshold,
            shard_count=self.recovery_document_count,
            signing_key_mode=self.signing_key_mode,
            signing_key_shard_threshold=self.signing_key_recovery_threshold,
            signing_key_shard_count=self.signing_key_recovery_count,
            expected_head_doc_hash=self.expected_head_doc_hash,
            allow_stale_head=self.allow_stale_head,
            paper=self.paper_size,
            design=self.design,
            qr_chunk_size=self.qr_chunk_size,
            quiet=quiet,
        )

    def _has_inputs(self) -> bool:
        return bool(self.input_paths or self.input_dirs)

    def _has_unlock(self) -> bool:
        return bool(self.passphrase or self.recovery_documents or self.recovery_payload_files)

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

    def _backup_source_status(self) -> TaskSectionStatus:
        if self.backup_folder is not None and self.source_paths:
            return "blocked"
        if self.backup_folder is not None or self.source_paths:
            return "ready"
        return "missing"

    def _backup_source_summary(self) -> str:
        if self.backup_folder is not None and self.source_paths:
            return "Choose either the backup folder or scanned pages, not both."
        if self.source_paths:
            return format_count(len(self.source_paths), "scanned page")
        if self.backup_folder is not None:
            return display_path(self.backup_folder)
        return "Choose a backup folder or scanned pages."

    def _output_folder(self) -> Path | None:
        return self.loose_output_folder if self.source_paths else self.backup_folder

    def _planned_output_path(
        self,
        assessed: AssessedExtendRun | None,
        *,
        output_folder: Path | None,
    ) -> Path | None:
        if output_folder is None or assessed is None:
            return output_folder
        if self.source_paths:
            return output_folder / loose_extension_dir_name(
                assessed.prepared.next_index,
                assessed.encrypted.doc_id.hex(),
            )
        return (
            output_folder
            / EXTENSIONS_DIR_NAME
            / canonical_extension_dir_name(assessed.prepared.next_index)
        )

    def _read_paths(self) -> tuple[Path, ...]:
        paths = [
            *self.source_paths,
            *self.input_paths,
            *self.input_dirs,
            *self.recovery_documents,
            *self.recovery_payload_files,
        ]
        if self.backup_folder is not None:
            paths.insert(0, self.backup_folder)
        return tuple(paths)

    def _source_status(self) -> TaskSectionStatus:
        if not self.source_paths:
            return "ready"
        if self.expected_head_doc_hash is not None:
            return "ready"
        if self.allow_stale_head:
            return "warning"
        return "missing"

    def _source_summary(self) -> str:
        if self.source_paths:
            if self.expected_head_doc_hash is not None:
                return "Latest fingerprint provided"
            if self.allow_stale_head:
                return "Latest loaded version accepted"
            return "Confirm the scans contain the latest version"
        return "Backup folder"

    def _input_summary(self) -> str:
        base_dir = self.base_dir
        cache = self._current_assessment_cache()
        if (
            base_dir is None
            and cache is not None
            and cache.assessed is not None
            and cache.assessed.prepared.args.base_dir is not None
        ):
            base_dir = Path(cache.assessed.prepared.args.base_dir)
        return selected_paths_summary(
            input_paths=self.input_paths,
            input_dirs=self.input_dirs,
            base_dir=base_dir,
            empty_label="No files selected.",
        )

    def _unlock_summary(self) -> str:
        if self.passphrase:
            return "Passphrase"
        if self.recovery_documents:
            return format_count(len(self.recovery_documents), "recovery sheet")
        if self.recovery_payload_files:
            return format_count(len(self.recovery_payload_files), "recovery payload file")
        return "Choose an unlock method"

    def _output_summary(self) -> str:
        output_folder = self._output_folder()
        if output_folder is None and self.source_paths:
            return "Choose a new or empty folder for the scan-based update documents."
        if output_folder is None:
            return "Choose the backup folder that will receive the update."
        if self.source_paths:
            return f"Separate update: {display_path(output_folder)}"
        return f"Add to backup: {display_path(output_folder)}"

    def _advanced_summary(self) -> str:
        cache = self._current_assessment_cache()
        assessed = cache.assessed if cache is not None else None
        if assessed is not None:
            return ", ".join(
                (
                    _resolved_recovery_summary(assessed),
                    _resolved_signing_summary(assessed),
                    f"{assessed.runtime.config.paper_size} {assessed.runtime.config.design_name}",
                )
            )
        parts = [
            {
                None: "Recovery from settings",
                "self-contained": "Self-contained update",
                "reuse-root": "Reuse original recovery",
            }[self.unlock_policy],
            self._recovery_documents_summary(),
            self._signing_key_summary(),
        ]
        if self.base_dir is not None:
            parts.append(f"base {display_path(self.base_dir)}")
        if self.qr_chunk_size is not None:
            parts.append(f"QR {self.qr_chunk_size} bytes")
        return ", ".join(parts)

    def _advanced_status(self) -> TaskSectionStatus:
        if self._advanced_issues():
            return "blocked"
        if self._advanced_warnings():
            return "warning"
        return "optional"

    def _recovery_documents_summary(self) -> str:
        if self.recovery_document_count == 0:
            return "No new recovery sheets"
        if (
            self.recovery_document_threshold is not None
            and self.recovery_document_count is not None
        ):
            return (
                f"{self.recovery_document_count} recovery sheets; "
                f"any {self.recovery_document_threshold} required"
            )
        return "Recovery sheets from settings"

    def _signing_key_summary(self) -> str:
        if self.signing_key_mode is None:
            return "From settings"
        if self.signing_key_mode == "not-stored":
            return "No separate key sheets"
        if (
            self.signing_key_recovery_threshold is not None
            and self.signing_key_recovery_count is not None
        ):
            return (
                f"{self.signing_key_recovery_count} key sheets; "
                f"any {self.signing_key_recovery_threshold} can recover the key"
            )
        return "Separate key sheets"

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
        if self.recovery_document_count == 0:
            warnings.append(
                TaskIssue(
                    code="ADD_FILES_RECOVERY_SHEETS_SKIPPED",
                    message=(
                        "This update will rely on existing recovery material; no new recovery "
                        "sheets will be created."
                    ),
                    severity="warning",
                    section="advanced",
                )
            )
        elif (
            self.recovery_document_threshold is not None
            and self.recovery_document_count is not None
        ):
            warnings.append(
                TaskIssue(
                    code="ADD_FILES_CUSTOM_RECOVERY_QUORUM",
                    message=(
                        "A custom quorum changes how many sheets you need to recover this update."
                    ),
                    severity="warning",
                    section="advanced",
                )
            )
        if self.signing_key_mode == "not-stored":
            warnings.append(
                TaskIssue(
                    code="ADD_FILES_SIGNING_KEY_NOT_STORED",
                    message=(
                        "No separate signing-key recovery sheets will be created. The update "
                        "remains signed."
                    ),
                    severity="warning",
                    section="advanced",
                )
            )
        elif (
            self.signing_key_mode == "sharded"
            and self.signing_key_recovery_threshold is not None
            and self.signing_key_recovery_count is not None
        ):
            warnings.append(
                TaskIssue(
                    code="ADD_FILES_CUSTOM_SIGNING_KEY_QUORUM",
                    message=(
                        "A custom key-sheet quorum changes how many sheets you need to recover "
                        "the signing key."
                    ),
                    severity="warning",
                    section="advanced",
                )
            )
        return tuple(warnings)

    def _advanced_issues(self) -> tuple[TaskIssue, ...]:
        issues: list[TaskIssue] = []
        if self.unlock_policy == "reuse-root" and (
            self.recovery_document_threshold is not None or self.recovery_document_count is not None
        ):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_REUSE_ROOT_RECOVERY_OVERRIDE",
                    message=(
                        "Original recovery cannot be combined with new recovery-sheet settings."
                    ),
                    section="advanced",
                )
            )
        if self.recovery_document_count == 0 and self.recovery_document_threshold is not None:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_RECOVERY_THRESHOLD_WITHOUT_DOCUMENTS",
                    message="Clear the recovery threshold or create recovery sheets.",
                    section="advanced",
                )
            )
        if (
            self.recovery_document_threshold is not None
            and self.recovery_document_count is not None
            and self.recovery_document_count > 0
            and self.recovery_document_threshold > self.recovery_document_count
        ):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_RECOVERY_QUORUM_INVALID",
                    message="Required recovery sheets cannot exceed the total.",
                    section="advanced",
                )
            )
        if self.signing_key_mode == "not-stored" and (
            self.signing_key_recovery_threshold is not None
            or self.signing_key_recovery_count is not None
        ):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SIGNING_KEY_SHARDS_NOT_STORED",
                    message="Choose separate key sheets before setting their quorum.",
                    section="advanced",
                )
            )
        if (
            self.signing_key_recovery_threshold is not None
            and self.signing_key_recovery_count is not None
            and self.signing_key_recovery_threshold > self.signing_key_recovery_count
        ):
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SIGNING_KEY_QUORUM_INVALID",
                    message="Required key sheets cannot exceed the total.",
                    section="advanced",
                )
            )
        if self.signing_key_mode == "sharded" and self.recovery_document_count == 0:
            issues.append(
                TaskIssue(
                    code="ADD_FILES_SIGNING_KEY_REQUIRES_RECOVERY_DOCS",
                    message="Signing-key recovery sheets require passphrase recovery sheets.",
                    section="advanced",
                )
            )
        return tuple(issues)

    def _source_warnings(self) -> tuple[TaskIssue, ...]:
        if not self.source_paths or not self.allow_stale_head:
            return ()
        return (
            TaskIssue(
                code="ADD_FILES_STALE_SOURCE_ACCEPTED",
                message="These scans may not contain the latest backup version.",
                severity="warning",
                section="source",
            ),
        )


def _assessment_issue_section(code: str) -> str:
    if code in {
        "DELETE_NOT_SUPPORTED",
        "EXTENSION_INPUT_REQUIRED",
        "EXTENSION_NO_CHANGES",
        "EXTENSION_TOO_LARGE",
    }:
        return "files"
    if code == api_codes.EXTENSION_PUBLISH_TARGET_INVALID:
        return "output"
    return "backup"


def _looks_like_output_error(message: str) -> bool:
    normalized = message.lower()
    return any(
        phrase in normalized
        for phrase in (
            "output",
            "publish target",
            "not writable",
            "empty directory",
            "render",
        )
    )


def _resolved_recovery_summary(assessed: AssessedExtendRun) -> str:
    passphrase = assessed.runtime.passphrase
    if isinstance(passphrase, ReuseRootPassphraseShards):
        return (
            f"Original recovery sheets; any {passphrase.threshold} of "
            f"{passphrase.share_count} required"
        )
    if isinstance(passphrase, ExtensionPassphraseShards):
        return (
            f"{passphrase.share_count} update recovery sheets; any {passphrase.threshold} required"
        )
    if isinstance(passphrase, PlaintextPassphrase):
        return "Passphrase included in the update recovery document"
    raise TypeError(f"unsupported extension passphrase policy: {type(passphrase).__qualname__}")


def _resolved_signing_summary(assessed: AssessedExtendRun) -> str:
    signing_key = assessed.runtime.signing_key
    if isinstance(signing_key, ExtensionSigningKeyShards):
        return (
            f"{signing_key.share_count} key sheets; any {signing_key.threshold} can recover the key"
        )
    return "No separate key sheets"
