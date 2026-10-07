"""Update TOML text while preserving unrelated configuration."""

from __future__ import annotations

import re
import tempfile
import tomllib
from pathlib import Path

_TABLE_HEADER_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$")


def load_toml(path: Path) -> dict[str, object]:
    """Load a TOML file into a raw dictionary."""

    with path.open("rb") as handle:
        return tomllib.load(handle)


def write_text_atomic(path: Path, text: str) -> None:
    """Atomically replace a text file in place."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.tmp-",
        delete=False,
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    try:
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def toml_quote(value: str) -> str:
    """Return a TOML basic string literal."""

    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def upsert_table_key(text: str, *, table: str, key: str, value: str) -> str:
    """Set a key while preserving table style, indentation, comments, and line endings."""

    line_ending = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    dotted_key = f"{table}.{key}"
    if _replace_assignment(lines, key=dotted_key, value=value, start=0, end=len(lines)):
        return line_ending.join(lines) + line_ending

    table_index, table_end = _table_span(lines, table)
    if table_index is None:
        _append_table_assignment(lines, table=table, key=key, value=value)
    elif not _replace_assignment(lines, key=key, value=value, start=table_index + 1, end=table_end):
        lines.insert(table_end, f"{key} = {value}")
    return line_ending.join(lines) + line_ending


def _replace_assignment(lines: list[str], *, key: str, value: str, start: int, end: int) -> bool:
    pattern = re.compile(rf"^(\s*){re.escape(key)}\s*=.*$")
    for index in range(start, end):
        line = lines[index]
        if line.strip().startswith(("#", ";")):
            continue
        match = pattern.match(line)
        if match is not None:
            lines[index] = f"{match.group(1)}{key} = {value}{_extract_inline_comment(line)}"
            return True
    return False


def _table_span(lines: list[str], table: str) -> tuple[int | None, int]:
    table_index: int | None = None
    for index, line in enumerate(lines):
        header = _table_header_name(line)
        if header is None:
            continue
        if table_index is not None:
            return table_index, index
        if header == table:
            table_index = index
    return table_index, len(lines)


def _append_table_assignment(lines: list[str], *, table: str, key: str, value: str) -> None:
    pattern = re.compile(rf"^\s*{re.escape(table)}\.[A-Za-z0-9_-]+\s*=")
    if any(not line.strip().startswith(("#", ";")) and pattern.match(line) for line in lines):
        lines.append(f"{table}.{key} = {value}")
        return
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend((f"[{table}]", f"{key} = {value}"))


def _table_header_name(line: str) -> str | None:
    match = _TABLE_HEADER_RE.match(line)
    if match is None:
        return None
    return match.group(1).strip()


def _extract_inline_comment(line: str) -> str:
    comment_start = _find_unquoted_hash(line)
    if comment_start == -1:
        return ""
    return " " + line[comment_start:].strip()


def _find_unquoted_hash(line: str) -> int:
    quote: str | None = None
    escaped = False
    for index, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if quote is not None:
            if ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in {"'", '"'}:
            quote = ch
        elif ch == "#":
            return index
    return -1
