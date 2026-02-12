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

import base64
import mimetypes
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATES_ROOT = Path(__file__).parent.parent / "templates"
_PACKAGED_SHARED_DIR = _TEMPLATES_ROOT / "_shared"


def _discover_shared_dir(template_dir: Path) -> Path | None:
    candidate = template_dir.parent / "_shared"
    if candidate.is_dir():
        return candidate
    return None


def _build_search_paths(template_dir: Path) -> tuple[Path, ...]:
    template_dir = template_dir.resolve()
    shared_dir = _discover_shared_dir(template_dir)
    packaged_shared_dir = _PACKAGED_SHARED_DIR if _PACKAGED_SHARED_DIR.is_dir() else None

    paths: list[Path] = [template_dir]
    if shared_dir is not None:
        shared_dir = shared_dir.resolve()
        if shared_dir not in paths:
            paths.append(shared_dir)
    if packaged_shared_dir is not None:
        packaged_shared_dir = packaged_shared_dir.resolve()
        if packaged_shared_dir not in paths:
            paths.append(packaged_shared_dir)
    return tuple(paths)


def _resolve_asset_path(rel_path: str, roots: tuple[Path, ...]) -> Path:
    if not rel_path or not str(rel_path).strip():
        raise ValueError("asset_data_uri requires a relative path")
    candidate = Path(rel_path)
    if candidate.is_absolute():
        raise ValueError("asset_data_uri does not allow absolute paths")

    escaped = True
    for root in roots:
        root_resolved = root.resolve()
        resolved = (root_resolved / candidate).resolve(strict=False)
        if not resolved.is_relative_to(root_resolved):
            continue
        escaped = False
        if resolved.is_file():
            return resolved

    if escaped:
        raise ValueError(f"asset_data_uri path escapes roots: {rel_path}")
    raise FileNotFoundError(f"asset not found: {rel_path}")


@lru_cache(maxsize=64)
def _asset_data_uri_for_path(path: Path) -> str:
    payload = path.read_bytes()
    mime_type, _encoding = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "application/octet-stream"
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


@lru_cache(maxsize=16)
def _get_env(template_dir: Path) -> Environment:
    search_paths = _build_search_paths(template_dir)
    loader_paths = [str(path) for path in search_paths]

    env = Environment(
        loader=FileSystemLoader(loader_paths),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        auto_reload=True,
    )
    env.globals["asset_data_uri"] = lambda rel_path: _asset_data_uri_for_path(
        _resolve_asset_path(str(rel_path), search_paths)
    )
    return env


def render_template(path: str | Path, context: dict[str, object]) -> str:
    template_path = Path(path)
    env = _get_env(template_path.parent.resolve())
    template = env.get_template(template_path.name)
    return template.render(**context)
