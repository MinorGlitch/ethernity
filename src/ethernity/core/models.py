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
from enum import StrEnum


class SigningSeedMode(StrEnum):
    EMBEDDED = "embedded"
    SHARDED = "sharded"

    def __str__(self) -> str:
        return f"{type(self).__name__}.{self.name}"


@dataclass(frozen=True)
class ShardingConfig:
    threshold: int
    shares: int


@dataclass(frozen=True)
class DocumentPlan:
    sealed: bool
    signing_seed_mode: SigningSeedMode = SigningSeedMode.EMBEDDED
    sharding: ShardingConfig | None = None
    signing_seed_sharding: ShardingConfig | None = None
