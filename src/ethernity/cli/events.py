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

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class CommandError(ValueError):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

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


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_safe_value(item) for item in value]
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    return str(value)


def emit_event(event_type: str, **payload: Any) -> None:
    sink = active_event_sink()
    if sink is None:
        return
    sink.emit(event_type, **{key: _safe_value(value) for key, value in payload.items()})


def emit_started(*, command: str, args: dict[str, Any], schema_version: int) -> None:
    emit_event("started", command=command, schema_version=schema_version, args=args)


def emit_phase(*, phase: str, label: str) -> None:
    emit_event("phase", id=phase, label=label)


def emit_warning(*, code: str, message: str, details: dict[str, Any] | None = None) -> None:
    emit_event("warning", code=code, message=message, details=details or {})


def emit_progress(
    *,
    phase: str,
    current: int,
    total: int | None = None,
    unit: str | None = None,
    label: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    emit_event(
        "progress",
        phase=phase,
        current=current,
        total=total,
        unit=unit,
        label=label,
        details=details or {},
    )


def emit_artifact(*, kind: str, path: str, details: dict[str, Any] | None = None) -> None:
    emit_event("artifact", kind=kind, path=path, details=details or {})


def emit_result(**payload: Any) -> None:
    emit_event("result", ok=True, **payload)


def emit_error(*, code: str, message: str, details: dict[str, Any] | None = None) -> None:
    emit_event("error", ok=False, code=code, message=message, details=details or {})


__all__ = [
    "CommandError",
    "EventSink",
    "active_event_sink",
    "emit_artifact",
    "emit_error",
    "emit_event",
    "emit_phase",
    "emit_progress",
    "emit_result",
    "emit_started",
    "emit_warning",
    "event_session",
]
