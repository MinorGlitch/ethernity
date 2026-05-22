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

"""Root shard policy discovery for extension unlock decisions."""

from __future__ import annotations

from pathlib import Path

from ethernity.cli.features.recover.key_recovery import InsufficientShardError
from ethernity.cli.shared.root_shard_policy import (
    has_potential_root_shard_frames,
    root_level_key_frames_from_scan,
    root_shard_quorum_from_frames,
)
from ethernity.crypto import sharding as sharding_module


def published_root_passphrase_shard_policy(
    root_dir: Path,
    *,
    root_doc_id: bytes,
    root_doc_hash: bytes,
    sign_pub: bytes | None,
    quiet: bool,
) -> tuple[int | None, int]:
    """Return the published root passphrase shard quorum, if the root publishes one."""

    frames = root_level_key_frames_from_scan(root_dir, quiet=quiet)
    if not frames:
        return None, 0
    if sign_pub is None:
        if has_potential_root_shard_frames(
            frames,
            expected_doc_id=root_doc_id,
            expected_doc_hash=root_doc_hash,
        ):
            raise ValueError(
                "root passphrase shard policy requires a verified root signing authority"
            )
        return None, 0
    try:
        threshold, share_count = root_shard_quorum_from_frames(
            frames,
            expected_doc_id=root_doc_id,
            expected_doc_hash=root_doc_hash,
            sign_pub=sign_pub,
            key_type=sharding_module.KEY_TYPE_PASSPHRASE,
            secret_label="passphrase",
            require_quorum=True,
        )
    except InsufficientShardError as exc:
        raise ValueError(
            "root passphrase shards are under quorum; "
            f"need at least {exc.threshold}, found {exc.provided_count}"
        ) from exc
    if share_count <= 0:
        return None, 0
    if threshold is None:
        return None, 0
    return threshold, share_count


__all__ = ["published_root_passphrase_shard_policy"]
