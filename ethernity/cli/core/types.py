#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InputFile:
    source_path: Path | None
    relative_path: str
    data: bytes
    mtime: int | None


@dataclass(frozen=True)
class BackupResult:
    doc_id: bytes
    qr_path: str
    recovery_path: str
    shard_paths: tuple[str, ...]
    passphrase_used: str | None
    generated_identity: str | None
    generated_recipient: str | None
