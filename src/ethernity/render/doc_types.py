#!/usr/bin/env python3
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
