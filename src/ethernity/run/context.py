from __future__ import annotations

from pathlib import Path

import click

CONFIG_PATH_KEY = "config_path"


def bind_config_path(ctx: click.Context, config_path: Path | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj[CONFIG_PATH_KEY] = config_path


def current_config_path(ctx: click.Context) -> Path | None:
    value = ctx.obj.get(CONFIG_PATH_KEY) if isinstance(ctx.obj, dict) else None
    return value if isinstance(value, Path) else None
