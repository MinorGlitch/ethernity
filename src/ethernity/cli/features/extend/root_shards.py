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

from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    _validated_shard_payloads_from_frames,
)
from ethernity.cli.shared.io.frames import _shard_frames_from_scan
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

    paths = sorted(root_dir.glob("shard-*.pdf"))
    if not paths:
        return None, 0
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"root passphrase shard must not be a symlink: {path.name}")
    frames = _shard_frames_from_scan([str(path) for path in paths], quiet=quiet)
    if not frames:
        return None, 0
    try:
        shares = _validated_shard_payloads_from_frames(
            frames,
            expected_doc_id=root_doc_id,
            expected_doc_hash=root_doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=sign_pub is None,
            key_type=sharding_module.KEY_TYPE_PASSPHRASE,
            secret_label="passphrase",
        )
    except InsufficientShardError as exc:
        if exc.share_count is not None:
            return None, 0
        raise
    first = shares[0]
    if len(shares) != first.share_count:
        return None, 0
    return first.threshold, first.share_count


__all__ = ["published_root_passphrase_shard_policy"]
