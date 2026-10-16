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

"""Adapter-neutral recovery inspection models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ethernity.crypto.signing import AuthPayload
from ethernity.encoding.framing import Frame
from ethernity.extensions.recovery import DecodedImportSession, ImportedRecoveryDocument
from ethernity.workflows.recovery.source_state import RecoverySourceFields
from ethernity.workflows.shared.events import emit_progress


@dataclass(frozen=True)
class RecoveryUnlockStatus:
    """Unlock readiness for recovery inspection."""

    mode: Literal["missing", "passphrase", "shards"]
    passphrase_provided: bool
    validated_shard_count: int
    required_shard_threshold: int | None
    satisfied: bool
    resolved_passphrase: str | None = None
    shard_share_count: int | None = None
    blocking_issues: tuple[dict[str, Any], ...] = ()

    @classmethod
    def unavailable(
        cls,
        mode: Literal["missing", "passphrase", "shards"],
        issues: tuple[dict[str, Any], ...],
        *,
        provided_count: int = 0,
        threshold: int | None = None,
        share_count: int | None = None,
    ) -> RecoveryUnlockStatus:
        return cls(
            mode=mode,
            passphrase_provided=mode == "passphrase",
            validated_shard_count=provided_count,
            required_shard_threshold=threshold,
            satisfied=False,
            shard_share_count=share_count,
            blocking_issues=issues,
        )


@dataclass(frozen=True)
class RecoveryDocumentState:
    """Authenticated document and carrier selections shared by plans and inspections."""

    source: RecoverySourceFields
    ciphertext: bytes
    doc_id: bytes
    doc_hash: bytes
    auth_payload: AuthPayload | None
    auth_status: str
    allow_unsigned: bool

    def emit_plan_progress(self, *, details: dict[str, Any] | None = None) -> None:
        emit_progress(
            phase="plan",
            current=1,
            total=1,
            unit="step",
            details={
                "main_frame_count": len(self.main_frames),
                "auth_frame_count": len(self.auth_frames),
                "shard_frame_count": len(self.shard_frames),
                **(details or {}),
            },
        )

    @property
    def input_label(self) -> str | None:
        return self.source.input_label

    @property
    def input_detail(self) -> str | None:
        return self.source.input_detail

    @property
    def main_frames(self) -> tuple[Frame, ...]:
        return self.source.main_frames

    @property
    def auth_frames(self) -> tuple[Frame, ...]:
        return self.source.auth_frames

    @property
    def shard_frames(self) -> tuple[Frame, ...]:
        return self.source.shard_frames

    @property
    def shard_fallback_files(self) -> tuple[str, ...]:
        return self.source.shard_fallback_files

    @property
    def shard_payloads_file(self) -> tuple[str, ...]:
        return self.source.shard_payloads_file

    @property
    def shard_scan(self) -> tuple[str, ...]:
        return self.source.shard_scan


@dataclass(frozen=True)
class RecoveryInspection(RecoveryDocumentState):
    """Best-effort recovery inspection state assembled from decoded frames."""

    unlock: RecoveryUnlockStatus
    blocking_issues: tuple[dict[str, Any], ...]
    source_frames: tuple[Frame, ...] = ()
    source_extra_auth_frames: tuple[Frame, ...] = ()
    decoded_import_session: DecodedImportSession | None = None


@dataclass(frozen=True)
class RecoveryRootSelection:
    """Frames and unlock state to use after resolving a multi-document root."""

    frames: tuple[Frame, ...]
    extra_auth_frames: tuple[Frame, ...]
    shard_frames: tuple[Frame, ...]
    passphrase: str | None
    shard_unlock: RecoveryUnlockStatus | None = None
    decoded_import_session: DecodedImportSession | None = None


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
    "RecoveryRootSelection",
    "RecoveryUnlockStatus",
]
