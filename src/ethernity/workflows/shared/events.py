#!/usr/bin/env python3
# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol

from ethernity.core.failures import FailureStage
from ethernity.workflows.shared.execution_control import begin_final_write, cancellation_point


@dataclass
class CommandError(ValueError):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    stage: FailureStage | None = None

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)


class EventSink(Protocol):
    def emit(self, event_type: str, **payload: Any) -> None: ...


_ACTIVE_SINK: ContextVar[EventSink | None] = ContextVar("event_sink", default=None)


def active_event_sink() -> EventSink | None:
    return _ACTIVE_SINK.get()


@contextmanager
def event_session(sink: EventSink | None) -> Generator[EventSink | None, None, None]:
    if sink is None:
        yield active_event_sink()
        return
    token = _ACTIVE_SINK.set(sink)
    try:
        yield sink
    finally:
        _ACTIVE_SINK.reset(token)


def emit_event(event_type: str, **payload: Any) -> None:
    sink = active_event_sink()
    if sink is None:
        return
    sink.emit(event_type, **payload)


def emit_phase(*, phase: str, label: str) -> None:
    cancellation_point()
    emit_event("phase", id=phase, label=label)


def emit_finalizing() -> None:
    """Announce the point after which cancellation can no longer undo the run."""
    begin_final_write()
    emit_phase(phase="save", label="Saving output")


def emit_warning(*, code: str, message: str, details: dict[str, Any] | None = None) -> None:
    emit_event("warning", code=code, message=message, details=details or {})


def emit_progress(
    *,
    phase: str,
    current: int,
    total: int | None = None,
    unit: str | None = None,
    label: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    cancellation_point()
    emit_event(
        "progress",
        phase=phase,
        current=current,
        total=total,
        unit=unit,
        label=label,
        details=details or {},
    )


def emit_written_file(*, kind: str, path: str, details: dict[str, Any] | None = None) -> None:
    emit_event("file", kind=kind, path=path, details=details or {})


def report_render_page(doc_type: str, current: int, total: int) -> None:
    """Adapt the renderer's page callback to workflow progress without UI dependencies."""
    emit_progress(
        phase="render",
        current=current,
        total=total,
        unit="pages",
        details={"document_type": doc_type},
    )


__all__ = [
    "CommandError",
    "EventSink",
    "active_event_sink",
    "emit_written_file",
    "emit_event",
    "emit_phase",
    "emit_finalizing",
    "emit_progress",
    "emit_warning",
    "event_session",
    "report_render_page",
]
