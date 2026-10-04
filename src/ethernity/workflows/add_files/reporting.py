"""Adapter-neutral reporting port for Add Files execution."""

from __future__ import annotations

from typing import Mapping, Protocol

from ethernity.workflows.shared import api_codes


class AddFilesReporter(Protocol):
    def phase(self, *, phase: str, label: str) -> None: ...

    def progress(
        self,
        *,
        phase: str,
        current: int,
        total: int | None = None,
        unit: str | None = None,
        label: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None: ...

    def warning(
        self,
        message: str,
        *,
        code: str = api_codes.WARNING,
        details: Mapping[str, object] | None = None,
    ) -> None: ...


class NullAddFilesReporter:
    """Default reporter for adapters that do not expose progress or warnings."""

    def phase(self, *, phase: str, label: str) -> None:
        pass

    def progress(
        self,
        *,
        phase: str,
        current: int,
        total: int | None = None,
        unit: str | None = None,
        label: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        pass

    def warning(
        self,
        message: str,
        *,
        code: str = api_codes.WARNING,
        details: Mapping[str, object] | None = None,
    ) -> None:
        pass


NULL_ADD_FILES_REPORTER = NullAddFilesReporter()

__all__ = ["AddFilesReporter", "NULL_ADD_FILES_REPORTER", "NullAddFilesReporter"]
