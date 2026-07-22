from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, PrivateAttr

from ethernity.cli.features.recover.planning import (
    RecoveryInspection,
    inspect_from_args as inspect_recovery_from_args,
)
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.io.frames import frames_from_fallback_text
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import RecoverArgs
from ethernity.crypto.age_policy import recovery_kdf_budget
from ethernity.encoding.framing import FrameType
from ethernity.tasks.file_summary import display_path
from ethernity.tasks.models import TaskIssue, TaskSectionStatus
from ethernity.tasks.presentation.recovery import pasted_text_summary
from ethernity.workflows.extension.errors import ExtensionIssue, ExtensionWorkflowError
from ethernity.workflows.extension.planning import (
    ExtendInspection,
    inspect_from_args as inspect_extend_from_args,
)
from ethernity.workflows.extension.request import ExtensionRequest

SourceKind = Literal["backup_folder", "scanned_pages", "recovery_text", "payload_files"]

_UNLOCK_ONLY_BLOCKERS = frozenset(
    {
        api_codes.PASSPHRASE_REQUIRED,
        api_codes.PASSPHRASE_SHARDS_UNDER_QUORUM,
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
    material_summary: str
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
    resource_intensive_compatibility_recovery: bool = False

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
            "resource_intensive_compatibility_recovery": (
                self.resource_intensive_compatibility_recovery
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceAssessment:
    """Facts and any source-local failure discovered without writing or decrypting data."""

    source_kind: SourceKind
    source_label: str
    material_summary: str
    backup_identity: str = ""
    version_summary: str = ""
    issue: TaskIssue | None = None


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
    resource_intensive_compatibility_recovery: bool = False,
) -> SourceAssessmentRequest | None:
    """Normalize the mutually exclusive recovery source shapes used by guided tasks."""

    paths = tuple(scan_paths)
    selected = sum(
        (
            bool(paths),
            bool(recovery_text or recovery_text_file is not None),
            payloads_file is not None,
        )
    )
    if selected != 1:
        return None
    if paths:
        return SourceAssessmentRequest(
            source_kind="scanned_pages",
            source_label="Scanned pages",
            material_summary=_paths_material_summary(paths),
            issue_section=issue_section,
            scan_paths=paths,
            auth_text_file=auth_text_file,
            auth_payloads_file=auth_payloads_file,
            config_path=config_path,
            allow_unsigned=allow_unsigned,
            resource_intensive_compatibility_recovery=(resource_intensive_compatibility_recovery),
        )
    if recovery_text or recovery_text_file is not None:
        material_summary = (
            pasted_text_summary(recovery_text)
            if recovery_text
            else display_path(recovery_text_file or "")
        )
        return SourceAssessmentRequest(
            source_kind="recovery_text",
            source_label="Recovery text",
            material_summary=material_summary,
            issue_section=issue_section,
            recovery_text=recovery_text,
            recovery_text_file=recovery_text_file,
            auth_text_file=auth_text_file,
            auth_payloads_file=auth_payloads_file,
            config_path=config_path,
            allow_unsigned=allow_unsigned,
            resource_intensive_compatibility_recovery=(resource_intensive_compatibility_recovery),
        )
    return SourceAssessmentRequest(
        source_kind="payload_files",
        source_label="Backup payload file",
        material_summary=display_path(payloads_file or ""),
        issue_section=issue_section,
        payloads_file=payloads_file,
        auth_text_file=auth_text_file,
        auth_payloads_file=auth_payloads_file,
        config_path=config_path,
        allow_unsigned=allow_unsigned,
        resource_intensive_compatibility_recovery=resource_intensive_compatibility_recovery,
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
            material_summary=display_path(backup_folder),
            issue_section=issue_section,
            backup_folder=backup_folder,
            config_path=config_path,
        )
    return SourceAssessmentRequest(
        source_kind="scanned_pages",
        source_label="Scanned pages",
        material_summary=_paths_material_summary(paths),
        issue_section=issue_section,
        scan_paths=paths,
        auth_text_file=auth_text_file,
        auth_payloads_file=auth_payloads_file,
        config_path=config_path,
    )


def assess_source_request(request: SourceAssessmentRequest) -> SourceAssessment:
    """Inspect source material through the existing recovery and extension planners."""

    try:
        with recovery_kdf_budget(
            allow_resource_intensive_compatibility=(
                request.resource_intensive_compatibility_recovery
            )
        ):
            if request.source_kind == "backup_folder":
                inspection = inspect_extend_from_args(
                    ExtensionRequest(
                        config_path=_path_text(request.config_path),
                        publish_root=_path_text(request.backup_folder),
                        quiet=True,
                    )
                )
                return _assessment_from_extend(request, inspection)
            inspection = inspect_recovery_from_args(_recover_args(request))
            return _assessment_from_recovery(request, inspection)
    except (ApiCommandError, ExtensionWorkflowError) as exc:
        return _failed_assessment(request, code=exc.code, message=exc.message)
    except (OSError, RuntimeError, ValueError) as exc:
        return _failed_assessment(
            request,
            code="SOURCE_ASSESSMENT_FAILED",
            message=str(exc),
        )


def _recover_args(request: SourceAssessmentRequest) -> RecoverArgs:
    frames = None
    if request.recovery_text:
        frames = frames_from_fallback_text(
            request.recovery_text,
            allow_invalid_auth=request.allow_unsigned,
            quiet=True,
        )
    return RecoverArgs(
        config=_path_text(request.config_path),
        frames=frames,
        fallback_file=(
            _path_text(request.recovery_text_file)
            if request.recovery_text_file is not None and not request.recovery_text
            else None
        ),
        payloads_file=_path_text(request.payloads_file),
        scan=[str(path) for path in request.scan_paths] or None,
        auth_fallback_file=_path_text(request.auth_text_file),
        auth_payloads_file=_path_text(request.auth_payloads_file),
        allow_unsigned=request.allow_unsigned,
        resource_intensive_compatibility_recovery=(
            request.resource_intensive_compatibility_recovery
        ),
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
    identity = inspection.doc_id.hex() if document_count <= 1 else ""
    noun = "document" if document_count == 1 else "documents"
    version_summary = f"{document_count} backup {noun} found"
    return SourceAssessment(
        source_kind=request.source_kind,
        source_label=request.source_label,
        material_summary=request.material_summary,
        backup_identity=identity,
        version_summary=version_summary,
        issue=issue,
    )


def _assessment_from_extend(
    request: SourceAssessmentRequest,
    inspection: ExtendInspection,
) -> SourceAssessment:
    issue = _first_source_issue(request, inspection.blocking_issues)
    if inspection.validated_head_index is not None:
        version_summary = (
            "Initial backup"
            if inspection.validated_head_index == 0
            else f"Update {inspection.validated_head_index} validated"
        )
    elif inspection.discovered_extension_dirs:
        update_count = len(inspection.discovered_extension_dirs)
        noun = "update" if update_count == 1 else "updates"
        version_summary = f"{update_count} {noun} found; unlock to validate the newest version"
    else:
        version_summary = "Initial backup only"
    return SourceAssessment(
        source_kind=request.source_kind,
        source_label=request.source_label,
        material_summary=request.material_summary,
        backup_identity=inspection.root_doc_id or inspection.doc_id or "",
        version_summary=version_summary,
        issue=issue,
    )


def _first_source_issue(
    request: SourceAssessmentRequest,
    blockers: tuple[dict[str, object], ...] | tuple[ExtensionIssue, ...],
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


def _issue_code(issue: dict[str, object] | ExtensionIssue) -> str:
    return issue.code if isinstance(issue, ExtensionIssue) else str(issue.get("code") or "")


def _issue_message(issue: dict[str, object] | ExtensionIssue) -> str:
    return issue.message if isinstance(issue, ExtensionIssue) else str(issue.get("message") or "")


def _failed_assessment(
    request: SourceAssessmentRequest,
    *,
    code: str,
    message: str,
) -> SourceAssessment:
    return SourceAssessment(
        source_kind=request.source_kind,
        source_label=request.source_label,
        material_summary=request.material_summary,
        issue=TaskIssue(
            code=code,
            message=message or "The selected backup source could not be assessed.",
            section=request.issue_section,
        ),
    )


def _paths_material_summary(paths: tuple[Path, ...]) -> str:
    first_path = display_path(paths[0])
    if len(paths) == 1:
        return first_path
    return f"{len(paths)} items: {first_path} and {len(paths) - 1} more"


def _path_text(path: Path | None) -> str | None:
    return str(path) if path is not None else None
