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

"""Content-first root shard policy discovery helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from ethernity.crypto import sharding as sharding_module
from ethernity.encoding.framing import Frame, FrameType
from ethernity.qr.scan import looks_like_image, looks_like_pdf
from ethernity.workflows.recovery.frame_inputs import NoQrFramesError, frames_from_scan
from ethernity.workflows.recovery.keys import (
    InsufficientShardError,
    validated_shard_payloads_from_frames,
)

FrameScanner = Callable[[list[str]], list[Frame]]

_SCAN_FILE_SUFFIXES = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".webp",
}


def root_level_key_frames_from_scan(
    root_dir: Path,
    *,
    quiet: bool,
    _frame_scanner: FrameScanner | None = None,
    _no_qr_frames_error: type[ValueError] | None = None,
) -> tuple[Frame, ...]:
    """Return KEY frames from immediate root-level scan carriers only."""

    return tuple(
        frame
        for _path, carrier_frames in root_level_key_frame_carriers_from_scan(
            root_dir,
            quiet=quiet,
            _frame_scanner=_frame_scanner,
            _no_qr_frames_error=_no_qr_frames_error,
        )
        for frame in carrier_frames
    )


def root_level_key_frame_carriers_from_scan(
    root_dir: Path,
    *,
    quiet: bool,
    _frame_scanner: FrameScanner | None = None,
    _no_qr_frames_error: type[ValueError] | None = None,
) -> tuple[tuple[Path, tuple[Frame, ...]], ...]:
    """Return each immediate root-level carrier together with its KEY frames."""

    _ = quiet
    scanner = frames_from_scan if _frame_scanner is None else _frame_scanner
    no_frames_error = NoQrFramesError if _no_qr_frames_error is None else _no_qr_frames_error
    candidates = _root_level_scan_candidates(root_dir)
    carriers: list[tuple[Path, tuple[Frame, ...]]] = []
    for path in candidates:
        try:
            frames = tuple(
                frame
                for frame in scanner([str(path)])
                if frame.frame_type == FrameType.KEY_DOCUMENT
            )
        except no_frames_error:
            continue
        except ValueError as exc:
            raise ValueError(f"root shard policy scan failed: {exc}") from exc
        if frames:
            carriers.append((path, frames))
    return tuple(carriers)


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

    selected = _select_root_shard_frames(
        frames,
        expected_doc_id=expected_doc_id,
        expected_doc_hash=expected_doc_hash,
        sign_pub=sign_pub,
        key_type=key_type,
        secret_label=secret_label,
    )
    if not selected:
        return None, 0
    try:
        shares = validated_shard_payloads_from_frames(
            selected,
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=False,
            key_type=key_type,
            secret_label=secret_label,
        )
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

    for frame in frames:
        if frame.frame_type != FrameType.KEY_DOCUMENT:
            continue
        if expected_doc_id is not None and frame.doc_id != expected_doc_id:
            continue
        try:
            payload = sharding_module.decode_shard_payload(frame.data)
        except ValueError:
            continue
        if payload.doc_hash == expected_doc_hash:
            return True
    return False


def _root_level_scan_candidates(root_dir: Path) -> tuple[Path, ...]:
    if not root_dir.exists() or not root_dir.is_dir():
        return ()
    candidates: list[Path] = []
    for path in sorted(root_dir.iterdir()):
        if path.is_symlink():
            if path.suffix.lower() in _SCAN_FILE_SUFFIXES:
                raise ValueError(f"root shard policy candidate must not be a symlink: {path}")
            continue
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in _SCAN_FILE_SUFFIXES or looks_like_pdf(path) or looks_like_image(path):
            candidates.append(path)
    return tuple(candidates)


def _select_root_shard_frames(
    frames: Sequence[Frame],
    *,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    sign_pub: bytes,
    key_type: str,
    secret_label: str,
) -> list[Frame]:
    selected: list[Frame] = []
    for frame in frames:
        if frame.frame_type != FrameType.KEY_DOCUMENT:
            continue
        if frame.doc_id != expected_doc_id:
            continue
        try:
            payload = sharding_module.decode_shard_payload(frame.data)
        except ValueError as exc:
            raise ValueError(f"invalid root {secret_label} shard payload: {exc}") from exc
        if payload.key_type != key_type or payload.doc_hash != expected_doc_hash:
            continue
        if payload.sign_pub != sign_pub:
            raise ValueError(f"root {secret_label} shard signing key does not match root authority")
        selected.append(frame)
    return selected


__all__ = [
    "has_potential_root_shard_frames",
    "root_level_key_frame_carriers_from_scan",
    "root_level_key_frames_from_scan",
    "root_shard_quorum_from_frames",
]
