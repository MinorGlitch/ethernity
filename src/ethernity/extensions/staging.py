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

"""Output paths and staging validation for extension publication."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from ethernity.core.bounds import MAX_EXTENSION_INDEX
from ethernity.encoding.framing import DOC_ID_LEN
from ethernity.publication import create_sibling_staging_dir, discard_staging_directory

DirectoryIdentity = tuple[int, int]


@dataclass(frozen=True)
class StagedExtensionPaths:
    """Explicit output inventory for a private extension publication transaction."""

    staging_dir: Path
    final_dir: Path
    staging_dir_identity: DirectoryIdentity
    output_parent_identity: DirectoryIdentity
    qr_document_path: Path
    recovery_document_path: Path


def preflight_extension_publish_target(output_dir: str | Path) -> None:
    """Check a new output destination without creating any files or directories."""

    final_path = Path(output_dir).expanduser().absolute()
    if final_path.exists() or final_path.is_symlink():
        raise ValueError(f"extension output directory already exists: {final_path}")
    parent = final_path.parent
    while not parent.exists():
        if parent.is_symlink():
            raise ValueError("extension output parent must not be a symlink")
        parent = parent.parent
    _directory_identity(parent, label="extension output parent")
    if not os.access(parent, os.W_OK | os.X_OK):
        raise ValueError(f"extension output parent is not writable: {parent}")


def create_extension_staging_paths(
    output_dir: str | Path,
    *,
    index: int,
    doc_id_hex: str,
    nonce: str,
) -> StagedExtensionPaths:
    """Create private staging beside the selected output destination."""

    preflight_extension_publish_target(output_dir)
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 1 <= index <= MAX_EXTENSION_INDEX
    ):
        raise ValueError(f"extension index must be between 1 and {MAX_EXTENSION_INDEX}")
    if (
        not isinstance(doc_id_hex, str)
        or re.fullmatch(rf"[0-9a-f]{{{DOC_ID_LEN * 2}}}", doc_id_hex) is None
    ):
        raise ValueError(f"doc_id_hex must be {DOC_ID_LEN * 2} lowercase hex characters")
    filenames = {
        doc_type: f"{doc_type}-{index:02d}-{doc_id_hex}.pdf"
        for doc_type in ("qr_document", "recovery_document")
    }
    if not isinstance(nonce, str) or re.fullmatch(r"[A-Za-z0-9._-]+", nonce) is None:
        raise ValueError("nonce must be a non-empty filename token")
    final_dir = Path(output_dir).expanduser().absolute()
    staging_dir = create_sibling_staging_dir(
        final_dir,
        prefix=f".staging-{final_dir.name}-extension-{nonce}-",
    )
    try:
        return StagedExtensionPaths(
            staging_dir=staging_dir,
            final_dir=final_dir,
            staging_dir_identity=_directory_identity(staging_dir, label="staging directory"),
            output_parent_identity=_directory_identity(
                final_dir.parent, label="extension output parent"
            ),
            qr_document_path=staging_dir / filenames["qr_document"],
            recovery_document_path=staging_dir / filenames["recovery_document"],
        )
    except BaseException:
        discard_staging_directory(staging_dir)
        raise


def validate_staged_extension_dir(paths: StagedExtensionPaths) -> None:
    """Require the planned regular-file inventory before content validation and promotion."""

    staging_dir = paths.staging_dir
    if _directory_identity(staging_dir, label="staging directory") != paths.staging_dir_identity:
        raise ValueError("staging directory changed before promotion")
    if staging_dir.parent != paths.final_dir.parent:
        raise ValueError("staging directory must be beside the output directory")
    if (
        _directory_identity(paths.final_dir.parent, label="extension output parent")
        != paths.output_parent_identity
    ):
        raise ValueError("extension output parent changed before promotion")

    expected_paths = (
        paths.qr_document_path,
        paths.recovery_document_path,
    )
    if any(path.parent != staging_dir for path in expected_paths):
        raise ValueError("extension output paths must be inside the staging directory")
    expected_names = {path.name for path in expected_paths}
    if len(expected_names) != len(expected_paths):
        raise ValueError("extension output paths must be distinct")
    actual_names: set[str] = set()
    for entry in staging_dir.iterdir():
        if entry.is_symlink():
            raise ValueError(f"staged extension contains symlinked file: {entry.name}")
        if not entry.is_file():
            raise ValueError(f"staged extension contains unexpected non-file entry: {entry.name}")
        if entry.name not in expected_names:
            raise ValueError(f"staged extension contains unexpected file: {entry.name}")
        actual_names.add(entry.name)
    missing = expected_names - actual_names
    if missing:
        raise ValueError(
            f"staged extension is missing required documents: {', '.join(sorted(missing))}"
        )


def _directory_identity(path: Path, *, label: str) -> DirectoryIdentity:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} not found: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} must not be a symlink")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a directory: {path}")
    return metadata.st_dev, metadata.st_ino
