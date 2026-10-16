"""Recovery-sheet options used by backup and replacement generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, kw_only=True)
class RecoveryQuorumOptions:
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None


@dataclass(frozen=True, kw_only=True)
class BackupRecoveryOptions(RecoveryQuorumOptions):
    signing_key_mode: Literal["embedded", "sharded"] | None = None


@dataclass(frozen=True, kw_only=True)
class ReplacementRecoveryOptions(RecoveryQuorumOptions):
    passphrase_replacement_count: int | None = None
    signing_key_replacement_count: int | None = None
    create_passphrase_shards: bool = True
    create_signing_key_shards: bool = True
