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

"""Build issues shared by workflow inspections."""

from __future__ import annotations

from collections.abc import Mapping

from ethernity.workflows.shared.events import CommandError

BlockingIssue = dict[str, object]


def blocking_issue(
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> BlockingIssue:
    """Keep an issue code, message, and details together."""

    return {
        "code": code,
        "message": message,
        "details": dict(details or {}),
    }


def blocking_issue_from_exception(
    exc: Exception,
    *,
    fallback_code: str,
    fallback_details: Mapping[str, object] | None = None,
) -> BlockingIssue:
    """Convert an exception to an issue, preserving its code and details."""

    if isinstance(exc, CommandError):
        return blocking_issue(code=exc.code, message=str(exc), details=exc.details)
    code = getattr(exc, "code", None)
    details = getattr(exc, "details", None)
    if isinstance(code, str) and code:
        return blocking_issue(
            code=code,
            message=str(exc),
            details=details if isinstance(details, Mapping) else {},
        )
    return blocking_issue(
        code=fallback_code,
        message=str(exc),
        details=dict(fallback_details or {}),
    )


__all__ = [
    "BlockingIssue",
    "blocking_issue",
    "blocking_issue_from_exception",
]
