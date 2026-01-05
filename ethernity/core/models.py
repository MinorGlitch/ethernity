#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

class DocumentMode(str, Enum):
    PASSPHRASE = "passphrase"
    RECIPIENT = "recipient"


class KeyMaterial(str, Enum):
    NONE = "none"
    PASSPHRASE = "passphrase"
    IDENTITY = "identity"


@dataclass(frozen=True)
class ShardingConfig:
    threshold: int
    shares: int


@dataclass(frozen=True)
class DocumentPlan:
    version: int
    mode: DocumentMode
    key_material: KeyMaterial
    sealed: bool
    sharding: ShardingConfig | None = None
    recipients: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentMeta:
    version: int
    doc_id: bytes
    mode: DocumentMode
    key_material: KeyMaterial
    sealed: bool = False
    sharding: ShardingConfig | None = None
    recipients: tuple[str, ...] = ()

    def doc_id_hex(self) -> str:
        return self.doc_id.hex()

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "doc_id": self.doc_id_hex(),
            "mode": self.mode.value,
            "key_material": self.key_material.value,
            "sealed": self.sealed,
            "sharding": (
                {"threshold": self.sharding.threshold, "shares": self.sharding.shares}
                if self.sharding
                else None
            ),
            "recipients": list(self.recipients),
        }


@dataclass(frozen=True)
class ShardMeta:
    doc_id: bytes
    shard_id: bytes
    index: int
    threshold: int
    shares: int
    key_material: KeyMaterial

    def doc_id_hex(self) -> str:
        return self.doc_id.hex()

    def shard_id_hex(self) -> str:
        return self.shard_id.hex()
