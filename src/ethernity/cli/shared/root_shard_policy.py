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

"""Compatibility adapters for workflow-owned root shard policy helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ethernity.cli.shared.io.frames import NoQrFramesError, frames_from_scan
from ethernity.encoding.framing import Frame
from ethernity.workflows.recovery import root_shard_policy as _root_shard_policy


def root_level_key_frames_from_scan(root_dir: Path, *, quiet: bool) -> tuple[Frame, ...]:
    """Return KEY frames from immediate root-level scan carriers only."""

    return _root_shard_policy.root_level_key_frames_from_scan(
        root_dir,
        quiet=quiet,
        _frame_scanner=frames_from_scan,
        _no_qr_frames_error=NoQrFramesError,
    )


def root_level_key_frame_carriers_from_scan(
    root_dir: Path,
    *,
    quiet: bool,
) -> tuple[tuple[Path, tuple[Frame, ...]], ...]:
    """Return each immediate root-level carrier together with its KEY frames."""

    return _root_shard_policy.root_level_key_frame_carriers_from_scan(
        root_dir,
        quiet=quiet,
        _frame_scanner=frames_from_scan,
        _no_qr_frames_error=NoQrFramesError,
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
    """Infer a root shard quorum from frames signed by the trusted root authority."""

    return _root_shard_policy.root_shard_quorum_from_frames(
        frames,
        expected_doc_id=expected_doc_id,
        expected_doc_hash=expected_doc_hash,
        sign_pub=sign_pub,
        key_type=key_type,
        secret_label=secret_label,
        require_quorum=require_quorum,
    )


def has_potential_root_shard_frames(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes | None,
    expected_doc_hash: bytes,
) -> bool:
    """Return whether frames contain shard payloads that appear bound to the root document."""

    return _root_shard_policy.has_potential_root_shard_frames(
        frames,
        expected_doc_id=expected_doc_id,
        expected_doc_hash=expected_doc_hash,
    )


__all__ = [
    "has_potential_root_shard_frames",
    "root_level_key_frame_carriers_from_scan",
    "root_level_key_frames_from_scan",
    "root_shard_quorum_from_frames",
]
