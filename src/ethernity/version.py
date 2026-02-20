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

import importlib.metadata
import tomllib
from functools import lru_cache
from pathlib import Path

_PACKAGE_NAME = "ethernity"
_PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


@lru_cache(maxsize=1)
def get_ethernity_version() -> str:
    try:
        return importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return _version_from_pyproject(_PYPROJECT_PATH)


def _version_from_pyproject(path: Path) -> str:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    project = payload.get("project")
    if not isinstance(project, dict):
        return ""
    version = project.get("version")
    if not isinstance(version, str):
        return ""
    return version.strip()
