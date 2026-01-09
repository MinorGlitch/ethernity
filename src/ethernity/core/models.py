#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SigningSeedMode(str, Enum):
    EMBEDDED = "embedded"
    SHARDED = "sharded"


@dataclass(frozen=True)
class ShardingConfig:
    threshold: int
    shares: int


@dataclass(frozen=True)
class DocumentPlan:
    version: int
    sealed: bool
    signing_seed_mode: SigningSeedMode = SigningSeedMode.EMBEDDED
    sharding: ShardingConfig | None = None
    signing_seed_sharding: ShardingConfig | None = None


@dataclass(frozen=True)
class DocumentMeta:
    version: int
    doc_id: bytes
    sealed: bool = False
    signing_seed_mode: SigningSeedMode = SigningSeedMode.EMBEDDED
    sharding: ShardingConfig | None = None
    signing_seed_sharding: ShardingConfig | None = None

    def doc_id_hex(self) -> str:
        return self.doc_id.hex()

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "doc_id": self.doc_id_hex(),
            "sealed": self.sealed,
            "signing_seed_mode": self.signing_seed_mode.value,
            "sharding": (
                {"threshold": self.sharding.threshold, "shares": self.sharding.shares}
                if self.sharding
                else None
            ),
            "signing_seed_sharding": (
                {
                    "threshold": self.signing_seed_sharding.threshold,
                    "shares": self.signing_seed_sharding.shares,
                }
                if self.signing_seed_sharding
                else None
            ),
        }


@dataclass(frozen=True)
class ShardMeta:
    doc_id: bytes
    shard_id: bytes
    index: int
    threshold: int
    shares: int

    def doc_id_hex(self) -> str:
        return self.doc_id.hex()

    def shard_id_hex(self) -> str:
        return self.shard_id.hex()
