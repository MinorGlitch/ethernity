from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def picker_root(paths: Sequence[Path]) -> Path:
    for path in paths:
        candidate = Path(path).expanduser()
        if candidate.is_dir():
            return candidate
        if candidate.parent.is_dir():
            return candidate.parent
    return Path.cwd()


def save_picker_parts(path: Path | None) -> tuple[Path, str]:
    if path is None:
        return Path.cwd(), ""
    candidate = Path(path).expanduser()
    if candidate.is_dir():
        return candidate, ""
    parent = candidate.parent if str(candidate.parent) != "." else Path.cwd()
    if not parent.is_dir():
        parent = Path.cwd()
    return parent, candidate.name


def split_file_dir_paths(paths: Sequence[Path]) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    directories: list[Path] = []
    for path in paths:
        if path.is_dir():
            directories.append(path)
        else:
            files.append(path)
    return files, directories
