"""The shared reader must stop at its bound even when a stream has more data."""

from __future__ import annotations

from io import BytesIO

import pytest

from ethernity.workflows.shared.streams import StreamSizeLimitError, read_bounded_bytes


@pytest.mark.parametrize("size", [0, 1, 65535, 65536, 65537])
def test_stream_at_limit_is_accepted(size: int) -> None:
    data = b"x" * size
    assert read_bounded_bytes(BytesIO(data), max_bytes=size) == data


@pytest.mark.parametrize("limit", [0, 1, 65535, 65536, 65537])
def test_oversized_stream_stops_after_one_extra_byte(limit: int) -> None:
    stream = BytesIO(b"x" * (limit + 100))
    with pytest.raises(StreamSizeLimitError) as raised:
        read_bounded_bytes(stream, max_bytes=limit)
    assert raised.value.bytes_read == limit + 1
    assert stream.tell() == limit + 1


def test_negative_limit_is_rejected_before_reading() -> None:
    stream = BytesIO(b"x")
    with pytest.raises(ValueError, match="non-negative"):
        read_bounded_bytes(stream, max_bytes=-1)
    assert stream.tell() == 0
