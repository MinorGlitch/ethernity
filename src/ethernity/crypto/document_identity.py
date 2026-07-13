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

"""Canonical document hash and identifier derivation."""

from __future__ import annotations

import hashlib

from ethernity.encoding.framing import DOC_ID_LEN

DOC_HASH_LEN = 32

__all__ = [
    "DOC_HASH_LEN",
    "doc_hash_from_ciphertext",
    "doc_id_and_hash_from_ciphertext",
    "doc_id_from_doc_hash",
    "normalize_doc_hash_hex",
    "parse_doc_hash_hex",
]


def doc_hash_from_ciphertext(ciphertext: bytes) -> bytes:
    """Derive the normative BLAKE2b-256 document hash from ciphertext."""
    return hashlib.blake2b(ciphertext, digest_size=DOC_HASH_LEN).digest()


def doc_id_from_doc_hash(doc_hash: bytes) -> bytes:
    """Derive the document identifier from a validated document hash."""
    if len(doc_hash) != DOC_HASH_LEN:
        raise ValueError(f"doc_hash must be {DOC_HASH_LEN} bytes")
    return doc_hash[:DOC_ID_LEN]


def doc_id_and_hash_from_ciphertext(ciphertext: bytes) -> tuple[bytes, bytes]:
    """Derive a document identifier and its full hash from ciphertext."""
    doc_hash = doc_hash_from_ciphertext(ciphertext)
    doc_id = doc_id_from_doc_hash(doc_hash)
    return doc_id, doc_hash


def normalize_doc_hash_hex(value: str, *, option: str = "doc hash") -> str:
    """Normalize and validate a hexadecimal document hash."""
    normalized = value.strip().lower()
    if len(normalized) != DOC_HASH_LEN * 2 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{option} must be a 32-byte lowercase hex value")
    return normalized


def parse_doc_hash_hex(value: str, *, option: str) -> bytes:
    """Parse a 32-byte hexadecimal document hash with option-specific errors."""

    normalized = value.strip().lower()
    try:
        doc_hash = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError(f"{option} must be lowercase hex") from exc
    if len(doc_hash) != DOC_HASH_LEN:
        raise ValueError(f"{option} must be a {DOC_HASH_LEN}-byte hex value")
    return doc_hash
