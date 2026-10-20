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
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BlockingIssue:
    """A recovery failure retained as domain data until an adapter presents it."""

    code: str
    message: str
    details: dict[str, object] = field(default_factory=dict)


def blocking_issue(
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> BlockingIssue:
    """Keep an issue code, message, and details together."""

    return BlockingIssue(code, message, dict(details or {}))


__all__ = [
    "BlockingIssue",
    "blocking_issue",
]
