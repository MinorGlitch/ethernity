from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ethernity.encoding.framing import Frame
from ethernity.workflows.recovery.frame_inputs import frames_from_fallback_text

__all__ = [
    "RecoverySourceInputs",
    "UnlockInputs",
    "has_recovery_source",
    "has_unlock_inputs",
    "detected_unlock_summary",
    "recovery_text_error",
    "recovery_text_frames",
]


class RecoverySourceInputs(Protocol):
    @property
    def source_paths(self) -> Sequence[Path]: ...

    @property
    def recovery_text(self) -> str | None: ...

    @property
    def recovery_text_file(self) -> Path | None: ...

    @property
    def payloads_file(self) -> Path | None: ...


class UnlockInputs(Protocol):
    @property
    def passphrase(self) -> str | None: ...

    @property
    def recovery_documents(self) -> Sequence[Path]: ...

    @property
    def recovery_payload_files(self) -> Sequence[Path]: ...


class _DetectedUnlock(Protocol):
    @property
    def unlock_ready(self) -> bool: ...

    @property
    def unlock_summary(self) -> str: ...


@runtime_checkable
class _AssessedUnlockInputs(Protocol):
    def current_source_assessment(self) -> _DetectedUnlock | None: ...


def detected_unlock_summary(inputs: UnlockInputs) -> str | None:
    """Describe validated sheets decoded from the current source collection."""

    if isinstance(inputs, _AssessedUnlockInputs):
        assessment = inputs.current_source_assessment()
        if assessment is not None and assessment.unlock_ready:
            return assessment.unlock_summary
    return None


def has_unlock_inputs(inputs: UnlockInputs) -> bool:
    return bool(
        inputs.passphrase
        or inputs.recovery_documents
        or inputs.recovery_payload_files
        or detected_unlock_summary(inputs)
    )


def has_recovery_source(inputs: RecoverySourceInputs) -> bool:
    return bool(
        inputs.source_paths
        or inputs.recovery_text
        or inputs.recovery_text_file
        or inputs.payloads_file
    )


def recovery_text_frames(
    value: str | None,
    *,
    allow_invalid_auth: bool = False,
    quiet: bool,
) -> list[Frame] | None:
    _ = quiet
    if not value:
        return None
    result = frames_from_fallback_text(
        value,
        allow_invalid_auth=allow_invalid_auth,
    )
    return list(result.frames)


def recovery_text_error(
    value: str | None,
    *,
    allow_invalid_auth: bool = False,
) -> str | None:
    try:
        recovery_text_frames(value, allow_invalid_auth=allow_invalid_auth, quiet=True)
    except ValueError as exc:
        return str(exc)
    return None
