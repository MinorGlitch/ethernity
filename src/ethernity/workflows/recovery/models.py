#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Adapter-neutral recovery inspection contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ethernity.crypto.signing import AuthPayload
from ethernity.encoding.framing import Frame
from ethernity.extensions.recovery import DecodedImportSession, ImportedRecoveryDocument


@dataclass(frozen=True)
class RecoveryUnlockStatus:
    """Unlock readiness for structured recovery inspection flows."""

    mode: Literal["missing", "passphrase", "shards"]
    passphrase_provided: bool
    validated_shard_count: int
    required_shard_threshold: int | None
    satisfied: bool
    resolved_passphrase: str | None = None
    shard_share_count: int | None = None
    blocking_issues: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RecoveryInspection:
    """Best-effort recovery inspection state assembled from decoded frames."""

    ciphertext: bytes
    doc_id: bytes
    doc_hash: bytes
    auth_payload: AuthPayload | None
    auth_status: str
    allow_unsigned: bool
    input_label: str | None
    input_detail: str | None
    main_frames: tuple[Frame, ...]
    auth_frames: tuple[Frame, ...]
    shard_frames: tuple[Frame, ...]
    shard_fallback_files: tuple[str, ...]
    shard_payloads_file: tuple[str, ...]
    shard_scan: tuple[str, ...]
    unlock: RecoveryUnlockStatus
    blocking_issues: tuple[dict[str, Any], ...]
    source_frames: tuple[Frame, ...] = ()
    source_extra_auth_frames: tuple[Frame, ...] = ()


@dataclass(frozen=True)
class PassphraseShardRootSelection:
    """Root selection proven by passphrase shards bound to one imported document."""

    root_document: ImportedRecoveryDocument
    target_document: ImportedRecoveryDocument
    target_shard_frames: tuple[Frame, ...]
    unlock: RecoveryUnlockStatus
    decoded_import_session: DecodedImportSession | None = None


__all__ = [
    "PassphraseShardRootSelection",
    "RecoveryInspection",
    "RecoveryUnlockStatus",
]
