from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from ethernity.cli.shared.io.frames import frames_from_fallback_text
from ethernity.encoding.framing import Frame

__all__ = [
    "RecoverySourceMaterial",
    "UnlockMaterial",
    "has_recovery_source",
    "has_unlock_material",
    "recovery_text_error",
    "recovery_text_frames",
]


class RecoverySourceMaterial(Protocol):
    @property
    def source_paths(self) -> Sequence[Path]: ...

    @property
    def recovery_text(self) -> str | None: ...

    @property
    def recovery_text_file(self) -> Path | None: ...

    @property
    def payloads_file(self) -> Path | None: ...


class UnlockMaterial(Protocol):
    @property
    def passphrase(self) -> str | None: ...

    @property
    def recovery_documents(self) -> Sequence[Path]: ...

    @property
    def recovery_payload_files(self) -> Sequence[Path]: ...


def has_unlock_material(material: UnlockMaterial) -> bool:
    return bool(
        material.passphrase or material.recovery_documents or material.recovery_payload_files
    )


def has_recovery_source(material: RecoverySourceMaterial) -> bool:
    return bool(
        material.source_paths
        or material.recovery_text
        or material.recovery_text_file
        or material.payloads_file
    )


def recovery_text_frames(
    value: str | None,
    *,
    allow_invalid_auth: bool = False,
    quiet: bool,
) -> list[Frame] | None:
    if not value:
        return None
    return frames_from_fallback_text(
        value,
        allow_invalid_auth=allow_invalid_auth,
        quiet=quiet,
    )


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
