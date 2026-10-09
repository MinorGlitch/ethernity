from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, Field, PrivateAttr

from ethernity.crypto.age_policy import recovery_kdf_budget
from ethernity.encoding.framing import FrameType
from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import TaskIssue, TaskSection, TaskSectionStatus, TaskValidation
from ethernity.tasks.presentation.recovery import pasted_text_summary
from ethernity.tasks.recovery_inputs import has_recovery_source, recovery_text_error
from ethernity.tasks.source_types import SourceDescription, SourceKind
from ethernity.workflows.execution import (
    WorkflowExecutionError,
    inspect_recovery,
)
from ethernity.workflows.recovery.frame_inputs import frames_from_fallback_text
from ethernity.workflows.recovery.models import RecoveryInspection
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.requests import RecoveryRequest

_UNLOCK_ONLY_BLOCKERS = frozenset(
    {
        issue_codes.PASSPHRASE_REQUIRED,
        issue_codes.PASSPHRASE_SHARDS_UNDER_QUORUM,
        issue_codes.PASSPHRASE_SHARDS_INVALID,
    }
)


def source_freshness_status(
    source_paths: Sequence[Path],
    *,
    expected_head_doc_hash: str | None,
    allow_stale_head: bool,
) -> TaskSectionStatus:
    if not source_paths or expected_head_doc_hash is not None:
        return "ready"
    if allow_stale_head:
        return "warning"
    return "missing"


@dataclass(frozen=True, slots=True)
class SourceAssessmentRequest:
    """A source-only, read-only assessment request owned by the task layer."""

    source_kind: SourceKind
    source_label: str
    source_summary: str
    issue_section: str
    backup_folder: Path | None = None
    scan_paths: tuple[Path, ...] = ()
    recovery_text: str | None = None
    recovery_text_file: Path | None = None
    payloads_file: Path | None = None
    auth_text_file: Path | None = None
    auth_payloads_file: Path | None = None
    config_path: Path | None = None
    allow_unsigned: bool = False

    @property
    def key(self) -> str:
        payload = {
            "source_kind": self.source_kind,
            "backup_folder": _path_text(self.backup_folder),
            "scan_paths": [_path_text(path) for path in self.scan_paths],
            "recovery_text": self.recovery_text,
            "recovery_text_file": _path_text(self.recovery_text_file),
            "payloads_file": _path_text(self.payloads_file),
            "auth_text_file": _path_text(self.auth_text_file),
            "auth_payloads_file": _path_text(self.auth_payloads_file),
            "config_path": _path_text(self.config_path),
            "allow_unsigned": self.allow_unsigned,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceAssessment(SourceDescription):
    """Decoded source details and errors found without writing any data."""

    issue: TaskIssue | None = None
    document_summary: str = ""
    unlock_summary: str = ""
    unlock_ready: bool = False
    has_updates: bool = False
    document_count: int = 0
    root_doc_hash: str = ""


@dataclass(frozen=True, slots=True)
class _SourceAssessmentCache:
    key: str
    assessment: SourceAssessment


class SourceAssessableTaskState(BaseModel):
    """Base for task states that expose a derived, source-only assessment."""

    _source_assessment_cache: _SourceAssessmentCache | None = PrivateAttr(default=None)

    def source_assessment_request(self) -> SourceAssessmentRequest | None:
        raise NotImplementedError

    def current_source_assessment(self) -> SourceAssessment | None:
        request = self.source_assessment_request()
        cache = self._source_assessment_cache
        if request is None or cache is None or cache.key != request.key:
            return None
        return cache.assessment

    def assess_source(self) -> SourceAssessment | None:
        """Assess the current source and publish the result only if the source is unchanged."""

        request = self.source_assessment_request()
        if request is None:
            self._source_assessment_cache = None
            return None
        assessment = assess_source_request(request)
        self.store_source_assessment(request, assessment)
        return assessment

    def store_source_assessment(
        self,
        request: SourceAssessmentRequest,
        assessment: SourceAssessment,
    ) -> bool:
        """Store an assessment only while its exact source request remains current."""

        current_request = self.source_assessment_request()
        if current_request is not None and current_request.key == request.key:
            self._source_assessment_cache = _SourceAssessmentCache(
                key=request.key,
                assessment=assessment,
            )
            return True
        return False

    def source_assessment_issues(
        self,
        issues: tuple[TaskIssue, ...] | list[TaskIssue],
    ) -> tuple[TaskIssue, ...]:
        """Append the current source issue without duplicating an existing task issue."""

        merged = list(issues)
        assessment = self.current_source_assessment()
        issue = assessment.issue if assessment is not None else None
        if issue is not None and not any(existing.code == issue.code for existing in merged):
            merged.insert(0, issue)
        return tuple(merged)


class RecoveryUnlockRequestFields(TypedDict):
    passphrase: str | None
    shard_scan_paths: tuple[Path, ...]
    shard_payload_files: tuple[Path, ...]
    auth_text_file: Path | None
    auth_payloads_file: Path | None


class RecoveryTaskState(SourceAssessableTaskState):
    """Input selections shared by tasks that read and unlock an existing backup."""

    source_paths: list[Path] = Field(default_factory=list)
    config_path: Path | None = None
    passphrase: str | None = None
    recovery_documents: list[Path] = Field(default_factory=list)
    recovery_payload_files: list[Path] = Field(default_factory=list)
    expected_head_doc_hash: str | None = None
    auth_text_file: Path | None = None
    auth_payloads_file: Path | None = None

    def unlock_request_fields(self) -> RecoveryUnlockRequestFields:
        return RecoveryUnlockRequestFields(
            passphrase=self.passphrase,
            shard_scan_paths=tuple(self.recovery_documents),
            shard_payload_files=tuple(self.recovery_payload_files),
            auth_text_file=self.auth_text_file,
            auth_payloads_file=self.auth_payloads_file,
        )

    def validation_with_source_issues(self, issues: list[TaskIssue]) -> TaskValidation:
        return TaskValidation(
            sections=self.sections(), issues=self.source_assessment_issues(issues)
        )

    def sections(self) -> tuple[TaskSection, ...]:
        raise NotImplementedError

    def recovery_read_paths(
        self, *, content_paths: Sequence[Path] = (), trailing_paths: Sequence[Path | None] = ()
    ) -> tuple[Path, ...]:
        return (
            *self.source_paths,
            *content_paths,
            *self.recovery_documents,
            *self.recovery_payload_files,
            *(path for path in trailing_paths if path is not None),
        )


class ContentRecoveryTaskState(RecoveryTaskState):
    """Recovery tasks supporting scanned pages, fallback text, and exported payloads."""

    recovery_text: str | None = None
    recovery_text_file: Path | None = None
    payloads_file: Path | None = None

    @property
    def external_recovery_text_file(self) -> Path | None:
        return self.recovery_text_file if not self.recovery_text else None

    def content_read_paths(
        self,
        *,
        auth_text_file: Path | None,
        auth_payloads_file: Path | None,
        content_paths: Sequence[Path] = (),
    ) -> tuple[Path, ...]:
        return self.recovery_read_paths(
            content_paths=content_paths,
            trailing_paths=(
                self.recovery_text_file,
                self.payloads_file,
                auth_text_file,
                auth_payloads_file,
            ),
        )

    def source_section(self, title: str, source_error: str | None, summary: str) -> TaskSection:
        status = (
            "blocked"
            if source_error is not None
            else "ready"
            if has_recovery_source(self)
            else "missing"
        )
        return TaskSection(
            key="source",
            title=title,
            status=status,
            summary="Pasted recovery text is not valid recovery text."
            if source_error is not None
            else summary,
            action_label="Load backup...",
        )

    def recovery_text_issues(
        self, code: str, *, allow_unsigned: bool = False
    ) -> tuple[TaskIssue, ...]:
        if (
            not self.recovery_text
            or recovery_text_error(self.recovery_text, allow_invalid_auth=allow_unsigned) is None
        ):
            return ()
        return (
            TaskIssue(
                code=code,
                message="Pasted recovery text is not valid recovery text.",
                section="source",
            ),
        )

    def content_source_request(
        self,
        *,
        auth_text_file: Path | None = None,
        auth_payloads_file: Path | None = None,
        allow_unsigned: bool = False,
    ) -> SourceAssessmentRequest | None:
        return recovery_source_request(
            issue_section="source",
            scan_paths=self.source_paths,
            recovery_text=self.recovery_text,
            recovery_text_file=self.recovery_text_file,
            payloads_file=self.payloads_file,
            auth_text_file=auth_text_file,
            auth_payloads_file=auth_payloads_file,
            config_path=self.config_path,
            allow_unsigned=allow_unsigned,
        )


def recovery_source_request(
    *,
    issue_section: str,
    scan_paths: list[Path] | tuple[Path, ...] = (),
    recovery_text: str | None = None,
    recovery_text_file: Path | None = None,
    payloads_file: Path | None = None,
    auth_text_file: Path | None = None,
    auth_payloads_file: Path | None = None,
    config_path: Path | None = None,
    allow_unsigned: bool = False,
) -> SourceAssessmentRequest | None:
    """Describe selected backup documents, payloads, and fallback text."""

    paths = tuple(scan_paths)
    sources: list[tuple[SourceKind, str, str]] = []
    if paths:
        sources.append(("scanned_pages", "Backup documents", _paths_source_summary(paths)))
    if recovery_text:
        sources.append(("recovery_text", "Recovery text", pasted_text_summary(recovery_text)))
    if recovery_text_file is not None:
        sources.append(("recovery_text", "Recovery text", display_path(recovery_text_file)))
    if payloads_file is not None:
        sources.append(("payload_files", "Backup payload file", display_path(payloads_file)))
    if not sources:
        return None
    source_kind, source_label, source_summary = sources[0]
    if len(sources) > 1:
        source_kind = "recovery_inputs"
        source_label = "Backup documents"
        source_summary = "; ".join(source[2] for source in sources)
    return SourceAssessmentRequest(
        source_kind=source_kind,
        source_label=source_label,
        source_summary=source_summary,
        issue_section=issue_section,
        scan_paths=paths,
        recovery_text=recovery_text,
        recovery_text_file=recovery_text_file,
        payloads_file=payloads_file,
        auth_text_file=auth_text_file,
        auth_payloads_file=auth_payloads_file,
        config_path=config_path,
        allow_unsigned=allow_unsigned,
    )


def folder_or_scans_source_request(
    *,
    issue_section: str,
    backup_folder: Path | None,
    scan_paths: list[Path] | tuple[Path, ...],
    config_path: Path | None = None,
    auth_text_file: Path | None = None,
    auth_payloads_file: Path | None = None,
) -> SourceAssessmentRequest | None:
    """Normalize the folder-or-scans source shape used by maintenance tasks."""

    paths = tuple(scan_paths)
    if (backup_folder is not None) == bool(paths):
        return None
    if backup_folder is not None:
        return SourceAssessmentRequest(
            source_kind="backup_folder",
            source_label="Backup folder",
            source_summary=display_path(backup_folder),
            issue_section=issue_section,
            backup_folder=backup_folder,
            auth_text_file=auth_text_file,
            auth_payloads_file=auth_payloads_file,
            config_path=config_path,
        )
    return SourceAssessmentRequest(
        source_kind="scanned_pages",
        source_label="Backup documents",
        source_summary=_paths_source_summary(paths),
        issue_section=issue_section,
        scan_paths=paths,
        auth_text_file=auth_text_file,
        auth_payloads_file=auth_payloads_file,
        config_path=config_path,
    )


def assess_source_request(request: SourceAssessmentRequest) -> SourceAssessment:
    """Inspect source documents through the existing recovery and extension planners."""

    try:
        with recovery_kdf_budget():
            inspection = inspect_recovery(_recovery_request(request))
            return _assessment_from_recovery(request, inspection)
    except WorkflowExecutionError as exc:
        return _failed_assessment(request, code=exc.code, message=exc.message)
    except (OSError, RuntimeError, ValueError) as exc:
        return _failed_assessment(
            request,
            code="SOURCE_ASSESSMENT_FAILED",
            message=str(exc),
        )


def _recovery_request(request: SourceAssessmentRequest) -> RecoveryRequest:
    frames = ()
    if request.recovery_text:
        frames = frames_from_fallback_text(
            request.recovery_text,
            allow_invalid_auth=request.allow_unsigned,
        ).frames
    return RecoveryRequest(
        config_path=request.config_path,
        frames=frames,
        recovery_text_file=request.recovery_text_file,
        payloads_file=request.payloads_file,
        scan_paths=(request.backup_folder,) if request.backup_folder else request.scan_paths,
        auth_text_file=request.auth_text_file,
        auth_payloads_file=request.auth_payloads_file,
        allow_unsigned=request.allow_unsigned,
        quiet=True,
    )


def _assessment_from_recovery(
    request: SourceAssessmentRequest,
    inspection: RecoveryInspection,
) -> SourceAssessment:
    source_frames = inspection.source_frames or (*inspection.main_frames, *inspection.auth_frames)
    document_ids = {
        frame.doc_id for frame in source_frames if frame.frame_type == FrameType.MAIN_DOCUMENT
    }
    document_count = len(document_ids)
    issue = _first_source_issue(request, inspection.blocking_issues)
    root_known = document_count == 1 or inspection.decoded_import_session is not None
    identity = inspection.doc_id.hex() if root_known else ""
    noun = "document" if document_count == 1 else "documents"
    version_summary = f"{document_count} backup {noun} found"
    unlock = inspection.unlock
    auth_count = len(
        {
            frame.doc_id
            for frame in (*source_frames, *inspection.auth_frames)
            if frame.frame_type == FrameType.AUTH
        }
    )
    document_summary = (
        f"{document_count} complete backup {noun}; authentication found for {auth_count}"
    )
    return SourceAssessment(
        source_kind=request.source_kind,
        source_label=request.source_label,
        source_summary=request.source_summary,
        backup_identity=identity,
        version_summary=version_summary,
        issue=issue,
        document_summary=document_summary,
        unlock_summary=_source_unlock_summary(inspection),
        unlock_ready=unlock.satisfied,
        has_updates=document_count > 1,
        document_count=document_count,
        root_doc_hash=inspection.doc_hash.hex() if root_known else "",
    )


def _source_unlock_summary(inspection: RecoveryInspection) -> str:
    unlock = inspection.unlock
    count = unlock.validated_shard_count
    if unlock.mode != "shards":
        return "Enter a passphrase or load recovery sheets to unlock."
    threshold = unlock.required_shard_threshold
    if unlock.satisfied:
        return f"Recovery sheets ready: {count} validated."
    if threshold is not None:
        missing = max(0, threshold - count)
        if missing == 0:
            return "Recovery sheets found; resolve the document error before unlocking."
        noun = "sheet" if missing == 1 else "sheets"
        return f"Recovery sheets: {count} of {threshold} required. Load {missing} more {noun}."
    return "The loaded recovery sheets cannot unlock this backup."


def _first_source_issue(
    request: SourceAssessmentRequest,
    blockers: tuple[dict[str, object], ...],
) -> TaskIssue | None:
    blocker = next(
        (item for item in blockers if _issue_code(item) not in _UNLOCK_ONLY_BLOCKERS), None
    )
    if blocker is None:
        return None
    return TaskIssue(
        code=_issue_code(blocker) or "SOURCE_ASSESSMENT_FAILED",
        message=_issue_message(blocker) or "The selected backup source is not usable.",
        section=request.issue_section,
    )


def _issue_code(issue: dict[str, object]) -> str:
    return str(issue.get("code") or "")


def _issue_message(issue: dict[str, object]) -> str:
    return str(issue.get("message") or "")


def _failed_assessment(
    request: SourceAssessmentRequest,
    *,
    code: str,
    message: str,
) -> SourceAssessment:
    return SourceAssessment(
        source_kind=request.source_kind,
        source_label=request.source_label,
        source_summary=request.source_summary,
        issue=TaskIssue(
            code=code,
            message=message or "The selected backup source could not be assessed.",
            section=request.issue_section,
        ),
    )


def _paths_source_summary(paths: tuple[Path, ...]) -> str:
    first_path = display_path(paths[0])
    if len(paths) == 1:
        return first_path
    return f"{len(paths)} items: {first_path} and {len(paths) - 1} more"


def _path_text(path: Path | None) -> str | None:
    return str(path) if path is not None else None
