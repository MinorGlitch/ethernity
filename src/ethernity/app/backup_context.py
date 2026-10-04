from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ethernity.app.app_types import ActiveTask, UnlockTaskState
from ethernity.tasks.rebuild import RebuildTaskState
from ethernity.tasks.source_assessment import SourceAssessment, SourceAssessmentRequest

BACKUP_TASKS: tuple[ActiveTask, ...] = (
    "restore",
    "add_files",
    "rebuild",
    "replace_recovery_docs",
)
MAINTENANCE_TASKS: tuple[ActiveTask, ...] = (
    "add_files",
    "rebuild",
    "replace_recovery_docs",
)


@dataclass(frozen=True, slots=True)
class LoadedBackupContext:
    """Decoded backup selection shared by untouched maintenance drafts."""

    source_task: ActiveTask
    request: SourceAssessmentRequest
    assessment: SourceAssessment
    passphrase: str | None
    recovery_documents: tuple[Path, ...]
    recovery_payload_files: tuple[Path, ...]
    expected_head_doc_hash: str | None
    allow_stale_head: bool

    @classmethod
    def from_state(
        cls,
        task: ActiveTask,
        state: UnlockTaskState,
    ) -> LoadedBackupContext | None:
        request = state.source_assessment_request()
        assessment = state.current_source_assessment()
        if request is None or assessment is None or assessment.issue is not None:
            return None
        if not (assessment.backup_identity or assessment.version_summary):
            return None
        return cls(
            source_task=task,
            request=request,
            assessment=assessment,
            passphrase=state.passphrase,
            recovery_documents=tuple(state.recovery_documents),
            recovery_payload_files=tuple(state.recovery_payload_files),
            expected_head_doc_hash=state.expected_head_doc_hash,
            allow_stale_head=getattr(state, "allow_stale_head", False),
        )

    @property
    def summary(self) -> str:
        identity = self.assessment.backup_identity
        label = f"Backup {identity[:8]}" if identity else "Documents loaded"
        count = self.assessment.document_count
        if count:
            noun = "doc" if count == 1 else "docs"
            return f"{label} / {count} {noun}"
        return label

    def apply_to(self, state: UnlockTaskState) -> bool:
        """Reuse source choices; the caller must first establish that the draft is pristine."""

        request = self.request
        if isinstance(state, RebuildTaskState):
            if request.recovery_text or request.recovery_text_file or request.payloads_file:
                return False
            state.backup_folder = request.backup_folder
            state.source_paths = list(request.scan_paths)
        else:
            state.source_paths = (
                [request.backup_folder]
                if request.backup_folder is not None
                else list(request.scan_paths)
            )
            state.recovery_text = request.recovery_text
            state.recovery_text_file = request.recovery_text_file
            state.payloads_file = request.payloads_file
        for field in ("auth_text_file", "auth_payloads_file"):
            if field in type(state).model_fields:
                setattr(state, field, getattr(request, field))
        state.config_path = request.config_path
        state.passphrase = self.passphrase
        state.recovery_documents = list(self.recovery_documents)
        state.recovery_payload_files = list(self.recovery_payload_files)
        state.expected_head_doc_hash = self.expected_head_doc_hash
        if "allow_stale_head" in type(state).model_fields:
            setattr(state, "allow_stale_head", self.allow_stale_head)
        if "allow_unsigned" in type(state).model_fields:
            setattr(state, "allow_unsigned", request.allow_unsigned)
        target_request = state.source_assessment_request()
        if target_request is not None and target_request.key == request.key:
            state.store_source_assessment(target_request, self.assessment)
        return True
