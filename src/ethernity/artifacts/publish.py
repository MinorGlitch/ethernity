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
import json
import os
import shutil
import stat
import tempfile
import uuid
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Generic, Iterator, Literal, TypeAlias, TypeVar

import portalocker

ArtifactSnapshot = tuple[tuple[str, int, str], ...]
DirectoryIdentity = tuple[int, int]
TRANSACTION_METADATA_NAME = ".transaction.json"
PublicationDurability: TypeAlias = Literal["required", "best-effort"]

_T = TypeVar("_T")


@dataclass(frozen=True)
class ArtifactPublishResult(Generic[_T]):
    """Result of a staged artifact publish transaction."""

    final_dir: Path
    snapshot: ArtifactSnapshot
    payload: _T


@dataclass(frozen=True)
class PublicationTransaction:
    """Authenticated-chain coordinates recorded beside staged publication artifacts."""

    root_hash: str
    expected_parent_hash: str | None
    new_index: int
    new_hash: str
    transaction_uuid: str | None = None

    def __post_init__(self) -> None:
        _require_hash(self.root_hash, label="root_hash")
        if self.expected_parent_hash is not None:
            _require_hash(self.expected_parent_hash, label="expected_parent_hash")
        _require_hash(self.new_hash, label="new_hash")
        if isinstance(self.new_index, bool) or not isinstance(self.new_index, int):
            raise ValueError("new_index must be an integer")
        if self.new_index < 0:
            raise ValueError("new_index must be non-negative")
        if self.transaction_uuid is not None:
            try:
                uuid.UUID(self.transaction_uuid)
            except (AttributeError, ValueError) as exc:
                raise ValueError("transaction_uuid must be a UUID") from exc

    def with_generated_uuid(self) -> PublicationTransaction:
        if self.transaction_uuid is not None:
            return self
        return PublicationTransaction(
            root_hash=self.root_hash,
            expected_parent_hash=self.expected_parent_hash,
            new_index=self.new_index,
            new_hash=self.new_hash,
            transaction_uuid=str(uuid.uuid4()),
        )


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
    lock_path: str | Path | None = None,
    transaction: PublicationTransaction | None = None,
    durability: PublicationDurability = "best-effort",
    cleanup_on_error: bool = True,
) -> ArtifactPublishResult[_T]:
    """Populate, validate, snapshot, and promote a staged artifact directory."""

    staging_path = Path(staging_dir).expanduser()
    final_path = Path(final_dir).expanduser()
    staging_identity = _directory_identity_or_none(staging_path)
    resolved_transaction = transaction.with_generated_uuid() if transaction is not None else None
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
            lock_path=lock_path,
            expected_transaction=resolved_transaction,
            durability=durability,
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
    lock_path: str | Path | None = None,
    expected_transaction: PublicationTransaction | None = None,
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
        raise ValueError("final artifact directory parent does not exist")
    if final_path.exists() or final_path.is_symlink():
        raise ValueError(f"final artifact directory already exists: {final_path.name}")

    lock = (
        exclusive_advisory_lock(lock_path, operation_name=final_path.name)
        if lock_path is not None
        else _exclusive_output_lock(final_path)
    )
    with lock:
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
        if (
            expected_transaction is not None
            and not (staging_path / TRANSACTION_METADATA_NAME).exists()
        ):
            transaction_snapshot = expected_snapshot or snapshot_artifact_dir(staging_path)
            write_transaction_metadata(
                staging_path,
                expected_transaction,
                snapshot=transaction_snapshot,
                durability=durability,
            )
            if expected_snapshot is None:
                expected_snapshot = transaction_snapshot
        _sync_staged_artifact_dir(staging_path, durability=durability)
        if (
            expected_snapshot is not None
            and snapshot_artifact_dir(staging_path) != expected_snapshot
        ):
            raise ValueError("validated staging_dir artifacts changed before promotion")
        if expected_transaction is not None:
            validate_transaction_metadata(
                staging_path,
                expected=expected_transaction,
                expected_snapshot=expected_snapshot,
            )
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
    """Preserve the temporary per-output lock used by non-extension publishers."""

    lock_dir = final_path.parent / f".{final_path.name}.lock"
    try:
        lock_dir.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValueError(
            f"final artifact directory is already being promoted: {final_path.name}"
        ) from exc
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
        raise ValueError("final artifact directory parent changed before promotion")
    if final_path.exists() or final_path.is_symlink():
        raise ValueError(f"final artifact directory already exists: {final_path.name}")
    if (
        expected_staging_identity is not None
        and _directory_identity_or_none(staging_path) != expected_staging_identity
    ):
        raise ValueError("validated staging_dir changed before promotion")

    staging_path.rename(final_path)

    promoted_identity = _directory_identity_or_none(final_path)
    if expected_staging_identity is not None and promoted_identity != expected_staging_identity:
        raise ValueError(
            "promoted artifact directory identity does not match validated staging_dir"
        )


def snapshot_artifact_dir(staging_dir: str | Path) -> ArtifactSnapshot:
    """Return a content fingerprint for direct regular files in a staged artifact directory."""

    path = Path(staging_dir).expanduser()
    if path.is_symlink():
        raise ValueError("staging_dir must not be a symlink")
    if not path.exists() or not path.is_dir():
        raise ValueError("staging_dir must be an existing directory")

    snapshot: list[tuple[str, int, str]] = []
    for entry in sorted(path.iterdir(), key=lambda item: item.name):
        if entry.name == TRANSACTION_METADATA_NAME:
            continue
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


def write_transaction_metadata(
    staging_dir: str | Path,
    transaction: PublicationTransaction,
    *,
    snapshot: ArtifactSnapshot,
    durability: PublicationDurability = "required",
) -> Path:
    """Durably record transaction identity and the non-self-referential artifact snapshot."""

    path = Path(staging_dir).expanduser()
    resolved = transaction.with_generated_uuid()
    payload = {
        "version": 1,
        "transaction_uuid": resolved.transaction_uuid,
        "root_hash": resolved.root_hash,
        "expected_parent_hash": resolved.expected_parent_hash,
        "new_index": resolved.new_index,
        "new_hash": resolved.new_hash,
        "artifact_snapshot": [list(item) for item in snapshot],
    }
    metadata_path = path / TRANSACTION_METADATA_NAME
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(metadata_path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            handle.write(b"\n")
            handle.flush()
            _sync_file(handle, durability=durability)
    except BaseException:
        metadata_path.unlink(missing_ok=True)
        raise
    _sync_directory_metadata(path, durability=durability)
    return metadata_path


def read_transaction_metadata(
    directory: str | Path,
) -> tuple[PublicationTransaction, ArtifactSnapshot]:
    """Read and strictly validate a staged or promoted transaction record."""

    metadata_path = Path(directory).expanduser() / TRANSACTION_METADATA_NAME
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid publication transaction metadata: {metadata_path}") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "transaction_uuid",
        "root_hash",
        "expected_parent_hash",
        "new_index",
        "new_hash",
        "artifact_snapshot",
    }:
        raise ValueError("publication transaction metadata has invalid fields")
    if raw["version"] != 1:
        raise ValueError("unsupported publication transaction metadata version")
    transaction = PublicationTransaction(
        root_hash=raw["root_hash"],
        expected_parent_hash=raw["expected_parent_hash"],
        new_index=raw["new_index"],
        new_hash=raw["new_hash"],
        transaction_uuid=raw["transaction_uuid"],
    )
    snapshot = _parse_artifact_snapshot(raw["artifact_snapshot"])
    return transaction, snapshot


def validate_transaction_metadata(
    directory: str | Path,
    *,
    expected: PublicationTransaction,
    expected_snapshot: ArtifactSnapshot | None,
) -> None:
    actual, recorded_snapshot = read_transaction_metadata(directory)
    if (
        actual.root_hash != expected.root_hash
        or actual.expected_parent_hash != expected.expected_parent_hash
        or actual.new_index != expected.new_index
        or actual.new_hash != expected.new_hash
        or (
            expected.transaction_uuid is not None
            and actual.transaction_uuid != expected.transaction_uuid
        )
    ):
        raise ValueError("publication transaction metadata changed before promotion")
    if expected_snapshot is not None and recorded_snapshot != expected_snapshot:
        raise ValueError("publication transaction snapshot changed before promotion")


def _parse_artifact_snapshot(value: object) -> ArtifactSnapshot:
    if not isinstance(value, list):
        raise ValueError("publication transaction artifact_snapshot must be a list")
    parsed: list[tuple[str, int, str]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not isinstance(item[0], str)
            or isinstance(item[1], bool)
            or not isinstance(item[1], int)
            or not isinstance(item[2], str)
        ):
            raise ValueError("publication transaction artifact_snapshot entry is invalid")
        name, size, digest = item
        if not name or Path(name).name != name or name == TRANSACTION_METADATA_NAME:
            raise ValueError("publication transaction artifact_snapshot filename is invalid")
        if size < 0:
            raise ValueError("publication transaction artifact_snapshot size is invalid")
        _require_hash(digest, label="artifact_snapshot hash")
        parsed.append((name, size, digest))
    if parsed != sorted(parsed, key=lambda entry: entry[0]):
        raise ValueError("publication transaction artifact_snapshot must be sorted")
    if len({entry[0] for entry in parsed}) != len(parsed):
        raise ValueError("publication transaction artifact_snapshot contains duplicate filenames")
    return tuple(parsed)


def _require_hash(value: object, *, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be 64 lowercase hex characters")
    if value.lower() != value or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be 64 lowercase hex characters")


def _sync_staged_artifact_dir(
    path: Path,
    *,
    durability: PublicationDurability,
) -> None:
    for entry in sorted(path.iterdir(), key=lambda item: item.name):
        if entry.is_symlink() or not entry.is_file():
            continue
        with entry.open("rb") as handle:
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
    if os.name == "nt":
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


@contextmanager
def exclusive_advisory_lock(
    path: str | Path,
    *,
    operation_name: str = "publication",
) -> Iterator[BinaryIO]:
    """Hold a process-owned exclusive lock on a persistent regular lock file."""

    path = Path(path).expanduser()
    handle = _open_advisory_lock_file(path)
    try:
        try:
            portalocker.lock(
                handle,
                portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
            )
        except portalocker.exceptions.LockException as exc:
            raise ValueError(f"{operation_name} is already in progress") from exc
        yield handle
    finally:
        with suppress(portalocker.exceptions.LockException):
            portalocker.unlock(handle)
        handle.close()


def _open_advisory_lock_file(path: Path) -> BinaryIO:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ValueError(f"advisory lock path must be a persistent regular file: {path}") from exc
    try:
        opened = os.fstat(fd)
        current = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(current.st_mode):
            raise ValueError(f"advisory lock path must be a persistent regular file: {path}")
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError(f"advisory lock path changed while it was opened: {path}")
        return os.fdopen(fd, "r+b")
    except BaseException:
        os.close(fd)
        raise


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


def _open_directory_fd(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def _harden_dir_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    with suppress(OSError):
        path.chmod(0o700)
