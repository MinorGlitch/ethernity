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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ethernity.workflows.shared import api_codes
from ethernity.workflows.shared.events import active_event_sink, emit_warning


@dataclass(frozen=True)
class WorkflowNotice:
    """Adapter-neutral non-fatal workflow notice."""

    code: str
    message: str
    details: dict[str, object]


WorkflowNoticeSink = Callable[[WorkflowNotice], None]


def send_notice(
    sink: WorkflowNoticeSink | None,
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> None:
    """Send one typed notice when a caller supplied a sink."""

    if sink is not None:
        sink(WorkflowNotice(code=code, message=message, details=dict(details or {})))


__all__ = ["WorkflowNotice", "WorkflowNoticeSink", "send_notice", "warn"]


def warn(
    message: str,
    *,
    quiet: bool,
    code: str = api_codes.WARNING,
    details: dict[str, Any] | None = None,
) -> None:
    if active_event_sink() is not None:
        emit_warning(code=code, message=message, details=details)
    _ = quiet
