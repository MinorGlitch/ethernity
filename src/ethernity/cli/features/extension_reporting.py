"""CLI adapter for extension workflow reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ethernity.cli.shared.events import emit_phase, emit_progress
from ethernity.cli.shared.log import warn


@dataclass(frozen=True)
class CliExtensionReporter:
    quiet: bool = False

    def phase(self, *, phase: str, label: str) -> None:
        emit_phase(phase=phase, label=label)

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
        emit_progress(
            phase=phase,
            current=current,
            total=total,
            unit=unit,
            label=label,
            details=dict(details or {}),
        )

    def warning(
        self,
        message: str,
        *,
        code: str = "WARNING",
        details: Mapping[str, object] | None = None,
    ) -> None:
        warn(message, quiet=self.quiet, code=code, details=dict(details or {}))


__all__ = ["CliExtensionReporter"]
