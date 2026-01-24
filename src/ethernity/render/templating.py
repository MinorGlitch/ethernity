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

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATES_ROOT = Path(__file__).parent.parent / "templates"
_SHARED_DIR = _TEMPLATES_ROOT / "_shared"


@lru_cache(maxsize=8)
def _get_env(directory: Path) -> Environment:
    search_paths = [str(directory)]
    if _SHARED_DIR.exists() and _SHARED_DIR.resolve() != directory.resolve():
        search_paths.append(str(_SHARED_DIR))

    return Environment(
        loader=FileSystemLoader(search_paths),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
        auto_reload=True,
    )


def render_template(path: str | Path, context: dict[str, object]) -> str:
    template_path = Path(path)
    env = _get_env(template_path.parent.resolve())
    template = env.get_template(template_path.name)
    return template.render(**context)
