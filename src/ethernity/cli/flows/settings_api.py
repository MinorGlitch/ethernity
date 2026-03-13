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

from pathlib import Path
from typing import Literal

from ...config import (
    apply_gui_defaults,
    list_template_designs,
    load_app_config,
    load_cli_defaults,
    resolve_config_path,
)
from ...version import get_ethernity_version
from ..events import emit_result


def _normalize_empty_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _settings_payload(path: str | Path | None) -> dict[str, object]:
    config_path = resolve_config_path(path)
    app_config = load_app_config(config_path)
    cli_defaults = load_cli_defaults(config_path)
    return {
        "config_path": str(config_path),
        "version": get_ethernity_version(),
        "designs": sorted(list_template_designs().keys()),
        "settings": {
            "template_design": app_config.template_path.parent.name,
            "page_size": str(app_config.paper_size).upper(),
            "backup_output_dir": _normalize_empty_str(cli_defaults.backup.output_dir),
            "qr_chunk_size": app_config.qr_chunk_size,
            "backup_shard_threshold": cli_defaults.backup.shard_threshold,
            "backup_shard_count": cli_defaults.backup.shard_count,
            "signing_key_mode": cli_defaults.backup.signing_key_mode,
            "signing_key_shard_threshold": cli_defaults.backup.signing_key_shard_threshold,
            "signing_key_shard_count": cli_defaults.backup.signing_key_shard_count,
            "recover_output_dir": _normalize_empty_str(cli_defaults.recover.output),
        },
    }


def run_settings_get_api_command(*, config_path: str | None) -> int:
    emit_result(command="settings_get", **_settings_payload(config_path))
    return 0


def run_settings_set_api_command(
    *,
    config_path: str | None,
    design: str,
    page_size: str,
    backup_output_dir: str,
    qr_chunk_size: int,
    backup_shard_threshold: int,
    backup_shard_count: int,
    signing_key_mode: Literal["embedded", "sharded"] | str,
    signing_key_shard_threshold: int,
    signing_key_shard_count: int,
    recover_output_dir: str,
) -> int:
    resolved_path = apply_gui_defaults(
        config_path,
        design=design,
        page_size=page_size.upper(),  # type: ignore[arg-type]
        backup_output_dir=backup_output_dir,
        qr_chunk_size=qr_chunk_size,
        backup_shard_threshold=backup_shard_threshold or None,
        backup_shard_count=backup_shard_count or None,
        signing_key_mode=(signing_key_mode.strip().lower() or None),  # type: ignore[arg-type]
        signing_key_shard_threshold=signing_key_shard_threshold or None,
        signing_key_shard_count=signing_key_shard_count or None,
        recover_output_dir=recover_output_dir,
    )
    emit_result(command="settings_set", **_settings_payload(str(resolved_path)))
    return 0


__all__ = [
    "run_settings_get_api_command",
    "run_settings_set_api_command",
]
