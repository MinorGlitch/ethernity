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

"""Shared staged artifact publishing primitives.

Feature modules remain responsible for naming and content policy. This module owns the common
transaction mechanics: write to a private staging directory, validate, snapshot, promote under a
lock, and clean up failed staging output.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

ArtifactSnapshot = tuple[tuple[str, int, str], ...]
DirectoryIdentity = tuple[int, int]

_T = TypeVar("_T")


@dataclass(frozen=True)
class ArtifactPublishResult(Generic[_T]):
    """Result of a staged artifact publish transaction."""

    final_dir: Path
    snapshot: ArtifactSnapshot
    payload: _T


def create_sibling_staging_dir(
    final_dir: str | Path,
    *,
    prefix: str | None = None,
) -> Path:
    """Create a private staging directory next to a future final artifact directory."""

    final_path = Path(final_dir).expanduser()
    if final_path.exists() or final_path.is_symlink():
        raise ValueError(f"final artifact directory already exists: {final_path}")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=prefix or f".{final_path.name}.tmp-",
            dir=str(final_path.parent),
        )
    )
    _harden_dir_permissions(staging_dir)
    return staging_dir


def publish_staged_artifacts(
    *,
    staging_dir: str | Path,
    final_dir: str | Path,
    populate: Callable[[], _T],
    validate_staging: Callable[[Path], None] | None = None,
    validate_artifacts: Callable[[_T], None] | None = None,
    validate_promotion: Callable[[], None] | None = None,
    lock_dir: str | Path | None = None,
    cleanup_on_error: bool = True,
) -> ArtifactPublishResult[_T]:
    """Populate, validate, snapshot, and promote a staged artifact directory."""

    staging_path = Path(staging_dir).expanduser()
    final_path = Path(final_dir).expanduser()
    staging_identity = _directory_identity_or_none(staging_path)
    try:
        payload = populate()
        if validate_staging is not None:
            validate_staging(staging_path)
        snapshot = snapshot_artifact_dir(staging_path)
        if validate_artifacts is not None:
            validate_artifacts(payload)
        promoted = promote_staged_artifact_dir(
            staging_path,
            final_path,
            expected_snapshot=snapshot,
            expected_staging_identity=staging_identity,
            validate_staging=validate_staging,
            validate_promotion=validate_promotion,
            lock_dir=lock_dir,
        )
    except BaseException:
        if cleanup_on_error:
            discard_staged_artifact_dir(staging_path, expected_identity=staging_identity)
        raise
    return ArtifactPublishResult(final_dir=promoted, snapshot=snapshot, payload=payload)


def promote_staged_artifact_dir(
    staging_dir: str | Path,
    final_dir: str | Path,
    *,
    expected_snapshot: ArtifactSnapshot | None = None,
    expected_staging_identity: DirectoryIdentity | None = None,
    validate_staging: Callable[[Path], None] | None = None,
    validate_promotion: Callable[[], None] | None = None,
    lock_dir: str | Path | None = None,
) -> Path:
    """Atomically promote a validated staging directory into its final location."""

    staging_path = Path(staging_dir).expanduser()
    final_path = Path(final_dir).expanduser()
    staging_parent_identity = _directory_identity_or_none(staging_path.parent)
    final_parent_identity = _directory_identity_or_none(final_path.parent)
    if staging_path.is_symlink():
        raise ValueError("validated staging_dir must not be a symlink")
    if not staging_path.exists() or not staging_path.is_dir():
        raise ValueError("validated staging_dir no longer exists")
    if staging_parent_identity is None:
        raise ValueError("validated staging_dir parent no longer exists")
    if final_parent_identity is None:
        raise ValueError("final artifact directory parent does not exist")
    if final_path.exists() or final_path.is_symlink():
        raise ValueError(f"final artifact directory already exists: {final_path.name}")

    resolved_lock_dir = (
        Path(lock_dir).expanduser()
        if lock_dir is not None
        else final_path.parent / f".{final_path.name}.lock"
    )
    try:
        resolved_lock_dir.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValueError(
            f"final artifact directory is already being promoted: {final_path.name}"
        ) from exc

    try:
        if final_path.exists() or final_path.is_symlink():
            raise ValueError(f"final artifact directory already exists: {final_path.name}")
        if validate_staging is not None:
            validate_staging(staging_path)
        if (
            expected_staging_identity is not None
            and _directory_identity_or_none(staging_path) != expected_staging_identity
        ):
            raise ValueError("validated staging_dir changed before promotion")
        if (
            expected_snapshot is not None
            and snapshot_artifact_dir(staging_path) != expected_snapshot
        ):
            raise ValueError("validated staging_dir artifacts changed before promotion")
        if validate_promotion is not None:
            validate_promotion()
        _rename_validated_staging_dir(
            staging_path,
            final_path,
            expected_staging_identity=expected_staging_identity,
            expected_staging_parent_identity=staging_parent_identity,
            expected_final_parent_identity=final_parent_identity,
        )
    finally:
        with suppress(OSError):
            resolved_lock_dir.rmdir()
    return final_path


def _rename_validated_staging_dir(
    staging_path: Path,
    final_path: Path,
    *,
    expected_staging_identity: DirectoryIdentity | None,
    expected_staging_parent_identity: DirectoryIdentity,
    expected_final_parent_identity: DirectoryIdentity,
) -> None:
    if _directory_identity_or_none(staging_path.parent) != expected_staging_parent_identity:
        raise ValueError("validated staging_dir parent changed before promotion")
    if _directory_identity_or_none(final_path.parent) != expected_final_parent_identity:
        raise ValueError("final artifact directory parent changed before promotion")
    if final_path.exists() or final_path.is_symlink():
        raise ValueError(f"final artifact directory already exists: {final_path.name}")
    if (
        expected_staging_identity is not None
        and _directory_identity_or_none(staging_path) != expected_staging_identity
    ):
        raise ValueError("validated staging_dir changed before promotion")

    if _supports_fd_relative_rename():
        _rename_validated_staging_dir_fd(
            staging_path,
            final_path,
            expected_staging_identity=expected_staging_identity,
            expected_staging_parent_identity=expected_staging_parent_identity,
            expected_final_parent_identity=expected_final_parent_identity,
        )
    else:
        staging_path.rename(final_path)

    promoted_identity = _directory_identity_or_none(final_path)
    if expected_staging_identity is not None and promoted_identity != expected_staging_identity:
        raise ValueError(
            "promoted artifact directory identity does not match validated staging_dir"
        )


def _rename_validated_staging_dir_fd(
    staging_path: Path,
    final_path: Path,
    *,
    expected_staging_identity: DirectoryIdentity | None,
    expected_staging_parent_identity: DirectoryIdentity,
    expected_final_parent_identity: DirectoryIdentity,
) -> None:
    source_parent_fd = _open_directory_fd(staging_path.parent)
    try:
        final_parent_fd = _open_directory_fd(final_path.parent)
        try:
            if _directory_identity_from_fd(source_parent_fd) != expected_staging_parent_identity:
                raise ValueError("validated staging_dir parent changed before promotion")
            if _directory_identity_from_fd(final_parent_fd) != expected_final_parent_identity:
                raise ValueError("final artifact directory parent changed before promotion")
            if (
                expected_staging_identity is not None
                and _directory_child_identity_or_none(staging_path.name, source_parent_fd)
                != expected_staging_identity
            ):
                raise ValueError("validated staging_dir changed before promotion")
            if _directory_child_identity_or_none(final_path.name, final_parent_fd) is not None:
                raise ValueError(f"final artifact directory already exists: {final_path.name}")
            os.rename(
                staging_path.name,
                final_path.name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=final_parent_fd,
            )
        finally:
            os.close(final_parent_fd)
    finally:
        os.close(source_parent_fd)


def snapshot_artifact_dir(staging_dir: str | Path) -> ArtifactSnapshot:
    """Return a content fingerprint for direct regular files in a staged artifact directory."""

    path = Path(staging_dir).expanduser()
    if path.is_symlink():
        raise ValueError("staging_dir must not be a symlink")
    if not path.exists() or not path.is_dir():
        raise ValueError("staging_dir must be an existing directory")

    snapshot: list[tuple[str, int, str]] = []
    for entry in sorted(path.iterdir(), key=lambda item: item.name):
        if entry.is_symlink():
            raise ValueError(f"staged artifact directory contains symlinked artifact: {entry.name}")
        if not entry.is_file():
            raise ValueError(
                f"staged artifact directory contains unexpected non-file entry: {entry.name}"
            )
        digest = hashlib.sha256()
        with entry.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        snapshot.append((entry.name, entry.stat().st_size, digest.hexdigest()))
    return tuple(snapshot)


def discard_staged_artifact_dir(
    staging_dir: str | Path | None,
    *,
    expected_identity: DirectoryIdentity | None = None,
) -> None:
    """Remove a staging artifact directory after a failed publish attempt."""

    if staging_dir is None:
        return
    staging_path = Path(staging_dir).expanduser()
    if (
        expected_identity is not None
        and _directory_identity_or_none(staging_path) != expected_identity
    ):
        return
    shutil.rmtree(staging_path, ignore_errors=True)


def _directory_identity_or_none(path: Path) -> DirectoryIdentity | None:
    try:
        stat_result = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return (stat_result.st_dev, stat_result.st_ino)


def _directory_child_identity_or_none(name: str, parent_fd: int) -> DirectoryIdentity | None:
    try:
        stat_result = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return None
    return (stat_result.st_dev, stat_result.st_ino)


def _directory_identity_from_fd(fd: int) -> DirectoryIdentity:
    stat_result = os.fstat(fd)
    return (stat_result.st_dev, stat_result.st_ino)


def _open_directory_fd(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def _supports_fd_relative_rename() -> bool:
    return os.rename in os.supports_dir_fd and os.stat in os.supports_dir_fd


def _harden_dir_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    with suppress(OSError):
        path.chmod(0o700)
