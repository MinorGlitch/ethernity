from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from os.path import commonprefix
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PickerPathCompletion:
    value: str
    matches: tuple[str, ...] = ()


def resolve_picker_path(value: str, root: Path) -> Path:
    """Resolve entered paths relative to the folder shown in the picker."""
    return _entered_picker_path(value, root).resolve(strict=False)


def _entered_picker_path(value: str, root: Path) -> Path:
    value = value.strip()
    if not value:
        raise ValueError("Enter a file or folder path.")
    if "\x00" in value:
        raise ValueError("The path contains an invalid null character.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path


def complete_picker_path(
    value: str,
    root: Path,
    *,
    include_files: bool,
) -> PickerPathCompletion:
    """Complete one path component, retaining relative and home-directory spelling."""
    value = value.strip()
    candidate = _entered_picker_path(value or ".", root)
    if value and candidate.is_dir() and not value.endswith("/"):
        return PickerPathCompletion(f"{value}/")
    if not value or value.endswith("/"):
        parent = candidate
        prefix = ""
        entered_parent = value
    else:
        parent = candidate.parent
        prefix = candidate.name
        entered_parent = value[: -len(Path(value).name)]
    if not parent.is_dir():
        raise ValueError("The containing folder does not exist.")
    entries = sorted(
        (
            child
            for child in parent.iterdir()
            if child.name.startswith(prefix) and (include_files or child.is_dir())
        ),
        key=lambda child: child.name,
    )
    matches = tuple(f"{child.name}/" if child.is_dir() else child.name for child in entries)
    if not matches:
        return PickerPathCompletion(value)
    completed = matches[0] if len(matches) == 1 else commonprefix(matches)
    return PickerPathCompletion(f"{entered_parent}{completed}", matches)


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
