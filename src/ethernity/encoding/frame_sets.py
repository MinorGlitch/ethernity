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

"""Frame-set deduplication and recovery-frame classification."""

from __future__ import annotations

from ethernity.encoding.framing import Frame, FrameType

__all__ = [
    "deduplicate_auth_frames",
    "deduplicate_frame_slots",
    "deduplicate_identical_frames",
    "split_main_and_auth_frames",
]


def deduplicate_frame_slots(frames: list[Frame]) -> list[Frame]:
    """Deduplicate logical frame slots while rejecting conflicting contents."""

    seen: dict[tuple[int, int, bytes], Frame] = {}
    deduplicated: list[Frame] = []
    for frame in frames:
        key = (int(frame.frame_type), int(frame.index), frame.doc_id)
        existing = seen.get(key)
        if existing is not None:
            if existing.data != frame.data or existing.total != frame.total:
                raise ValueError("conflicting duplicate frames detected")
            continue
        seen[key] = frame
        deduplicated.append(frame)
    return deduplicated


def deduplicate_identical_frames(frames: list[Frame]) -> list[Frame]:
    """Collapse complete frame-value repeats without interpreting other differences."""

    seen: set[tuple[int, int, bytes, int, int, bytes]] = set()
    deduplicated: list[Frame] = []
    for frame in frames:
        key = (frame.version, frame.frame_type, frame.doc_id, frame.index, frame.total, frame.data)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(frame)
    return deduplicated


def deduplicate_auth_frames(frames: list[Frame]) -> list[Frame]:
    """Deduplicate AUTH frame slots and reject frames of other types."""

    if not frames:
        return []
    deduplicated = deduplicate_frame_slots(frames)
    for frame in deduplicated:
        if frame.frame_type != FrameType.AUTH:
            raise ValueError("auth payloads must be AUTH type")
    return deduplicated


def split_main_and_auth_frames(frames: list[Frame]) -> tuple[list[Frame], list[Frame]]:
    """Split recovery frames into MAIN and AUTH lists, rejecting other types."""

    main_frames: list[Frame] = []
    auth_frames: list[Frame] = []
    for frame in frames:
        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            main_frames.append(frame)
        elif frame.frame_type == FrameType.AUTH:
            auth_frames.append(frame)
        else:
            raise ValueError("unexpected frame type in main document QR payloads")
    if not main_frames:
        raise ValueError(
            "no main document payloads provided; check the MAIN QR payloads or recovery text"
        )
    return main_frames, auth_frames
