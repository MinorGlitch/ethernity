#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import sys

def _ensure_directory(path: str | Path, *, exist_ok: bool) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=exist_ok)
    return directory


def _ensure_output_dir(output_dir: str | None, doc_id_hex: str) -> str:
    directory = output_dir or f"backup-{doc_id_hex}"
    _ensure_directory(directory, exist_ok=False)
    return directory


def _safe_join(base: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe output path: {relative}")
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_output(path: str | None, data: bytes, *, quiet: bool) -> None:
    if path:
        with open(path, "wb") as handle:
            handle.write(data)
        if not quiet:
            print(f"- wrote {path}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(data)


def _write_recovered_outputs(
    output_path: str | None,
    entries: Sequence[tuple[object, bytes]],
    *,
    quiet: bool,
) -> None:
    if not entries:
        raise ValueError("no payloads to write")
    if output_path:
        if len(entries) == 1:
            _write_output(output_path, entries[0][1], quiet=quiet)
            return
        base_dir = _ensure_directory(output_path, exist_ok=True)
        for entry, data in entries:
            path = _safe_join(base_dir, getattr(entry, "path", "payload.bin"))
            _write_output(str(path), data, quiet=quiet)
        return

    if len(entries) == 1:
        _write_output(None, entries[0][1], quiet=quiet)
        return

    raise ValueError("multiple files require --output to specify a directory")
