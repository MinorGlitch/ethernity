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
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

"""Domain-owned extension error codes and exceptions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AUTH_DOC_HASH_MISMATCH = "AUTH_DOC_HASH_MISMATCH"
AUTH_SIGNATURE_INVALID = "AUTH_SIGNATURE_INVALID"
RECOVERY_HEAD_UNTRUSTED = "RECOVERY_HEAD_UNTRUSTED"
ROOT_AUTHORITY_MISMATCH = "ROOT_AUTHORITY_MISMATCH"


@dataclass
class ExtensionRecoveryError(ValueError):
    """Structured extension recovery failure independent of CLI/API layers."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)


__all__ = [
    "AUTH_DOC_HASH_MISMATCH",
    "AUTH_SIGNATURE_INVALID",
    "ExtensionRecoveryError",
    "RECOVERY_HEAD_UNTRUSTED",
    "ROOT_AUTHORITY_MISMATCH",
]
