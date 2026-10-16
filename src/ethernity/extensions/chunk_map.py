from __future__ import annotations

import hashlib
from collections.abc import Mapping


def normalize_chunk_map(chunk_map: Mapping[bytes, bytes] | None) -> dict[bytes, bytes]:
    """Validate and normalize a content-addressed extension chunk map."""

    if chunk_map is None:
        return {}
    normalized: dict[bytes, bytes] = {}
    for chunk_id, chunk_bytes in chunk_map.items():
        if not isinstance(chunk_id, (bytes, bytearray)) or len(chunk_id) != 32:
            raise ValueError("chunk_id must be 32 bytes")
        if not isinstance(chunk_bytes, (bytes, bytearray)):
            raise ValueError("chunk payload must be bytes")
        raw_chunk_id = bytes(chunk_id)
        raw_chunk_bytes = bytes(chunk_bytes)
        if hashlib.sha256(raw_chunk_bytes).digest() != raw_chunk_id:
            raise ValueError("chunk payload does not hash to chunk_id")
        normalized[raw_chunk_id] = raw_chunk_bytes
    return normalized
