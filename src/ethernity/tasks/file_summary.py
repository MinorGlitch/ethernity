from __future__ import annotations

from pathlib import Path


def display_path(path: Path | str, *, max_chars: int = 56) -> str:
    if max_chars <= 0:
        return ""
    text = str(path)
    home = str(Path.home())
    if text == home:
        text = "~"
    elif text.startswith(f"{home}/"):
        text = f"~/{text[len(home) + 1 :]}"
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars

    separator = "/" if "/" in text else "\\"
    parts = text.split(separator)
    if len(parts) >= 3:
        prefix = separator.join(parts[:2])
        suffix = separator.join(parts[-2:])
        shortened = f"{prefix}{separator}...{separator}{suffix}"
        if len(shortened) <= max_chars:
            return shortened

    keep_total = max_chars - 3
    prefix_keep = keep_total // 2
    suffix_keep = keep_total - prefix_keep
    return f"{text[:prefix_keep]}...{text[-suffix_keep:]}"


def selected_paths_summary(
    *,
    input_paths: list[Path],
    input_dirs: list[Path],
    base_dir: Path | None,
    empty_label: str,
) -> str:
    count = len(input_paths) + len(input_dirs)
    if count == 0:
        return empty_label

    parts = [_selected_count_summary(input_paths, input_dirs)]
    size = _direct_file_size(input_paths, input_dirs)
    if size is None:
        parts.append("size available after backup planning")
    else:
        parts.append(format_bytes(size))
    parts.append(
        f"base folder: {display_path(base_dir)}"
        if base_dir is not None
        else "base folder: automatic"
    )
    return "; ".join(parts)


def format_bytes(value: int) -> str:
    if value == 1:
        return "1 byte"
    return f"{value} bytes"


def format_count(count: int, singular: str, plural: str | None = None) -> str:
    """Format a count without exposing placeholder grammar such as ``file(s)``."""
    noun = singular if count == 1 else plural or f"{singular}s"
    return f"{count} {noun}"


def _selected_count_summary(input_paths: list[Path], input_dirs: list[Path]) -> str:
    if not input_dirs:
        count = len(input_paths)
        noun = "file" if count == 1 else "files"
        return f"{count} {noun} selected"
    count = len(input_paths) + len(input_dirs)
    noun = "path" if count == 1 else "paths"
    return f"{count} {noun} selected"


def _direct_file_size(input_paths: list[Path], input_dirs: list[Path]) -> int | None:
    if input_dirs:
        return None
    total = 0
    for path in input_paths:
        try:
            if not path.is_file():
                return None
            total += path.stat().st_size
        except OSError:
            return None
    return total
