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

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = PACKAGE_ROOT / "templates/ledger/main_document.html.j2"
DEFAULT_RECOVERY_TEMPLATE_PATH = PACKAGE_ROOT / "templates/ledger/recovery_document.html.j2"
DEFAULT_SHARD_TEMPLATE_PATH = PACKAGE_ROOT / "templates/ledger/shard_document.html.j2"
DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH = (
    PACKAGE_ROOT / "templates/ledger/signing_key_shard_document.html.j2"
)
DEFAULT_KIT_TEMPLATE_PATH = PACKAGE_ROOT / "templates/ledger/kit_document.html.j2"
DEFAULT_TEMPLATE_STYLE = DEFAULT_TEMPLATE_PATH.parent.name
TEMPLATE_FILENAMES = (
    DEFAULT_TEMPLATE_PATH.name,
    DEFAULT_RECOVERY_TEMPLATE_PATH.name,
    DEFAULT_SHARD_TEMPLATE_PATH.name,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH.name,
    DEFAULT_KIT_TEMPLATE_PATH.name,
)
DEFAULT_PAPER_SIZE = "A4"
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config/config.toml"
XDG_CONFIG_ENV = "XDG_CONFIG_HOME"


@dataclass(frozen=True)
class ConfigPaths:
    user_config_dir: Path
    user_templates_root: Path
    user_templates_dir: Path
    user_config_path: Path
    user_template_paths: dict[str, Path]
    user_required_files: tuple[Path, ...]


def _user_config_dir() -> Path:
    xdg_override = os.environ.get(XDG_CONFIG_ENV)
    if xdg_override:
        return Path(xdg_override) / "ethernity"
    if sys.platform == "darwin":
        return Path.home() / ".config" / "ethernity"
    return Path(user_config_dir("ethernity", appauthor=False))


def _build_paths() -> ConfigPaths:
    user_config_dir = _user_config_dir()
    user_templates_root = user_config_dir / "templates"
    user_templates_dir = user_templates_root / DEFAULT_TEMPLATE_STYLE
    user_config_path = user_config_dir / DEFAULT_CONFIG_PATH.name
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
    package_root = PACKAGE_ROOT / "templates"
    if not package_root.exists():
        return {}

    paths = _build_paths()
    designs: dict[str, Path] = {}
    for entry in sorted(package_root.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        if not _is_template_design_dir(entry):
            continue
        user_override = paths.user_templates_root / entry.name
        if user_override.is_dir() and _is_template_design_dir(user_override):
            designs[entry.name] = user_override
        else:
            designs[entry.name] = entry
    return designs


def resolve_template_design_path(design: str) -> Path:
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
    return all((path / filename).is_file() for filename in TEMPLATE_FILENAMES)


def init_user_config() -> Path:
    paths = _build_paths()
    if not _ensure_user_config(paths):
        raise OSError(f"unable to create config dir at {paths.user_config_dir}")
    return paths.user_config_dir


def user_config_needs_init() -> bool:
    paths = _build_paths()
    return any(not path.exists() for path in paths.user_required_files)


def resolve_config_path(path: str | Path | None = None) -> Path:
    """Resolve the TOML config path used by the application."""
    if path:
        return Path(path)

    paths = _build_paths()
    if _ensure_user_config(paths) and paths.user_config_path.exists():
        return paths.user_config_path
    return DEFAULT_CONFIG_PATH


def _ensure_user_config(paths: ConfigPaths) -> bool:
    try:
        paths.user_config_dir.mkdir(parents=True, exist_ok=True)
        paths.user_templates_root.mkdir(parents=True, exist_ok=True)
        _copy_if_missing(DEFAULT_CONFIG_PATH, paths.user_config_path)
        _copy_template_designs(paths)
    except OSError:
        return False
    return True


def _copy_template_designs(paths: ConfigPaths) -> None:
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
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
