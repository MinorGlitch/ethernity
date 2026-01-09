#!/usr/bin/env python3
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


@lru_cache(maxsize=8)
def _get_env(directory: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(directory)),
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
