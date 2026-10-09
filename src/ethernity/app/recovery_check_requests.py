"""Map completed task output to read-only recovery checks."""

from __future__ import annotations

import re

from ethernity.app.execution import ReviewedTask
from ethernity.tasks.add_files import AddFilesTaskState
from ethernity.tasks.models import TaskExecutionResult
from ethernity.tasks.recovery_check import GeneratedRecoveryCheckRequest
from ethernity.tasks.recovery_inputs import recovery_text_frames
from ethernity.workflows.shared.requests import RecoveryRequest


def generated_recovery_request(
    reviewed: ReviewedTask,
    result: TaskExecutionResult,
) -> GeneratedRecoveryCheckRequest:
    state = reviewed.state_snapshot
    ancestry = None
    if isinstance(state, AddFilesTaskState):
        ancestry = RecoveryRequest(
            frames=tuple(recovery_text_frames(state.recovery_text, quiet=True) or ()),
            recovery_text_file=state.recovery_text_file if not state.recovery_text else None,
            payloads_file=state.payloads_file,
            scan_paths=tuple(state.source_paths),
            shard_scan_paths=tuple(state.recovery_documents),
            shard_payload_files=tuple(state.recovery_payload_files),
            auth_text_file=state.auth_text_file,
            auth_payloads_file=state.auth_payloads_file,
            quiet=True,
        )
    return GeneratedRecoveryCheckRequest(
        documents=result.recovery_check_paths,
        passphrase=getattr(state, "passphrase", None),
        config_path=state.config_path,
        expected_head_doc_hash=_result_head(result),
        base_request=ancestry,
    )


def _result_head(result: TaskExecutionResult) -> str | None:
    for detail in result.details:
        if detail.key in {"head_doc_hash", "doc_hash"} and isinstance(detail.value, str):
            if re.fullmatch(r"[0-9a-fA-F]{64}", detail.value):
                return detail.value.lower()
    return None
