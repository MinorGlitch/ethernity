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

from typing import Final, Literal

DocType = Literal["main", "recovery", "kit", "shard", "signing_key_shard"]

DOC_TYPE_MAIN: Final = "main"
DOC_TYPE_RECOVERY: Final = "recovery"
DOC_TYPE_KIT: Final = "kit"
DOC_TYPE_SHARD: Final = "shard"
DOC_TYPE_SIGNING_KEY_SHARD: Final = "signing_key_shard"

DOC_TYPES: Final[set[str]] = {
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_KIT,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
}
