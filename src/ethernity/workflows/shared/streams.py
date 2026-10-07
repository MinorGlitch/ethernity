"""Bounded binary reads shared by backup and recovery input loaders."""

from __future__ import annotations

from typing import BinaryIO


class StreamSizeLimitError(ValueError):
    """A stream exceeded its bound before the rest of it was read."""

    def __init__(self, *, max_bytes: int, bytes_read: int) -> None:
        super().__init__(f"stream exceeds {max_bytes} bytes: {bytes_read} bytes read")
        self.bytes_read = bytes_read


def read_bounded_bytes(handle: BinaryIO, *, max_bytes: int) -> bytes:
    """Read at most the limit plus one byte, sufficient to detect an oversized stream."""

    if max_bytes < 0:
        raise ValueError("stream size limit must be non-negative")
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = handle.read(min(64 * 1024, max_bytes + 1 - total_bytes))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise StreamSizeLimitError(max_bytes=max_bytes, bytes_read=total_bytes)
