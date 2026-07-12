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

"""Shared root-plus-extension chain resource admission rules."""

from __future__ import annotations

from ethernity.core.bounds import (
    MAX_RECOVERY_CIPHERTEXT_BYTES,
    MAX_RECOVERY_DECODED_CHUNK_BYTES,
    MAX_RECOVERY_DOCUMENTS,
)


def require_chain_resource_limits(
    *,
    document_count: int,
    total_ciphertext_bytes: int,
    operation: str,
) -> None:
    """Reject a chain that exceeds the interoperable recovery profile."""

    if isinstance(document_count, bool) or not isinstance(document_count, int):
        raise ValueError("chain document_count must be an integer")
    if document_count < 0:
        raise ValueError("chain document_count must be non-negative")
    if isinstance(total_ciphertext_bytes, bool) or not isinstance(total_ciphertext_bytes, int):
        raise ValueError("chain total_ciphertext_bytes must be an integer")
    if total_ciphertext_bytes < 0:
        raise ValueError("chain total_ciphertext_bytes must be non-negative")
    if document_count > MAX_RECOVERY_DOCUMENTS:
        raise ValueError(
            f"{operation} contains {document_count} recovery documents; the maximum is "
            f"MAX_RECOVERY_DOCUMENTS ({MAX_RECOVERY_DOCUMENTS}). Rebuild the latest logical "
            "state as a fresh standalone backup before adding more files."
        )
    if total_ciphertext_bytes > MAX_RECOVERY_CIPHERTEXT_BYTES:
        raise ValueError(
            f"{operation} contains {total_ciphertext_bytes} aggregate ciphertext bytes; the "
            "maximum is MAX_RECOVERY_CIPHERTEXT_BYTES "
            f"({MAX_RECOVERY_CIPHERTEXT_BYTES}). Rebuild the latest logical state as a fresh "
            "standalone backup before adding more files."
        )


def require_decoded_chunk_resource_limit(*, decoded_chunk_bytes: int, operation: str) -> None:
    """Reject cumulative extension decode/build work above the chain profile."""

    if isinstance(decoded_chunk_bytes, bool) or not isinstance(decoded_chunk_bytes, int):
        raise ValueError("chain decoded_chunk_bytes must be an integer")
    if decoded_chunk_bytes < 0:
        raise ValueError("chain decoded_chunk_bytes must be non-negative")
    if decoded_chunk_bytes > MAX_RECOVERY_DECODED_CHUNK_BYTES:
        raise ValueError(
            f"{operation} contains {decoded_chunk_bytes} decoded inline chunk bytes; the maximum "
            "is MAX_RECOVERY_DECODED_CHUNK_BYTES "
            f"({MAX_RECOVERY_DECODED_CHUNK_BYTES}). Rebuild the latest logical state as a fresh "
            "standalone backup before adding more files."
        )


__all__ = [
    "require_chain_resource_limits",
    "require_decoded_chunk_resource_limit",
]
