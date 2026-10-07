"""Validate shard quorums supplied to document-generation workflows."""

from __future__ import annotations

from ethernity.crypto.sharding import MAX_SHARES

__all__ = ["validate_quorum", "validate_quorum_pair"]


def validate_quorum(threshold: int, count: int, *, label: str = "shard") -> None:
    """Require a quorum representable by the shard format."""

    if threshold < 1:
        raise ValueError(f"{label} threshold must be >= 1")
    if threshold > MAX_SHARES:
        raise ValueError(f"{label} threshold must be <= {MAX_SHARES}")
    if count < threshold:
        raise ValueError(f"{label} count must be >= {label} threshold")
    if count > MAX_SHARES:
        raise ValueError(f"{label} count must be <= {MAX_SHARES}")


def validate_quorum_pair(
    threshold: int | None,
    count: int | None,
    *,
    pair_label: str,
    label: str = "shard",
    required: bool = False,
) -> None:
    """Check paired request values before validating their numeric bounds."""

    if threshold is None and count is None:
        if required:
            raise ValueError(f"{pair_label} are required")
        return
    if threshold is None or count is None:
        raise ValueError(f"both {pair_label} are required")
    validate_quorum(threshold, count, label=label)
