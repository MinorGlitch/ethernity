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

from __future__ import annotations

from typing import Iterable, Sequence

from .framing import DOC_ID_LEN, VERSION, Frame, decode_frame
from .zbase32 import decode_fallback_lines as _decode_fallback_lines

DEFAULT_CHUNK_SIZE = 1024


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
    if total <= 0:
        raise ValueError("total must be positive")

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
        if frame.index < 0:
            raise ValueError("index must be non-negative")
        if frame.index >= total:
            raise ValueError("index must be < total")
        if frame.index in seen:
            existing = seen[frame.index]
            if existing.data != frame.data:
                raise ValueError("conflicting duplicate frames detected")
            continue
        seen[frame.index] = frame

    if len(seen) != total:
        raise ValueError("missing frames")

    return b"".join(seen[idx].data for idx in range(total))


def fallback_lines_to_frame(lines: Iterable[str]) -> Frame:
    data = _decode_fallback_lines(lines)
    return decode_frame(data)
