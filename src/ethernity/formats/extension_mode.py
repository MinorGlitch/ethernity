"""Authenticated update dependencies, shared by writers and readers."""

from enum import StrEnum


class UpdateMode(StrEnum):
    CUMULATIVE = "cumulative"
    INCREMENTAL = "incremental"


def resolve_update_mode(
    locked: UpdateMode | None, requested: UpdateMode | None = None
) -> UpdateMode:
    """Choose once for a new series, or retain an authenticated series' mode."""

    if requested is not None:
        requested = UpdateMode(requested)
    if locked is not None and requested is not None and locked != requested:
        raise ValueError("update mode is fixed for this series; use Rebuild to start another mode")
    return locked or requested or UpdateMode.CUMULATIVE


__all__ = ["UpdateMode", "resolve_update_mode"]
