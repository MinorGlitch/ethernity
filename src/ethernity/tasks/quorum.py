from __future__ import annotations

from functools import partial
from typing import Annotated

from pydantic import AfterValidator

from ethernity.crypto.sharding import MAX_SHARES


def validate_required_shard_count(value: int, *, label: str) -> int:
    if value < 1:
        raise ValueError(f"{label} must be at least 1")
    if value > MAX_SHARES:
        raise ValueError(f"{label} must be at most {MAX_SHARES}")
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


RecoveryDocumentCount = Annotated[
    int, AfterValidator(partial(validate_required_shard_count, label="recovery document count"))
]
OptionalSigningDocumentCount = Annotated[
    int | None,
    AfterValidator(
        partial(validate_optional_shard_count, label="signing key recovery document count")
    ),
]
