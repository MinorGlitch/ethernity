"""Shared TOML text update helpers for config modules."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

_TABLE_HEADER_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$")


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
    """Set `key = value` inside a TOML table, appending table/key when missing."""

    line_ending = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()

    dotted_key = f"{table}.{key}"
    dotted_key_pattern = re.compile(rf"^(\s*){re.escape(dotted_key)}\s*=.*$")
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        match = dotted_key_pattern.match(line)
        if match is None:
            continue
        indent = match.group(1)
        comment = _extract_inline_comment(line)
        lines[index] = f"{indent}{dotted_key} = {value}{comment}"
        return line_ending.join(lines) + line_ending

    table_index: int | None = None
    table_end = len(lines)
    for index, line in enumerate(lines):
        header_name = _table_header_name(line)
        if header_name is None:
            continue
        if table_index is None and header_name == table:
            table_index = index
            continue
        if table_index is not None:
            table_end = index
            break

    if table_index is None:
        dotted_table_pattern = re.compile(rf"^\s*{re.escape(table)}\.[A-Za-z0-9_-]+\s*=")
        has_dotted_table_keys = any(
            not candidate.strip().startswith(("#", ";")) and dotted_table_pattern.match(candidate)
            for candidate in lines
        )
        if has_dotted_table_keys:
            lines.append(f"{dotted_key} = {value}")
            return line_ending.join(lines) + line_ending
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{table}]")
        lines.append(f"{key} = {value}")
        return line_ending.join(lines) + line_ending

    key_pattern = re.compile(rf"^(\s*){re.escape(key)}\s*=.*$")
    for index in range(table_index + 1, table_end):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        match = key_pattern.match(line)
        if match is None:
            continue
        indent = match.group(1)
        comment = _extract_inline_comment(line)
        lines[index] = f"{indent}{key} = {value}{comment}"
        return line_ending.join(lines) + line_ending

    lines.insert(table_end, f"{key} = {value}")
    return line_ending.join(lines) + line_ending


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
    in_double = False
    in_single = False
    escaped = False

    for index, ch in enumerate(line):
        if in_double:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_double = False
            continue
        if in_single:
            if ch == "'":
                in_single = False
            continue

        if ch == '"':
            in_double = True
            continue
        if ch == "'":
            in_single = True
            continue
        if ch == "#":
            return index

    return -1
