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
