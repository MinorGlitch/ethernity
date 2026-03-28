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

"""Write backup and recovery outputs to disk or stdout safely."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unicodedata
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from ethernity.cli.shared.paths import expanduser_cli_path
from ethernity.core.validation import normalize_path


def _is_posix() -> bool:
    return os.name == "posix"


def _harden_dir_permissions(path: Path) -> None:
    """Apply restrictive directory permissions on POSIX systems."""

    if not _is_posix():
        return
    try:
        path.chmod(0o700)
    except OSError:
        return


def _harden_file_permissions(path: Path) -> None:
    """Apply restrictive file permissions on POSIX systems."""

    if not _is_posix():
        return
    try:
        path.chmod(0o600)
    except OSError:
        return


def _ensure_directory(path: str | Path, *, exist_ok: bool) -> Path:
    """Create an output directory and harden its permissions."""

    directory = Path(expanduser_cli_path(path, preserve_stdin=False) or "")
    existed = directory.exists()
    directory.mkdir(parents=True, exist_ok=exist_ok, mode=0o700)
    if not existed:
        _harden_dir_permissions(directory)
    return directory


def _ensure_output_dir(
    output_dir: str | None,
    doc_id_hex: str,
    *,
    existing_directory_is_parent: bool = False,
) -> str:
    """Create a fresh backup output directory or raise if it already exists."""

    directory = expanduser_cli_path(output_dir, preserve_stdin=False) or f"backup-{doc_id_hex}"
    normalized = Path(directory)
    if existing_directory_is_parent and normalized.is_dir():
        directory = str(normalized / f"backup-{doc_id_hex}")
    try:
        _ensure_directory(directory, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError(
            f"output directory already exists: {directory}; "
            "use a different --output-dir path or remove the existing directory"
        ) from exc
    return directory


def _prepare_output_dir(
    output_dir: str | None,
    doc_id_hex: str,
    *,
    prefix: str,
    existing_directory_is_parent: bool = False,
) -> tuple[str, str]:
    """Prepare sibling staging and final output directories."""

    final_dir = expanduser_cli_path(output_dir, preserve_stdin=False) or f"{prefix}-{doc_id_hex}"
    normalized = Path(final_dir)
    if existing_directory_is_parent and normalized.is_dir():
        normalized = normalized / f"{prefix}-{doc_id_hex}"
        final_dir = str(normalized)
    if normalized.exists():
        raise ValueError(
            f"output directory already exists: {final_dir}; "
            "use a different --output-dir path or remove the existing directory"
        )
    _ensure_directory(normalized.parent, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{normalized.name}.tmp-", dir=str(normalized.parent))
    )
    _harden_dir_permissions(staging_dir)
    return str(normalized), str(staging_dir)


def _commit_prepared_output_dir(staging_dir: str | Path, final_dir: str | Path) -> str:
    """Promote a staged output directory into place."""

    staging_path = Path(staging_dir)
    final_path = Path(final_dir)
    staging_path.replace(final_path)
    return str(final_path)


def _discard_prepared_output_dir(staging_dir: str | Path | None) -> None:
    """Remove a staged output directory when a render fails."""

    if staging_dir is None:
        return
    shutil.rmtree(staging_dir, ignore_errors=True)


def _safe_join(base: Path, relative: str) -> Path:
    """Join a manifest path under a base directory after path normalization checks."""

    relative = normalize_path(relative, label="output path")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe output path: {relative}")
    path = base / rel
    _ensure_directory(path.parent, exist_ok=True)
    return path


def _write_output(path: str | None, data: bytes) -> str | None:
    """Write bytes to a file path or stdout when no path is provided."""

    if path:
        normalized = Path(expanduser_cli_path(path, preserve_stdin=False) or "")
        _ensure_directory(normalized.parent, exist_ok=True)
        _write_atomic_file(normalized, data)
        return str(normalized)

    sys.stdout.buffer.write(data)
    return None


def _single_entry_uses_directory_output(
    output_path: str | None,
    *,
    single_entry_output_is_directory: bool = False,
) -> bool:
    """Return whether a single recovered file should be written under a directory."""

    if output_path is None:
        return False
    if single_entry_output_is_directory:
        return True
    normalized = Path(expanduser_cli_path(output_path, preserve_stdin=False) or "")
    try:
        return normalized.is_dir()
    except OSError:
        return False


def _write_recovered_outputs(
    output_path: str | None,
    entries: Sequence[tuple[object, bytes]],
    *,
    single_entry_output_is_directory: bool = False,
    on_entry_written: Callable[[object, bytes, str, int, int], None] | None = None,
) -> list[str]:
    """Write recovered manifest entries to a file, directory, or stdout."""

    if not entries:
        raise ValueError("no payloads to write")
    if output_path:
        directory_mode = _single_entry_uses_directory_output(
            output_path,
            single_entry_output_is_directory=single_entry_output_is_directory,
        )
        if len(entries) == 1 and not directory_mode:
            path = _write_output(output_path, entries[0][1])
            if on_entry_written is not None:
                resolved_path = path or output_path
                on_entry_written(entries[0][0], entries[0][1], resolved_path, 1, 1)
            return [path or output_path]
        base_dir = Path(expanduser_cli_path(output_path, preserve_stdin=False) or "")
        return _write_recovered_directory_outputs(
            base_dir,
            entries,
            on_entry_written=on_entry_written,
        )

    if len(entries) == 1:
        _write_output(None, entries[0][1])
        if on_entry_written is not None:
            on_entry_written(entries[0][0], entries[0][1], "-", 1, 1)
        return []

    raise ValueError("multiple files require --output to specify a directory")


def _write_atomic_file(path: Path, data: bytes) -> None:
    """Write a file atomically in place."""

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        _harden_file_permissions(temp_path)
        temp_path.replace(path)
        _harden_file_permissions(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _write_recovered_directory_outputs(
    base_dir: Path,
    entries: Sequence[tuple[object, bytes]],
    *,
    on_entry_written: Callable[[object, bytes, str, int, int], None] | None,
) -> list[str]:
    """Write recovered directory-style outputs via staging with rollback."""

    destination_exists = base_dir.exists()
    if destination_exists and not base_dir.is_dir():
        raise ValueError(f"output path is not a directory: {base_dir}")
    _ensure_directory(base_dir.parent, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{base_dir.name or 'recover'}.tmp-", dir=str(base_dir.parent))
    )
    _harden_dir_permissions(staging_dir)
    _validate_recovered_output_paths(
        entries, case_sensitive=_is_directory_case_sensitive(staging_dir)
    )
    staged_records: list[tuple[object, bytes, str, Path]] = []
    total = len(entries)
    try:
        for entry, data in entries:
            relative_path = getattr(entry, "path", "payload.bin")
            staged_path = _safe_join(staging_dir, relative_path)
            _write_atomic_file(staged_path, data)
            staged_records.append((entry, data, relative_path, staged_path))
        if not destination_exists:
            staging_dir.replace(base_dir)
            written_paths = [
                str(base_dir / relative_path)
                for _entry, _data, relative_path, _path in staged_records
            ]
            if on_entry_written is not None:
                for index, (entry, data, _relative_path, _path) in enumerate(
                    staged_records, start=1
                ):
                    on_entry_written(entry, data, written_paths[index - 1], index, total)
            return written_paths
        return _commit_recovered_directory_outputs(
            base_dir=base_dir,
            staging_dir=staging_dir,
            staged_records=staged_records,
            total=total,
            on_entry_written=on_entry_written,
        )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _validate_recovered_output_paths(
    entries: Sequence[tuple[object, bytes]],
    *,
    case_sensitive: bool,
) -> None:
    """Reject output paths that would collide on the target filesystem."""

    if case_sensitive:
        return
    seen_paths: dict[tuple[str, ...], str] = {}
    for entry, _data in entries:
        relative_path = normalize_path(getattr(entry, "path", "payload.bin"), label="output path")
        key = tuple(
            unicodedata.normalize("NFC", part).casefold() for part in relative_path.split("/")
        )
        previous = seen_paths.get(key)
        if previous is None:
            seen_paths[key] = relative_path
            continue
        if previous != relative_path:
            raise ValueError(
                f"output paths collide on this filesystem: {previous!r} vs {relative_path!r}"
            )


def _is_directory_case_sensitive(directory: Path) -> bool:
    """Return whether the target directory distinguishes file names by case."""

    probe_name = f".CaseSensitivityProbe-{uuid.uuid4().hex}"
    probe_path = directory / probe_name
    alternate_path = directory / probe_name.swapcase()
    try:
        probe_path.write_bytes(b"")
        return not alternate_path.exists()
    except OSError:
        return os.name != "nt"
    finally:
        probe_path.unlink(missing_ok=True)


def _commit_recovered_directory_outputs(
    base_dir: Path,
    staging_dir: Path,
    staged_records: Sequence[tuple[object, bytes, str, Path]],
    *,
    total: int,
    on_entry_written: Callable[[object, bytes, str, int, int], None] | None,
) -> list[str]:
    """Publish the staged recovered tree as the authoritative destination."""

    fd, backup_name = tempfile.mkstemp(prefix=f".{base_dir.name}.bak-", dir=str(base_dir.parent))
    os.close(fd)
    backup_dir = Path(backup_name)
    backup_dir.unlink(missing_ok=True)
    written_paths = [
        str(base_dir / relative_path) for _entry, _data, relative_path, _path in staged_records
    ]
    try:
        base_dir.replace(backup_dir)
        staging_dir.replace(base_dir)
    except Exception:
        if backup_dir.exists() and not base_dir.exists():
            backup_dir.replace(base_dir)
        raise
    finally:
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)

    if on_entry_written is not None:
        for index, (entry, data, _relative_path, _path) in enumerate(staged_records, start=1):
            on_entry_written(entry, data, written_paths[index - 1], index, total)
    return written_paths
