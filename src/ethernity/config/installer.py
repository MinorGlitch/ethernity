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

"""Resolve and initialize user-facing config and template paths."""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from ..core.app_paths import (
    DEFAULT_CONFIG_FILENAME,
    user_config_dir_path,
    user_config_file_path,
    user_templates_design_path,
    user_templates_root_path,
)
from ..version import get_ethernity_version

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = PACKAGE_ROOT / "templates/sentinel/main_document.html.j2"
DEFAULT_RECOVERY_TEMPLATE_PATH = PACKAGE_ROOT / "templates/sentinel/recovery_document.html.j2"
DEFAULT_SHARD_TEMPLATE_PATH = PACKAGE_ROOT / "templates/sentinel/shard_document.html.j2"
DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH = (
    PACKAGE_ROOT / "templates/sentinel/signing_key_shard_document.html.j2"
)
DEFAULT_KIT_TEMPLATE_PATH = PACKAGE_ROOT / "templates/sentinel/kit_document.html.j2"
DEFAULT_TEMPLATE_STYLE = DEFAULT_TEMPLATE_PATH.parent.name
SUPPORTED_TEMPLATE_DESIGNS = (
    "archive",
    "forge",
    "ledger",
    "maritime",
    "sentinel",
)
TEMPLATE_FILENAMES = (
    DEFAULT_TEMPLATE_PATH.name,
    DEFAULT_RECOVERY_TEMPLATE_PATH.name,
    DEFAULT_SHARD_TEMPLATE_PATH.name,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH.name,
    DEFAULT_KIT_TEMPLATE_PATH.name,
)
DEFAULT_PAPER_SIZE = "A4"
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config/config.toml"

_DOTTED_BACKUP_KEY_RE = re.compile(r"^\s*defaults\.backup\.[A-Za-z0-9_-]+\s*=", re.MULTILINE)
_TABLE_HEADER_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$")
_TEMPLATE_SYNC_STATE_FILENAME = ".template_sync_state_v1.json"
_TEMPLATE_SYNC_STATE_VERSION = 1
_FIRST_RUN_ONBOARDING_MARKER_FILENAME = ".first_run_onboarding_v1.done"
_FIRST_RUN_ONBOARDING_MARKER_VERSION = 1

ONBOARDING_FIELD_TEMPLATE_DESIGN = "template_design"
ONBOARDING_FIELD_PAGE_SIZE = "page_size"
ONBOARDING_FIELD_BACKUP_OUTPUT_DIR = "backup_output_dir"
ONBOARDING_FIELD_QR_CHUNK_SIZE = "qr_chunk_size"
ONBOARDING_FIELD_QR_ERROR_CORRECTION = "qr_error_correction"
ONBOARDING_FIELD_SHARDING = "sharding"
ONBOARDING_FIELD_PAYLOAD_CODEC = "payload_codec"
ONBOARDING_FIELD_QR_PAYLOAD_CODEC = "qr_payload_codec"


@dataclass(frozen=True)
class ConfigPaths:
    """Resolved user config and template locations."""

    user_config_dir: Path
    user_templates_root: Path
    user_templates_dir: Path
    user_config_path: Path
    user_template_paths: dict[str, Path]
    user_required_files: tuple[Path, ...]


ConfigMigration = Callable[[str], str | None]


@dataclass(frozen=True)
class ConfigMigrationStep:
    """A single text-based migration applied to user config files."""

    migration_id: str
    apply: ConfigMigration


PayloadCodec = Literal["auto", "raw", "gzip"]
QrPayloadCodec = Literal["raw", "base64"]
QrErrorCorrection = Literal["L", "M", "Q", "H"]
PageSize = Literal["A4", "LETTER"]
SigningKeyMode = Literal["embedded", "sharded"]


def _build_paths() -> ConfigPaths:
    """Construct the derived config/template path set."""

    user_config_dir = user_config_dir_path()
    user_templates_root = user_templates_root_path()
    user_templates_dir = user_templates_design_path(DEFAULT_TEMPLATE_STYLE)
    user_config_path = user_config_file_path(DEFAULT_CONFIG_FILENAME)
    user_template_paths = {
        "main": user_templates_dir / DEFAULT_TEMPLATE_PATH.name,
        "recovery": user_templates_dir / DEFAULT_RECOVERY_TEMPLATE_PATH.name,
        "shard": user_templates_dir / DEFAULT_SHARD_TEMPLATE_PATH.name,
        "signing_key_shard": user_templates_dir / DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH.name,
        "kit": user_templates_dir / DEFAULT_KIT_TEMPLATE_PATH.name,
    }
    user_required_files = tuple([user_config_path, *user_template_paths.values()])
    return ConfigPaths(
        user_config_dir=user_config_dir,
        user_templates_root=user_templates_root,
        user_templates_dir=user_templates_dir,
        user_config_path=user_config_path,
        user_template_paths=user_template_paths,
        user_required_files=user_required_files,
    )


def list_template_designs() -> dict[str, Path]:
    """List supported template designs, preferring valid user overrides."""

    package_root = PACKAGE_ROOT / "templates"
    if not package_root.exists():
        return {}

    paths = _build_paths()
    designs: dict[str, Path] = {}
    for design_name in SUPPORTED_TEMPLATE_DESIGNS:
        entry = package_root / design_name
        if not entry.is_dir():
            continue
        if not _is_template_design_dir(entry):
            continue
        user_override = paths.user_templates_root / design_name
        if user_override.is_dir() and _is_template_design_dir(user_override):
            designs[design_name] = user_override
        else:
            designs[design_name] = entry
    return designs


def resolve_template_design_path(design: str) -> Path:
    """Resolve a template design name to a concrete directory path."""

    name = design.strip()
    if not name:
        raise ValueError("template design cannot be empty")
    designs = list_template_designs()
    if name in designs:
        return designs[name]
    lowered = name.lower()
    for candidate, path in designs.items():
        if candidate.lower() == lowered:
            return path
    raise ValueError(f"unknown template design: {design}")


def _is_template_design_dir(path: Path) -> bool:
    """Return whether a directory contains the required template files."""

    return all((path / filename).is_file() for filename in TEMPLATE_FILENAMES)


def init_user_config() -> Path:
    """Ensure user config/templates exist and return the user config directory."""

    paths = _build_paths()
    if not _ensure_user_config(paths):
        raise OSError(f"unable to create config dir at {paths.user_config_dir}")
    return paths.user_config_dir


def user_config_needs_init() -> bool:
    """Return whether any required user config/template files are missing."""

    paths = _build_paths()
    return any(not path.exists() for path in paths.user_required_files)


def resolve_config_path(path: str | Path | None = None) -> Path:
    """Resolve the TOML config path used by the application."""
    if path:
        return Path(path).expanduser()

    paths = _build_paths()
    if _ensure_user_config(paths) and paths.user_config_path.exists():
        return paths.user_config_path
    return DEFAULT_CONFIG_PATH


def first_run_onboarding_marker_path() -> Path:
    """Return the marker file path used to gate first-run onboarding prompts."""

    return user_config_dir_path() / _FIRST_RUN_ONBOARDING_MARKER_FILENAME


def first_run_onboarding_needed() -> bool:
    """Return whether first-run onboarding should be offered."""

    return not first_run_onboarding_marker_path().exists()


def first_run_onboarding_configured_fields() -> frozenset[str]:
    """Return onboarding-configured field identifiers from marker metadata."""

    marker_path = first_run_onboarding_marker_path()
    if not marker_path.exists():
        return frozenset()
    try:
        payload = marker_path.read_text(encoding="utf-8").strip()
    except OSError:
        return frozenset()
    if not payload:
        return frozenset()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(parsed, dict):
        return frozenset()
    values = parsed.get("configured_fields")
    if not isinstance(values, list):
        return frozenset()
    configured: set[str] = set()
    for value in values:
        if isinstance(value, str) and value.strip():
            configured.add(value.strip())
    return frozenset(configured)


def mark_first_run_onboarding_complete(*, configured_fields: set[str] | None = None) -> Path:
    """Persist the first-run onboarding completion marker and return its path."""

    marker_path = first_run_onboarding_marker_path()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    existing_fields = set(first_run_onboarding_configured_fields())
    merged_fields = (
        existing_fields if configured_fields is None else existing_fields | configured_fields
    )
    payload = {
        "version": _FIRST_RUN_ONBOARDING_MARKER_VERSION,
        "configured_fields": sorted(merged_fields),
    }
    marker_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return marker_path


def apply_first_run_defaults(
    path: str | Path | None,
    *,
    design: str,
    payload_codec: PayloadCodec,
    qr_payload_codec: QrPayloadCodec,
    qr_error_correction: QrErrorCorrection,
    page_size: PageSize,
    backup_output_dir: str | None,
    qr_chunk_size: int,
    shard_threshold: int | None,
    shard_count: int | None,
    signing_key_mode: SigningKeyMode | None,
    signing_key_shard_threshold: int | None = None,
    signing_key_shard_count: int | None = None,
) -> Path:
    """Apply first-run default selections into the resolved config file."""

    _ = resolve_template_design_path(design)
    if payload_codec not in {"auto", "raw", "gzip"}:
        raise ValueError("payload_codec must be 'auto', 'raw', or 'gzip'")
    if qr_payload_codec not in {"raw", "base64"}:
        raise ValueError("qr_payload_codec must be 'raw' or 'base64'")
    if qr_error_correction not in {"L", "M", "Q", "H"}:
        raise ValueError("qr_error_correction must be one of 'L', 'M', 'Q', or 'H'")
    if page_size not in {"A4", "LETTER"}:
        raise ValueError("page_size must be 'A4' or 'LETTER'")
    if qr_chunk_size <= 0:
        raise ValueError("qr_chunk_size must be a positive integer")

    if (shard_threshold is None) != (shard_count is None):
        raise ValueError("shard_threshold and shard_count must be set together")
    if shard_threshold is not None and shard_count is not None:
        if shard_threshold < 1:
            raise ValueError("shard_threshold must be >= 1")
        if shard_threshold > 255:
            raise ValueError("shard_threshold must be <= 255")
        if shard_count < shard_threshold:
            raise ValueError("shard_count must be >= shard_threshold")
        if shard_count > 255:
            raise ValueError("shard_count must be <= 255")

    if signing_key_mode not in {None, "embedded", "sharded"}:
        raise ValueError("signing_key_mode must be 'embedded', 'sharded', or None")
    if signing_key_mode == "sharded" and (shard_threshold is None or shard_count is None):
        raise ValueError("signing_key_mode='sharded' requires passphrase sharding")
    if (signing_key_shard_threshold is None) != (signing_key_shard_count is None):
        raise ValueError(
            "signing_key_shard_threshold and signing_key_shard_count must be set together"
        )
    if signing_key_shard_threshold is not None and signing_key_shard_count is not None:
        if signing_key_mode != "sharded":
            raise ValueError("signing key shard counts require signing_key_mode='sharded'")
        if signing_key_shard_threshold < 1:
            raise ValueError("signing_key_shard_threshold must be >= 1")
        if signing_key_shard_threshold > 255:
            raise ValueError("signing_key_shard_threshold must be <= 255")
        if signing_key_shard_count < signing_key_shard_threshold:
            raise ValueError("signing_key_shard_count must be >= signing_key_shard_threshold")
        if signing_key_shard_count > 255:
            raise ValueError("signing_key_shard_count must be <= 255")

    config_path = resolve_config_path(path)
    original = config_path.read_text(encoding="utf-8")
    line_ending = "\r\n" if "\r\n" in original else "\n"

    updated = original
    updated = _upsert_table_key(updated, table="templates", key="default_name", value=f'"{design}"')
    for section in (
        "template",
        "recovery_template",
        "shard_template",
        "signing_key_shard_template",
        "kit_template",
    ):
        updated = _upsert_table_key(updated, table=section, key="name", value=f'"{design}"')
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="payload_codec",
        value=f'"{payload_codec}"',
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="qr_payload_codec",
        value=f'"{qr_payload_codec}"',
    )
    updated = _upsert_table_key(updated, table="qr", key="error", value=f'"{qr_error_correction}"')
    updated = _upsert_table_key(updated, table="page", key="size", value=f'"{page_size}"')
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="output_dir",
        value=_toml_quote(backup_output_dir or ""),
    )
    updated = _upsert_table_key(updated, table="qr", key="chunk_size", value=str(qr_chunk_size))

    if shard_threshold is None or shard_count is None:
        updated = _upsert_table_key(
            updated, table="defaults.backup", key="shard_threshold", value="0"
        )
        updated = _upsert_table_key(updated, table="defaults.backup", key="shard_count", value="0")
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="signing_key_mode",
            value='""',
        )
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="signing_key_shard_threshold",
            value="0",
        )
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="signing_key_shard_count",
            value="0",
        )
    else:
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="shard_threshold",
            value=str(shard_threshold),
        )
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="shard_count",
            value=str(shard_count),
        )
        if signing_key_mode is None:
            signing_key_mode = "embedded"
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="signing_key_mode",
            value=_toml_quote(signing_key_mode),
        )
        if signing_key_mode != "sharded":
            updated = _upsert_table_key(
                updated,
                table="defaults.backup",
                key="signing_key_shard_threshold",
                value="0",
            )
            updated = _upsert_table_key(
                updated,
                table="defaults.backup",
                key="signing_key_shard_count",
                value="0",
            )
        else:
            updated = _upsert_table_key(
                updated,
                table="defaults.backup",
                key="signing_key_shard_threshold",
                value=str(signing_key_shard_threshold or 0),
            )
            updated = _upsert_table_key(
                updated,
                table="defaults.backup",
                key="signing_key_shard_count",
                value=str(signing_key_shard_count or 0),
            )

    if not updated.endswith(("\n", "\r\n")):
        updated += line_ending
    _write_text_atomic(config_path, updated)
    return config_path


def apply_gui_defaults(
    path: str | Path | None,
    *,
    design: str,
    page_size: PageSize,
    backup_output_dir: str | None,
    qr_chunk_size: int,
    backup_shard_threshold: int | None,
    backup_shard_count: int | None,
    signing_key_mode: SigningKeyMode | None,
    signing_key_shard_threshold: int | None = None,
    signing_key_shard_count: int | None = None,
    recover_output_dir: str | None = None,
) -> Path:
    """Apply GUI-managed defaults into the resolved config file."""

    _ = resolve_template_design_path(design)
    if page_size not in {"A4", "LETTER"}:
        raise ValueError("page_size must be 'A4' or 'LETTER'")
    if qr_chunk_size <= 0:
        raise ValueError("qr_chunk_size must be a positive integer")

    if (backup_shard_threshold is None) != (backup_shard_count is None):
        raise ValueError("backup_shard_threshold and backup_shard_count must be set together")
    if backup_shard_threshold is not None and backup_shard_count is not None:
        if backup_shard_threshold < 1:
            raise ValueError("backup_shard_threshold must be >= 1")
        if backup_shard_threshold > 255:
            raise ValueError("backup_shard_threshold must be <= 255")
        if backup_shard_count < backup_shard_threshold:
            raise ValueError("backup_shard_count must be >= backup_shard_threshold")
        if backup_shard_count > 255:
            raise ValueError("backup_shard_count must be <= 255")

    if signing_key_mode not in {None, "embedded", "sharded"}:
        raise ValueError("signing_key_mode must be 'embedded', 'sharded', or None")
    if signing_key_mode == "sharded" and (
        backup_shard_threshold is None or backup_shard_count is None
    ):
        raise ValueError("signing_key_mode='sharded' requires backup sharding")
    if (signing_key_shard_threshold is None) != (signing_key_shard_count is None):
        raise ValueError(
            "signing_key_shard_threshold and signing_key_shard_count must be set together"
        )
    if signing_key_shard_threshold is not None and signing_key_shard_count is not None:
        if signing_key_mode != "sharded":
            raise ValueError("signing key shard counts require signing_key_mode='sharded'")
        if signing_key_shard_threshold < 1:
            raise ValueError("signing_key_shard_threshold must be >= 1")
        if signing_key_shard_threshold > 255:
            raise ValueError("signing_key_shard_threshold must be <= 255")
        if signing_key_shard_count < signing_key_shard_threshold:
            raise ValueError("signing_key_shard_count must be >= signing_key_shard_threshold")
        if signing_key_shard_count > 255:
            raise ValueError("signing_key_shard_count must be <= 255")

    config_path = resolve_config_path(path)
    original = config_path.read_text(encoding="utf-8")
    line_ending = "\r\n" if "\r\n" in original else "\n"

    updated = original
    updated = _upsert_table_key(updated, table="templates", key="default_name", value=f'"{design}"')
    for section in (
        "template",
        "recovery_template",
        "shard_template",
        "signing_key_shard_template",
        "kit_template",
    ):
        updated = _upsert_table_key(updated, table=section, key="name", value=f'"{design}"')
    updated = _upsert_table_key(updated, table="page", key="size", value=f'"{page_size}"')
    updated = _upsert_table_key(updated, table="qr", key="chunk_size", value=str(qr_chunk_size))
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="output_dir",
        value=_toml_quote(backup_output_dir or ""),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.recover",
        key="output",
        value=_toml_quote(recover_output_dir or ""),
    )

    if backup_shard_threshold is None or backup_shard_count is None:
        updated = _upsert_table_key(
            updated, table="defaults.backup", key="shard_threshold", value="0"
        )
        updated = _upsert_table_key(updated, table="defaults.backup", key="shard_count", value="0")
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="signing_key_mode",
            value='""',
        )
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="signing_key_shard_threshold",
            value="0",
        )
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="signing_key_shard_count",
            value="0",
        )
    else:
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="shard_threshold",
            value=str(backup_shard_threshold),
        )
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="shard_count",
            value=str(backup_shard_count),
        )
        effective_signing_key_mode = signing_key_mode or "embedded"
        updated = _upsert_table_key(
            updated,
            table="defaults.backup",
            key="signing_key_mode",
            value=_toml_quote(effective_signing_key_mode),
        )
        if effective_signing_key_mode != "sharded":
            updated = _upsert_table_key(
                updated,
                table="defaults.backup",
                key="signing_key_shard_threshold",
                value="0",
            )
            updated = _upsert_table_key(
                updated,
                table="defaults.backup",
                key="signing_key_shard_count",
                value="0",
            )
        else:
            updated = _upsert_table_key(
                updated,
                table="defaults.backup",
                key="signing_key_shard_threshold",
                value=str(signing_key_shard_threshold or 0),
            )
            updated = _upsert_table_key(
                updated,
                table="defaults.backup",
                key="signing_key_shard_count",
                value=str(signing_key_shard_count or 0),
            )

    if not updated.endswith(("\n", "\r\n")):
        updated += line_ending
    _write_text_atomic(config_path, updated)
    return config_path


def _write_text_atomic(path: Path, text: str) -> None:
    """Atomically replace a text file in place."""

    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def _toml_quote(value: str) -> str:
    """Return a TOML basic string literal."""

    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _table_header_name(line: str) -> str | None:
    """Return table name when a line is a TOML table header."""

    match = _TABLE_HEADER_RE.match(line)
    if match is None:
        return None
    return match.group(1).strip()


def _upsert_table_key(text: str, *, table: str, key: str, value: str) -> str:
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


def _extract_inline_comment(line: str) -> str:
    """Return trailing inline TOML comment with a leading space, or empty string."""

    comment_start = _find_unquoted_hash(line)
    if comment_start == -1:
        return ""
    return " " + line[comment_start:].strip()


def _find_unquoted_hash(line: str) -> int:
    """Return index of first # outside quoted strings, or -1 when absent."""

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


def _ensure_user_config(paths: ConfigPaths) -> bool:
    """Create user config and copy default files when missing."""

    try:
        paths.user_config_dir.mkdir(parents=True, exist_ok=True)
        paths.user_templates_root.mkdir(parents=True, exist_ok=True)
        _copy_if_missing(DEFAULT_CONFIG_PATH, paths.user_config_path)
        _migrate_user_config(paths.user_config_path)
        template_version = get_ethernity_version()
        overwrite_templates = _should_overwrite_templates(paths, template_version=template_version)
        _copy_template_designs(paths, overwrite=overwrite_templates)
        if overwrite_templates:
            _write_template_sync_state(paths, template_version=template_version)
    except OSError:
        return False
    return True


def _template_sync_state_path(paths: ConfigPaths) -> Path:
    """Return the per-user template sync state path."""

    return paths.user_templates_root / _TEMPLATE_SYNC_STATE_FILENAME


def _read_template_sync_version(paths: ConfigPaths) -> str | None:
    """Return the last template version synced for this user, when available."""

    state_path = _template_sync_state_path(paths)
    if not state_path.exists():
        return None
    try:
        payload = state_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    template_version = parsed.get("template_version")
    if not isinstance(template_version, str):
        return None
    return template_version


def _should_overwrite_templates(paths: ConfigPaths, *, template_version: str) -> bool:
    """Return whether packaged templates should overwrite user copies."""

    previous_version = _read_template_sync_version(paths)
    return previous_version != template_version


def _write_template_sync_state(paths: ConfigPaths, *, template_version: str) -> None:
    """Persist template sync metadata for upgrade overwrite detection."""

    state_path = _template_sync_state_path(paths)
    payload = {
        "version": _TEMPLATE_SYNC_STATE_VERSION,
        "template_version": template_version,
    }
    _write_text_atomic(state_path, json.dumps(payload, sort_keys=True) + "\n")


def _migrate_user_config(path: Path) -> bool:
    """Apply backward-compatible migrations to an existing user config file."""

    original = path.read_text(encoding="utf-8")

    updated, applied = _apply_config_migrations(original, _CONFIG_MIGRATIONS)
    if not applied:
        return False

    backup_path = path.with_name(f"{path.name}.bak")
    if not backup_path.exists():
        shutil.copyfile(path, backup_path)

    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(updated, encoding="utf-8")
    temp_path.replace(path)
    return True


def _apply_config_migrations(
    text: str,
    migrations: tuple[ConfigMigrationStep, ...],
) -> tuple[str, tuple[str, ...]]:
    """Apply config migrations in order and return updated text and applied IDs."""

    current = text
    applied: list[str] = []
    for migration in migrations:
        candidate = migration.apply(current)
        if candidate is None or candidate == current:
            continue
        current = candidate
        applied.append(migration.migration_id)
    return current, tuple(applied)


def _inject_missing_backup_qr_payload_codec(text: str) -> str | None:
    """Insert a default `defaults.backup.qr_payload_codec` when absent."""

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None

    defaults = data.get("defaults")
    if defaults is not None and not isinstance(defaults, dict):
        return None
    backup = defaults.get("backup") if isinstance(defaults, dict) else None
    if backup is not None and not isinstance(backup, dict):
        return None
    if isinstance(backup, dict) and "qr_payload_codec" in backup:
        return None

    line_ending = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    config_line = 'qr_payload_codec = "raw"'
    dotted_config_line = 'defaults.backup.qr_payload_codec = "raw"'

    section_header = "[defaults.backup]"
    header_index = next(
        (idx for idx, line in enumerate(lines) if line.strip() == section_header), None
    )
    if header_index is not None:
        lines.insert(header_index + 1, config_line)
    elif backup is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([section_header, config_line])
    elif _DOTTED_BACKUP_KEY_RE.search(text):
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(dotted_config_line)
    else:
        return None

    return line_ending.join(lines) + line_ending


_CONFIG_MIGRATIONS: tuple[ConfigMigrationStep, ...] = (
    ConfigMigrationStep(
        migration_id="2026_03_defaults_backup_qr_payload_codec",
        apply=_inject_missing_backup_qr_payload_codec,
    ),
)


def _copy_template_designs(paths: ConfigPaths, *, overwrite: bool = False) -> None:
    """Copy packaged template designs into the user config directory."""

    package_root = PACKAGE_ROOT / "templates"
    if not package_root.exists():
        return

    shared_dir = package_root / "_shared"
    if shared_dir.is_dir():
        dest_shared = paths.user_templates_root / "_shared"
        dest_shared.mkdir(parents=True, exist_ok=True)
        for shared_path in sorted(shared_dir.rglob("*"), key=lambda item: str(item).lower()):
            if shared_path.name.startswith(".") or not shared_path.is_file():
                continue
            relative = shared_path.relative_to(shared_dir)
            destination = dest_shared / relative
            _copy_template_file(shared_path, destination, overwrite=overwrite)

    for entry in sorted(package_root.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        if entry.name == "_shared":
            continue
        if not _is_template_design_dir(entry):
            continue
        dest_dir = paths.user_templates_root / entry.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        for template_path in sorted(entry.iterdir(), key=lambda item: item.name.lower()):
            if template_path.name.startswith(".") or not template_path.is_file():
                continue
            _copy_template_file(template_path, dest_dir / template_path.name, overwrite=overwrite)


def _copy_template_file(source: Path, dest: Path, *, overwrite: bool) -> None:
    """Copy a template file, optionally overwriting existing user copies."""

    if overwrite:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        return
    _copy_if_missing(source, dest)


def _copy_if_missing(source: Path, dest: Path) -> None:
    """Copy a file only when the destination does not already exist."""

    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
