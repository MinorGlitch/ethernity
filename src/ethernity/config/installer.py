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
    user_state_dir_path,
    user_templates_design_path,
    user_templates_root_path,
)

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
_FIRST_RUN_ONBOARDING_MARKER_FILENAME = "first_run_onboarding_v1.done"


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

    return user_state_dir_path() / _FIRST_RUN_ONBOARDING_MARKER_FILENAME


def first_run_onboarding_needed() -> bool:
    """Return whether first-run onboarding should be offered."""

    return not first_run_onboarding_marker_path().exists()


def mark_first_run_onboarding_complete() -> Path:
    """Persist the first-run onboarding completion marker and return its path."""

    marker_path = first_run_onboarding_marker_path()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    if not marker_path.exists():
        marker_path.write_text("completed\n", encoding="utf-8")
    return marker_path


def apply_first_run_defaults(
    path: str | Path | None,
    *,
    design: str,
    payload_codec: PayloadCodec,
    qr_payload_codec: QrPayloadCodec,
) -> Path:
    """Apply first-run default selections into the resolved config file."""

    _ = resolve_template_design_path(design)
    if payload_codec not in {"auto", "raw", "gzip"}:
        raise ValueError("payload_codec must be 'auto', 'raw', or 'gzip'")
    if qr_payload_codec not in {"raw", "base64"}:
        raise ValueError("qr_payload_codec must be 'raw' or 'base64'")

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

    if not updated.endswith(("\n", "\r\n")):
        updated += line_ending
    _write_text_atomic(config_path, updated)
    return config_path


def _write_text_atomic(path: Path, text: str) -> None:
    """Atomically replace a text file in place."""

    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


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
    dotted_prefix = f"{dotted_key} ="
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        if not stripped.startswith(dotted_prefix):
            continue
        indent = line[: len(line) - len(line.lstrip())]
        comment = ""
        hash_index = line.find("#")
        if hash_index != -1:
            comment = " " + line[hash_index:].strip()
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
        comment = ""
        hash_index = line.find("#")
        if hash_index != -1:
            comment = " " + line[hash_index:].strip()
        lines[index] = f"{indent}{key} = {value}{comment}"
        return line_ending.join(lines) + line_ending

    lines.insert(table_end, f"{key} = {value}")
    return line_ending.join(lines) + line_ending


def _ensure_user_config(paths: ConfigPaths) -> bool:
    """Create user config and copy default files when missing."""

    try:
        paths.user_config_dir.mkdir(parents=True, exist_ok=True)
        paths.user_templates_root.mkdir(parents=True, exist_ok=True)
        _copy_if_missing(DEFAULT_CONFIG_PATH, paths.user_config_path)
        _migrate_user_config(paths.user_config_path)
        _copy_template_designs(paths)
    except OSError:
        return False
    return True


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


def _copy_template_designs(paths: ConfigPaths) -> None:
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
            _copy_if_missing(shared_path, destination)

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
            _copy_if_missing(template_path, dest_dir / template_path.name)


def _copy_if_missing(source: Path, dest: Path) -> None:
    """Copy a file only when the destination does not already exist."""

    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
