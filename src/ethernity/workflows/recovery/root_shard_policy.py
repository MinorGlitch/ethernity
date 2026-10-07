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

"""Discover root-shard policy from carrier content."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from ethernity.crypto import sharding as sharding_module
from ethernity.encoding.framing import Frame, FrameType
from ethernity.workflows.recovery.keys import (
    InsufficientShardError,
    RecoveryTrust,
)


def root_shard_quorum_from_frames(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    sign_pub: bytes,
    key_type: str,
    secret_label: str,
    require_quorum: bool = True,
) -> tuple[int | None, int]:
    """Infer a root shard quorum from frames signed by the trusted root signing key."""

    trust = RecoveryTrust(expected_doc_id, expected_doc_hash, sign_pub)
    selected = _select_root_shard_frames(
        frames, trust, key_type=key_type, secret_label=secret_label
    )
    if not selected:
        return None, 0
    try:
        shares = RecoveryTrust(
            expected_doc_id, expected_doc_hash, sign_pub, False
        ).validated_shards(selected, key_type=key_type, secret_label=secret_label)
    except InsufficientShardError as exc:
        if not require_quorum and exc.share_count is not None:
            return exc.threshold, exc.share_count
        raise
    first = shares[0]
    return first.threshold, first.share_count


def has_potential_root_shard_frames(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes,
) -> bool:
    """Return whether frames contain shard payloads that appear bound to the root document."""

    for _frame, payload in decoded_shard_candidates(frames, doc_id=expected_doc_id):
        if payload.doc_hash == expected_doc_hash:
            return True
    return False


def decoded_shard_candidates(
    frames: Sequence[Frame], *, doc_id: bytes | None = None
) -> Iterator[tuple[Frame, sharding_module.ShardPayload]]:
    """Yield valid key payloads for discovery, ignoring unrelated or malformed carriers."""
    for frame in frames:
        if frame.frame_type != FrameType.KEY_DOCUMENT:
            continue
        if doc_id is not None and frame.doc_id != doc_id:
            continue
        try:
            yield frame, sharding_module.decode_shard_payload(frame.data)
        except ValueError:
            continue


def _select_root_shard_frames(
    frames: Sequence[Frame],
    trust: RecoveryTrust,
    *,
    key_type: str,
    secret_label: str,
) -> list[Frame]:
    selected: list[Frame] = []
    for frame in frames:
        if frame.frame_type != FrameType.KEY_DOCUMENT:
            continue
        if frame.doc_id != trust.doc_id:
            continue
        try:
            payload = sharding_module.decode_shard_payload(frame.data)
        except ValueError as exc:
            raise ValueError(f"invalid root {secret_label} shard payload: {exc}") from exc
        if payload.key_type != key_type or payload.doc_hash != trust.doc_hash:
            continue
        if payload.sign_pub != trust.sign_pub:
            raise ValueError(
                f"root {secret_label} shard signing key does not match root signing key"
            )
        selected.append(frame)
    return selected


__all__ = [
    "decoded_shard_candidates",
    "has_potential_root_shard_frames",
    "root_shard_quorum_from_frames",
]
