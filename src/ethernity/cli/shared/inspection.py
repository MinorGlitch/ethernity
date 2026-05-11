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

"""Shared inspection/preflight payload helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ethernity.cli.shared import api_codes
from ethernity.cli.shared.events import CommandError

BlockingIssue = dict[str, object]


def blocking_issue(
    *,
    code: str,
    message: str,
    details: Mapping[str, object] | None = None,
) -> BlockingIssue:
    """Build the stable blocking issue shape used by inspect/preflight APIs."""

    return {
        "code": stable_blocking_issue_code(code),
        "message": message,
        "details": dict(details or {}),
    }


def blocking_issue_from_exception(
    exc: Exception,
    *,
    fallback_code: str,
    fallback_details: Mapping[str, object] | None = None,
) -> BlockingIssue:
    """Convert an exception into a blocking issue without losing stable command codes."""

    if isinstance(exc, CommandError):
        return blocking_issue(code=exc.code, message=str(exc), details=exc.details)
    return blocking_issue(
        code=fallback_code,
        message=str(exc),
        details=dict(fallback_details or {}),
    )


def stable_blocking_issue_code(code: str) -> str:
    """Return a stable blocking issue code, preserving existing stable codes."""

    if code in api_codes.STABLE_BLOCKING_ISSUE_CODES:
        return code
    if code in api_codes.STABLE_COMMAND_ERROR_CODES:
        return code
    return api_codes.INVALID_INPUT


def normalize_blocking_issues(
    issues: Iterable[Mapping[str, Any]],
) -> list[BlockingIssue]:
    """Normalize arbitrary issue mappings into the inspect/preflight issue contract."""

    normalized: list[BlockingIssue] = []
    for issue in issues:
        code = issue.get("code")
        message = issue.get("message")
        details = issue.get("details")
        normalized.append(
            blocking_issue(
                code=str(code) if isinstance(code, str) and code else api_codes.INVALID_INPUT,
                message=str(message) if message is not None else "inspection is not ready",
                details=details if isinstance(details, Mapping) else {},
            )
        )
    return normalized


def inspect_result_payload(
    *,
    command: str,
    source_summary: Mapping[str, object] | None,
    frame_counts: Mapping[str, object],
    unlock: Mapping[str, object],
    blocking_issues: Iterable[Mapping[str, Any]],
    warnings: Sequence[Mapping[str, Any]],
    operation: str = "inspect",
    **extra: object,
) -> dict[str, object]:
    """Build the common inspect/preflight event payload shape."""

    payload: dict[str, object] = {
        "command": command,
        "operation": operation,
        "source_summary": None if source_summary is None else dict(source_summary),
        "frame_counts": dict(frame_counts),
        "unlock": dict(unlock),
        "blocking_issues": normalize_blocking_issues(blocking_issues),
        "warnings": [dict(item) for item in warnings],
    }
    payload.update(extra)
    return payload


__all__ = [
    "BlockingIssue",
    "blocking_issue",
    "blocking_issue_from_exception",
    "inspect_result_payload",
    "normalize_blocking_issues",
    "stable_blocking_issue_code",
]
