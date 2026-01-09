#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .fallback import (
    DEFAULT_GROUP_SIZE,
    DEFAULT_LINE_COUNT,
    DEFAULT_LINE_LENGTH,
    decode_fallback_lines as _decode_fallback_lines,
    encode_fallback_lines as _encode_fallback_lines,
)
from .framing import DOC_ID_LEN, VERSION, Frame, decode_frame, encode_frame

DEFAULT_CHUNK_SIZE = 1024


@dataclass(frozen=True)
class ChunkConfig:
    chunk_size: int = DEFAULT_CHUNK_SIZE
    group_size: int = DEFAULT_GROUP_SIZE
    line_length: int = DEFAULT_LINE_LENGTH
    line_count: int = DEFAULT_LINE_COUNT


def chunk_payload(
    payload: bytes,
    *,
    doc_id: bytes,
    frame_type: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    version: int = VERSION,
) -> list[Frame]:
    if not payload:
        raise ValueError("payload cannot be empty")
    if len(doc_id) != DOC_ID_LEN:
        raise ValueError(f"doc_id must be {DOC_ID_LEN} bytes")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    total = (len(payload) + chunk_size - 1) // chunk_size
    base_size = len(payload) // total
    remainder = len(payload) % total

    frames: list[Frame] = []
    offset = 0
    for idx in range(total):
        size = base_size + (1 if idx < remainder else 0)
        start = offset
        end = start + size
        frames.append(
            Frame(
                version=version,
                frame_type=frame_type,
                doc_id=doc_id,
                index=idx,
                total=total,
                data=payload[start:end],
            )
        )
        offset = end
    return frames


def reassemble_payload(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None = None,
    expected_frame_type: int | None = None,
) -> bytes:
    if not frames:
        raise ValueError("no frames provided")

    doc_id = expected_doc_id or frames[0].doc_id
    frame_type = expected_frame_type if expected_frame_type is not None else frames[0].frame_type
    total = frames[0].total
    version = frames[0].version

    if len(doc_id) != DOC_ID_LEN:
        raise ValueError(f"doc_id must be {DOC_ID_LEN} bytes")

    seen: dict[int, Frame] = {}
    for frame in frames:
        if frame.doc_id != doc_id:
            raise ValueError("mismatched doc_id")
        if frame.frame_type != frame_type:
            raise ValueError("mismatched frame_type")
        if frame.total != total:
            raise ValueError("mismatched total")
        if frame.version != version:
            raise ValueError("mismatched version")
        if frame.index in seen:
            raise ValueError("duplicate frame index")
        seen[frame.index] = frame

    if len(seen) != total:
        raise ValueError("missing frames")

    return b"".join(seen[idx].data for idx in range(total))


def frame_to_fallback_lines(
    frame: Frame,
    *,
    group_size: int = DEFAULT_GROUP_SIZE,
    line_length: int = DEFAULT_LINE_LENGTH,
    line_count: int | None = DEFAULT_LINE_COUNT,
) -> list[str]:
    encoded = encode_frame(frame)
    return _encode_fallback_lines(
        encoded,
        group_size=group_size,
        line_length=line_length,
        line_count=line_count,
    )


def payload_to_fallback_lines(
    payload: bytes,
    *,
    doc_id: bytes,
    frame_type: int,
    group_size: int = DEFAULT_GROUP_SIZE,
    line_length: int = DEFAULT_LINE_LENGTH,
) -> list[str]:
    if not payload:
        raise ValueError("payload cannot be empty")
    frame = Frame(
        version=VERSION,
        frame_type=frame_type,
        doc_id=doc_id,
        index=0,
        total=1,
        data=payload,
    )
    return _encode_fallback_lines(
        encode_frame(frame),
        group_size=group_size,
        line_length=line_length,
        line_count=None,
    )


def fallback_lines_to_frame(lines: Iterable[str]) -> Frame:
    data = _decode_fallback_lines(lines)
    return decode_frame(data)
