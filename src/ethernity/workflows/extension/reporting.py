"""Adapter-neutral reporting port for extension execution."""

from __future__ import annotations

from typing import Mapping, Protocol


class ExtensionReporter(Protocol):
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
        code: str = "WARNING",
        details: Mapping[str, object] | None = None,
    ) -> None: ...


class NullExtensionReporter:
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
        code: str = "WARNING",
        details: Mapping[str, object] | None = None,
    ) -> None:
        pass


NULL_EXTENSION_REPORTER = NullExtensionReporter()

__all__ = ["ExtensionReporter", "NULL_EXTENSION_REPORTER", "NullExtensionReporter"]
