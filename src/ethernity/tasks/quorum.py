from __future__ import annotations

from ethernity.crypto.sharding import MAX_SHARES

MAX_SHARDS = MAX_SHARES


def validate_required_shard_count(value: int, *, label: str) -> int:
    if value < 1:
        raise ValueError(f"{label} must be at least 1")
    if value > MAX_SHARDS:
        raise ValueError(f"{label} must be at most {MAX_SHARDS}")
    return value


def validate_optional_shard_count(
    value: int | None,
    *,
    label: str,
    allow_zero: bool = False,
) -> int | None:
    if value is None:
        return None
    if allow_zero and value == 0:
        return value
    return validate_required_shard_count(value, label=label)
