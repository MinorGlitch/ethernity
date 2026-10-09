"""Preserve failure provenance across workflow and worker boundaries."""

from __future__ import annotations

from collections.abc import Mapping

from ethernity.core.failures import FailureInfo, FailureStage
from ethernity.workflows.shared import issue_codes

_CODE_STAGES = {
    **dict.fromkeys(
        (
            issue_codes.AUTH_REQUIRED,
            issue_codes.AUTH_DOC_HASH_MISMATCH,
            issue_codes.AUTH_SIGNATURE_INVALID,
            issue_codes.AUTH_PAYLOAD_MISSING,
            issue_codes.AUTH_PAYLOAD_MULTIPLE,
            issue_codes.AUTH_PAYLOAD_DOC_ID_MISMATCH,
            issue_codes.AUTH_PAYLOAD_FRAME_INVALID,
            issue_codes.AUTH_PAYLOAD_INVALID,
            issue_codes.AUTH_FALLBACK_INVALID,
            issue_codes.ROOT_SIGNING_KEY_MISMATCH,
            issue_codes.SIGNING_KEY_SHARDS_REQUIRED,
        ),
        FailureStage.AUTHENTICATION,
    ),
    **dict.fromkeys(
        (
            "PASSPHRASE_AUTH_FAILED",
            "RECOVERY_RESOURCE_LIMIT",
            issue_codes.PASSPHRASE_REQUIRED,
            issue_codes.PASSPHRASE_SHARDS_UNDER_QUORUM,
            issue_codes.PASSPHRASE_SHARDS_INVALID,
        ),
        FailureStage.UNLOCK,
    ),
    issue_codes.RECOVERY_HEAD_UNTRUSTED: FailureStage.SELECTION,
    issue_codes.INPUT_REQUIRED: FailureStage.INPUT,
    issue_codes.ADD_FILES_INPUT_REQUIRED: FailureStage.INPUT,
    issue_codes.OUTPUT_REQUIRED: FailureStage.OUTPUT,
    issue_codes.ADD_FILES_RECOVERY_OUTPUT_EXISTS: FailureStage.OUTPUT,
    issue_codes.EXTENSION_PUBLISH_TARGET_INVALID: FailureStage.OUTPUT,
    issue_codes.ADD_FILES_RENDER_OPTIONS_INVALID: FailureStage.LAYOUT,
}

_PHASE_STAGES = {
    **{stage.value: stage for stage in FailureStage},
    "scan": FailureStage.SOURCE,
    "auth": FailureStage.AUTHENTICATION,
    "decrypt": FailureStage.UNLOCK,
    "decode": FailureStage.SOURCE,
    "file_tree": FailureStage.INPUT,
    "render": FailureStage.LAYOUT,
    "verify": FailureStage.LAYOUT,
    "validate": FailureStage.LAYOUT,
    "encrypt": FailureStage.UNLOCK,
    "write": FailureStage.OUTPUT,
    "save": FailureStage.OUTPUT,
    "publish": FailureStage.OUTPUT,
    "publish_target": FailureStage.OUTPUT,
    "generate": FailureStage.RECOVERY,
    "shard": FailureStage.RECOVERY,
}


def failure_from_exception(error: BaseException, *, phase: str | None = None) -> FailureInfo:
    """Read structured errors, retaining specific causes through generic wrappers."""

    code: str | None = None
    stage: FailureStage | None = None
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        current_code = getattr(current, "code", None)
        if isinstance(current_code, str) and (code is None or code == issue_codes.RUNTIME_ERROR):
            code = current_code
        details = getattr(current, "details", None)
        explicit_stage = getattr(current, "stage", None)
        if explicit_stage is None and isinstance(details, Mapping):
            explicit_stage = details.get("stage")
        if stage is None and isinstance(explicit_stage, str):
            stage = _PHASE_STAGES.get(explicit_stage)
        if stage is None and isinstance(current_code, str):
            stage = _CODE_STAGES.get(current_code)
        current = current.__cause__
    return FailureInfo(
        code=code or issue_codes.RUNTIME_ERROR,
        stage=stage or _PHASE_STAGES.get(phase or ""),
    )
