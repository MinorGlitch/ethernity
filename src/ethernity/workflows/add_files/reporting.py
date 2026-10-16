"""Adapter-neutral reporting port for Add Files execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ethernity.workflows.shared import events, issue_codes


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
        code: str = issue_codes.WARNING,
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
        code: str = issue_codes.WARNING,
        details: Mapping[str, object] | None = None,
    ) -> None:
        pass


NULL_ADD_FILES_REPORTER = NullAddFilesReporter()


class EventAddFilesReporter:
    """Forward update progress through the same event stream as other workflows."""

    phase = staticmethod(events.emit_phase)
    progress = staticmethod(events.emit_progress)

    def warning(
        self,
        message: str,
        *,
        code: str = issue_codes.WARNING,
        details: Mapping[str, object] | None = None,
    ) -> None:
        events.emit_warning(code=code, message=message, details=dict(details or {}))


EVENT_ADD_FILES_REPORTER = EventAddFilesReporter()


__all__ = [
    "AddFilesReporter",
    "EventAddFilesReporter",
    "EVENT_ADD_FILES_REPORTER",
    "NULL_ADD_FILES_REPORTER",
    "NullAddFilesReporter",
]
