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

import json
import sys
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TextIO

from . import api_codes
from .events import (
    CommandError as ApiCommandError,
    EventSink,
    emit_artifact,
    emit_error,
    emit_event,
    emit_phase,
    emit_progress,
    emit_result,
    emit_started,
    emit_warning,
    event_session,
)

SCHEMA_VERSION = 1


@dataclass
class NdjsonEventSink(EventSink):
    stream: TextIO

    def emit(self, event_type: str, **payload: Any) -> None:
        record = {"type": event_type}
        record.update(payload)
        self.stream.write(json.dumps(record, sort_keys=True) + "\n")
        self.stream.flush()


@contextmanager
def ndjson_session(*, stream: TextIO | None = None) -> Generator[NdjsonEventSink, None, None]:
    sink = NdjsonEventSink(stream=stream or sys.stdout)
    with event_session(sink):
        yield sink


def error_code_for_exception(exc: BaseException) -> str:
    if isinstance(exc, ApiCommandError):
        return exc.code
    if isinstance(exc, KeyboardInterrupt):
        return api_codes.CANCELLED
    if isinstance(exc, FileNotFoundError):
        return api_codes.NOT_FOUND
    if isinstance(exc, PermissionError):
        return api_codes.PERMISSION_DENIED
    if isinstance(exc, ValueError):
        return api_codes.INVALID_INPUT
    if isinstance(exc, RuntimeError):
        return api_codes.RUNTIME_ERROR
    if isinstance(exc, OSError):
        return api_codes.IO_ERROR
    return api_codes.RUNTIME_ERROR


def error_details_for_exception(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, ApiCommandError):
        return dict(exc.details)
    if isinstance(exc, OSError):
        details: dict[str, Any] = {}
        if exc.filename:
            details["path"] = exc.filename
        if exc.errno is not None:
            details["errno"] = exc.errno
        return details
    return {}


__all__ = [
    "ApiCommandError",
    "NdjsonEventSink",
    "SCHEMA_VERSION",
    "emit_artifact",
    "emit_error",
    "emit_event",
    "emit_phase",
    "emit_progress",
    "emit_result",
    "emit_started",
    "emit_warning",
    "error_code_for_exception",
    "error_details_for_exception",
    "ndjson_session",
]
