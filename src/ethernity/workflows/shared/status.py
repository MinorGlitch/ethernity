"""Adapter-neutral status context used by workflow implementations."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager


@contextmanager
def plain_status(
    message: str,
    *,
    quiet: bool = False,
    console: object | None = None,
) -> Generator[None, None, None]:
    """Run a workflow phase without owning terminal presentation."""

    _ = message, quiet, console
    yield None


__all__ = ["plain_status"]
