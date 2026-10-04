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

"""Shared staged-directory publication primitives.

Feature modules remain responsible for naming and content policy. This module owns the common
transaction mechanics: write to a private staging directory, validate, snapshot, promote under a
per-output lock, and clean up failed staging output.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Generic, Iterator, Literal, TypeAlias, TypeVar

DirectorySnapshot = tuple[tuple[str, int, str], ...]
DirectoryIdentity = tuple[int, int]
PublicationDurability: TypeAlias = Literal["required", "best-effort"]

_T = TypeVar("_T")


@dataclass(frozen=True)
class DirectoryPublishResult(Generic[_T]):
    """Result of a staged-directory publication transaction."""

    final_dir: Path
    snapshot: DirectorySnapshot
    payload: _T


def create_sibling_staging_dir(
    final_dir: str | Path,
    *,
    prefix: str | None = None,
) -> Path:
    """Create a private staging directory next to a future published directory."""

    final_path = Path(final_dir).expanduser()
    if final_path.exists() or final_path.is_symlink():
        raise ValueError(f"final directory already exists: {final_path}")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=prefix or f".staging-{final_path.name}-",
            dir=str(final_path.parent),
        )
    )
    _harden_dir_permissions(staging_dir)
    return staging_dir


def publish_staged_directory(
    *,
    staging_dir: str | Path,
    final_dir: str | Path,
    populate: Callable[[], _T],
    validate_staging: Callable[[Path], None] | None = None,
    validate_result: Callable[[_T], None] | None = None,
    durability: PublicationDurability = "best-effort",
    cleanup_on_error: bool = True,
) -> DirectoryPublishResult[_T]:
    """Populate, validate, snapshot, and promote a staging directory."""

    staging_path = Path(staging_dir).expanduser()
    final_path = Path(final_dir).expanduser()
    staging_identity = _directory_identity_or_none(staging_path)
    try:
        payload = populate()
        if validate_staging is not None:
            validate_staging(staging_path)
        snapshot = snapshot_staging_directory(staging_path)
        if validate_result is not None:
            validate_result(payload)
        promoted = promote_staged_directory(
            staging_path,
            final_path,
            expected_snapshot=snapshot,
            expected_staging_identity=staging_identity,
            validate_staging=validate_staging,
            durability=durability,
        )
    except BaseException:
        if cleanup_on_error:
            discard_staging_directory(staging_path, expected_identity=staging_identity)
        raise
    return DirectoryPublishResult(final_dir=promoted, snapshot=snapshot, payload=payload)


def promote_staged_directory(
    staging_dir: str | Path,
    final_dir: str | Path,
    *,
    expected_snapshot: DirectorySnapshot | None = None,
    expected_staging_identity: DirectoryIdentity | None = None,
    validate_staging: Callable[[Path], None] | None = None,
    durability: PublicationDurability = "best-effort",
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
        raise ValueError("final directory parent does not exist")
    if final_path.exists() or final_path.is_symlink():
        raise ValueError(f"final directory already exists: {final_path.name}")

    with _exclusive_output_lock(final_path):
        if final_path.exists() or final_path.is_symlink():
            raise ValueError(f"final directory already exists: {final_path.name}")
        if validate_staging is not None:
            validate_staging(staging_path)
        if (
            expected_staging_identity is not None
            and _directory_identity_or_none(staging_path) != expected_staging_identity
        ):
            raise ValueError("validated staging_dir changed before promotion")
        if (
            expected_snapshot is not None
            and snapshot_staging_directory(staging_path) != expected_snapshot
        ):
            raise ValueError("staged files changed before promotion")
        if _directory_identity_or_none(staging_path.parent) != staging_parent_identity:
            raise ValueError("validated staging_dir parent changed before promotion")
        if _directory_identity_or_none(final_path.parent) != final_parent_identity:
            raise ValueError("final directory parent changed before promotion")
        _sync_staging_directory(staging_path, durability=durability)
        if (
            expected_snapshot is not None
            and snapshot_staging_directory(staging_path) != expected_snapshot
        ):
            raise ValueError("staged files changed before promotion")
        _rename_validated_staging_dir(
            staging_path,
            final_path,
            expected_staging_identity=expected_staging_identity,
            expected_staging_parent_identity=staging_parent_identity,
            expected_final_parent_identity=final_parent_identity,
        )
        _sync_directory_metadata(final_path.parent, durability=durability)
    return final_path


@contextmanager
def _exclusive_output_lock(final_path: Path) -> Iterator[None]:
    """Reserve one output destination for the duration of directory promotion."""

    lock_dir = final_path.parent / f".{final_path.name}.lock"
    try:
        lock_dir.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValueError(f"final directory is already being promoted: {final_path.name}") from exc
    try:
        yield
    finally:
        with suppress(OSError):
            lock_dir.rmdir()


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
        raise ValueError("final directory parent changed before promotion")
    if final_path.exists() or final_path.is_symlink():
        raise ValueError(f"final directory already exists: {final_path.name}")
    if (
        expected_staging_identity is not None
        and _directory_identity_or_none(staging_path) != expected_staging_identity
    ):
        raise ValueError("validated staging_dir changed before promotion")

    staging_path.rename(final_path)

    promoted_identity = _directory_identity_or_none(final_path)
    if expected_staging_identity is not None and promoted_identity != expected_staging_identity:
        raise ValueError("published directory identity does not match validated staging_dir")


def snapshot_staging_directory(staging_dir: str | Path) -> DirectorySnapshot:
    """Return names, sizes, and hashes for regular files in a staging directory."""

    path = Path(staging_dir).expanduser()
    if path.is_symlink():
        raise ValueError("staging_dir must not be a symlink")
    if not path.exists() or not path.is_dir():
        raise ValueError("staging_dir must be an existing directory")

    snapshot: list[tuple[str, int, str]] = []
    for entry in sorted(path.iterdir(), key=lambda item: item.name):
        if entry.is_symlink():
            raise ValueError(f"staging directory contains symlinked file: {entry.name}")
        if not entry.is_file():
            raise ValueError(f"staging directory contains unexpected non-file entry: {entry.name}")
        digest = hashlib.sha256()
        with entry.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        snapshot.append((entry.name, entry.stat().st_size, digest.hexdigest()))
    return tuple(snapshot)


def _sync_staging_directory(
    path: Path,
    *,
    durability: PublicationDurability,
) -> None:
    for entry in sorted(path.iterdir(), key=lambda item: item.name):
        if entry.is_symlink() or not entry.is_file():
            continue
        with entry.open("r+b" if os.name == "nt" else "rb") as handle:
            _sync_file(handle, durability=durability)
    _sync_directory_metadata(path, durability=durability)


def _sync_file(handle: BinaryIO, *, durability: PublicationDurability) -> None:
    try:
        os.fsync(handle.fileno())
    except OSError:
        if durability == "required":
            raise


def _sync_directory_metadata(path: Path, *, durability: PublicationDurability) -> None:
    try:
        sync_directory_metadata(path)
    except OSError:
        if durability == "required":
            raise


def sync_directory_metadata(path: str | Path) -> None:
    """Flush directory metadata where the platform exposes that operation."""

    path = Path(path).expanduser()
    if not _directory_metadata_sync_supported():
        return
    try:
        fd = _open_directory_fd(path)
    except OSError as exc:
        raise OSError(f"directory metadata sync unavailable: {path}") from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise OSError(f"directory metadata sync unavailable: {path}") from exc
    finally:
        os.close(fd)


def discard_staging_directory(
    staging_dir: str | Path | None,
    *,
    expected_identity: DirectoryIdentity | None = None,
) -> None:
    """Remove a staging directory after a failed publication attempt."""

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


def _open_directory_fd(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def _directory_metadata_sync_supported() -> bool:
    return os.name != "nt"


def _harden_dir_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    with suppress(OSError):
        path.chmod(0o700)
