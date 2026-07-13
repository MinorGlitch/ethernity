"""Canonical runtime choices and bounds shared by config boundaries."""

from __future__ import annotations

from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES
from ethernity.formats.extension_envelope import MIN_EXTENSION_CHUNK_SIZE
from ethernity.page_sizes import paper_size_names

PAGE_SIZES = paper_size_names()
QR_ERROR_LEVELS = ("L", "M", "Q", "H")
PAYLOAD_CODECS = ("auto", "raw", "gzip")
QR_PAYLOAD_CODECS = ("raw", "base64")
SIGNING_KEY_MODES = ("embedded", "sharded")
EXTENSION_UNLOCK_POLICIES = ("self-contained", "reuse-root")
EXTENSION_SIGNING_KEY_MODES = ("not-stored", "sharded")


def extension_chunking_profile_is_valid(
    *,
    target_size: int,
    min_size: int,
    max_size: int,
) -> bool:
    return (
        MIN_EXTENSION_CHUNK_SIZE <= min_size <= target_size <= max_size
        and target_size <= MAX_DECOMPRESSED_PAYLOAD_BYTES
        and max_size <= MAX_DECOMPRESSED_PAYLOAD_BYTES
    )


__all__ = [
    "EXTENSION_SIGNING_KEY_MODES",
    "EXTENSION_UNLOCK_POLICIES",
    "PAGE_SIZES",
    "PAYLOAD_CODECS",
    "QR_ERROR_LEVELS",
    "QR_PAYLOAD_CODECS",
    "SIGNING_KEY_MODES",
    "extension_chunking_profile_is_valid",
]
