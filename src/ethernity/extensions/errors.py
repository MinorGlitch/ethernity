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
ROOT_SIGNING_KEY_MISMATCH = "ROOT_SIGNING_KEY_MISMATCH"


@dataclass
class ExtensionRecoveryError(ValueError):
    """Extension recovery failure with an error code and details."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)


class OrphanAuthFramesError(ValueError):
    """AUTH carriers refer to documents whose MAIN carriers were not supplied."""

    def __init__(self, doc_ids: tuple[bytes, ...], *, source_label: str) -> None:
        self.doc_ids = doc_ids
        self.source_label = source_label
        preview = ", ".join(doc_id.hex() for doc_id in doc_ids[:3])
        super().__init__(f"{source_label} contains AUTH frame(s) without matching MAIN: {preview}")


__all__ = [
    "AUTH_DOC_HASH_MISMATCH",
    "AUTH_SIGNATURE_INVALID",
    "ExtensionRecoveryError",
    "OrphanAuthFramesError",
    "RECOVERY_HEAD_UNTRUSTED",
    "ROOT_SIGNING_KEY_MISMATCH",
]
