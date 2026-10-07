"""Normalize common source selections from scriptable recovery commands."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict


class RecoverySourceFields(TypedDict):
    source_paths: list[Path]
    recovery_text_file: Path | None
    payloads_file: Path | None
    auth_text_file: Path | None
    auth_payloads_file: Path | None


def recovery_source_fields(
    source_paths: tuple[Path, ...],
    recovery_text: Path | None,
    payloads_file: Path | None,
    auth_text_file: Path | None,
    auth_payloads_file: Path | None,
) -> RecoverySourceFields:
    return RecoverySourceFields(
        source_paths=list(source_paths),
        recovery_text_file=recovery_text,
        payloads_file=payloads_file,
        auth_text_file=auth_text_file,
        auth_payloads_file=auth_payloads_file,
    )
