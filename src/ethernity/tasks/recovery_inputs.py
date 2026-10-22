from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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
    "ParsedRecoveryText",
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


@dataclass(frozen=True)
class ParsedRecoveryText:
    text: str | None
    allow_unsigned: bool
    frames: tuple[Frame, ...] = ()
    error: str | None = None

    @classmethod
    def parse(cls, text: str | None, *, allow_unsigned: bool = False) -> ParsedRecoveryText:
        if not text:
            return cls(text, allow_unsigned)
        try:
            result = frames_from_fallback_text(text, allow_invalid_auth=allow_unsigned)
        except ValueError as exc:
            return cls(text, allow_unsigned, error=str(exc))
        return cls(text, allow_unsigned, frames=tuple(result.frames))

    def require_frames(self) -> tuple[Frame, ...]:
        if self.error is not None:
            raise ValueError(self.error)
        return self.frames
