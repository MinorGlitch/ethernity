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

"""Load and validate application configuration from TOML files."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Literal, TypeVar, cast

from ..encoding.chunking import DEFAULT_CHUNK_SIZE
from ..qr.codec import QrConfig
from .installer import (
    DEFAULT_KIT_TEMPLATE_PATH,
    DEFAULT_PAPER_SIZE,
    DEFAULT_RECOVERY_TEMPLATE_PATH,
    DEFAULT_SHARD_TEMPLATE_PATH,
    DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
    DEFAULT_TEMPLATE_PATH,
    resolve_config_path,
    resolve_template_design_path,
)

_T = TypeVar("_T")


@dataclass(frozen=True)
class BackupDefaults:
    """Default CLI values for backup commands."""

    base_dir: str | None = None
    output_dir: str | None = None
    shard_threshold: int | None = None
    shard_count: int | None = None
    signing_key_mode: Literal["embedded", "sharded"] | None = None
    signing_key_shard_threshold: int | None = None
    signing_key_shard_count: int | None = None
    payload_codec: Literal["auto", "raw", "gzip"] = "auto"
    qr_payload_codec: Literal["raw", "base64"] = "raw"


@dataclass(frozen=True)
class RecoverDefaults:
    """Default CLI values for recover commands."""

    output: str | None = None


@dataclass(frozen=True)
class UiDefaults:
    """Default CLI UI behavior flags."""

    quiet: bool = False
    no_color: bool = False
    no_animations: bool = False


@dataclass(frozen=True)
class DebugDefaults:
    """Default debug output settings."""

    max_bytes: int | None = None


@dataclass(frozen=True)
class RuntimeDefaults:
    """Default runtime tuning knobs."""

    render_jobs: int | Literal["auto"] | None = None


@dataclass(frozen=True)
class CliDefaults:
    """Grouped defaults for CLI subcommands and UI behavior."""

    backup: BackupDefaults = field(default_factory=BackupDefaults)
    recover: RecoverDefaults = field(default_factory=RecoverDefaults)
    ui: UiDefaults = field(default_factory=UiDefaults)
    debug: DebugDefaults = field(default_factory=DebugDefaults)
    runtime: RuntimeDefaults = field(default_factory=RuntimeDefaults)


@dataclass(frozen=True)
class AppConfig:
    """Resolved application configuration used by runtime services."""

    template_path: Path
    recovery_template_path: Path
    shard_template_path: Path
    signing_key_shard_template_path: Path
    kit_template_path: Path
    paper_size: str
    qr_config: QrConfig
    qr_chunk_size: int
    cli_defaults: CliDefaults = field(default_factory=CliDefaults)


def load_app_config(path: str | Path | None = None, *, paper_size: str | None = None) -> AppConfig:
    """Load app configuration and apply defaults and template resolution."""

    config_path = resolve_config_path(path)
    data = _load_toml(config_path)
    cli_defaults = _parse_cli_defaults(data)
    templates_cfg = _get_dict(data, "templates")
    default_design_path = _resolve_default_template_design_path(templates_cfg)
    template_path = _resolve_template_section_path(
        data,
        section="template",
        default_template_path=DEFAULT_TEMPLATE_PATH,
        default_design_path=default_design_path,
    )
    recovery_path = _resolve_template_section_path(
        data,
        section="recovery_template",
        default_template_path=DEFAULT_RECOVERY_TEMPLATE_PATH,
        default_design_path=default_design_path,
    )
    shard_path = _resolve_template_section_path(
        data,
        section="shard_template",
        default_template_path=DEFAULT_SHARD_TEMPLATE_PATH,
        default_design_path=default_design_path,
    )
    signing_key_shard_path = _resolve_template_section_path(
        data,
        section="signing_key_shard_template",
        default_template_path=DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH,
        default_design_path=default_design_path,
    )
    kit_path = _resolve_template_section_path(
        data,
        section="kit_template",
        default_template_path=DEFAULT_KIT_TEMPLATE_PATH,
        default_design_path=default_design_path,
    )

    page_cfg = _get_dict(data, "page")
    resolved_paper_size = (
        paper_size or _parse_optional_str(page_cfg.get("size")) or DEFAULT_PAPER_SIZE
    )
    qr_section = _get_dict(data, "qr")
    qr_config = build_qr_config(qr_section)
    qr_chunk_size_value = _parse_optional_int(qr_section.get("chunk_size"))
    qr_chunk_size = DEFAULT_CHUNK_SIZE if qr_chunk_size_value is None else qr_chunk_size_value
    if qr_chunk_size <= 0:
        raise ValueError("qr.chunk_size must be a positive integer")
    return AppConfig(
        template_path=template_path,
        recovery_template_path=recovery_path,
        shard_template_path=shard_path,
        signing_key_shard_template_path=signing_key_shard_path,
        kit_template_path=kit_path,
        paper_size=resolved_paper_size,
        qr_config=qr_config,
        qr_chunk_size=qr_chunk_size,
        cli_defaults=cli_defaults,
    )


def load_cli_defaults(path: str | Path | None = None) -> CliDefaults:
    """Load only CLI defaults from the configured TOML file."""

    config_path = resolve_config_path(path)
    data = _load_toml(config_path)
    return _parse_cli_defaults(data)


def apply_template_design(config: AppConfig, design: str | None) -> AppConfig:
    """Override template paths in a config with a resolved design name."""

    if not design:
        return config
    design_path = resolve_template_design_path(design)
    return replace(
        config,
        template_path=design_path / DEFAULT_TEMPLATE_PATH.name,
        recovery_template_path=design_path / DEFAULT_RECOVERY_TEMPLATE_PATH.name,
        shard_template_path=design_path / DEFAULT_SHARD_TEMPLATE_PATH.name,
        signing_key_shard_template_path=(
            design_path / DEFAULT_SIGNING_KEY_SHARD_TEMPLATE_PATH.name
        ),
        kit_template_path=design_path / DEFAULT_KIT_TEMPLATE_PATH.name,
    )


def build_qr_config(cfg: dict[str, object] | None = None) -> QrConfig:
    """Build QR rendering config from a parsed TOML section."""

    cfg = cfg or {}
    boost_error = _parse_optional_bool(cfg.get("boost_error"), field="qr.boost_error")
    return QrConfig(
        error=str(cfg.get("error", "Q")),
        scale=_parse_int(cfg.get("scale"), default=4),
        border=_parse_int(cfg.get("border"), default=4),
        kind=str(cfg.get("kind", "png")),
        dark=_parse_color(cfg.get("dark"), field="qr.dark"),
        light=_parse_color(cfg.get("light"), field="qr.light"),
        version=_parse_optional_int(cfg.get("version")),
        mask=_parse_optional_int(cfg.get("mask")),
        micro=_parse_optional_bool(cfg.get("micro"), field="qr.micro"),
        boost_error=True if boost_error is None else boost_error,
    )


def _parse_cli_defaults(data: dict[str, object]) -> CliDefaults:
    """Parse nested CLI default sections from raw config data."""

    return CliDefaults(
        backup=_parse_backup_defaults(_get_nested_dict(data, "defaults", "backup")),
        recover=_parse_recover_defaults(_get_nested_dict(data, "defaults", "recover")),
        ui=_parse_ui_defaults(_get_dict(data, "ui")),
        debug=_parse_debug_defaults(_get_dict(data, "debug")),
        runtime=_parse_runtime_defaults(_get_dict(data, "runtime")),
    )


def _parse_backup_defaults(cfg: dict[str, object]) -> BackupDefaults:
    """Parse `[defaults.backup]` values."""

    return BackupDefaults(
        base_dir=_parse_optional_unset_str(cfg.get("base_dir"), field="defaults.backup.base_dir"),
        output_dir=_parse_optional_unset_str(
            cfg.get("output_dir"), field="defaults.backup.output_dir"
        ),
        shard_threshold=_parse_optional_positive_int_or_unset_zero(
            cfg.get("shard_threshold"),
            field="defaults.backup.shard_threshold",
        ),
        shard_count=_parse_optional_positive_int_or_unset_zero(
            cfg.get("shard_count"),
            field="defaults.backup.shard_count",
        ),
        signing_key_mode=_parse_optional_signing_key_mode(
            cfg.get("signing_key_mode"),
            field="defaults.backup.signing_key_mode",
        ),
        signing_key_shard_threshold=_parse_optional_positive_int_or_unset_zero(
            cfg.get("signing_key_shard_threshold"),
            field="defaults.backup.signing_key_shard_threshold",
        ),
        signing_key_shard_count=_parse_optional_positive_int_or_unset_zero(
            cfg.get("signing_key_shard_count"),
            field="defaults.backup.signing_key_shard_count",
        ),
        payload_codec=_parse_payload_codec(
            cfg.get("payload_codec"),
            field="defaults.backup.payload_codec",
        ),
        qr_payload_codec=_parse_required_qr_payload_codec(
            cfg.get("qr_payload_codec"),
            field="defaults.backup.qr_payload_codec",
        ),
    )


def _parse_recover_defaults(cfg: dict[str, object]) -> RecoverDefaults:
    """Parse `[defaults.recover]` values."""

    return RecoverDefaults(
        output=_parse_optional_unset_str(cfg.get("output"), field="defaults.recover.output"),
    )


def _parse_ui_defaults(cfg: dict[str, object]) -> UiDefaults:
    """Parse `[ui]` default flags."""

    return UiDefaults(
        quiet=_parse_bool(cfg.get("quiet"), field="ui.quiet", default=False),
        no_color=_parse_bool(cfg.get("no_color"), field="ui.no_color", default=False),
        no_animations=_parse_bool(
            cfg.get("no_animations"),
            field="ui.no_animations",
            default=False,
        ),
    )


def _parse_debug_defaults(cfg: dict[str, object]) -> DebugDefaults:
    """Parse `[debug]` default values."""

    return DebugDefaults(
        max_bytes=_parse_optional_positive_int_or_unset_zero(
            cfg.get("max_bytes"),
            field="debug.max_bytes",
        ),
    )


def _parse_runtime_defaults(cfg: dict[str, object]) -> RuntimeDefaults:
    """Parse `[runtime]` defaults."""

    return RuntimeDefaults(
        render_jobs=_parse_optional_render_jobs(
            cfg.get("render_jobs"),
            field="runtime.render_jobs",
        ),
    )


def _resolve_default_template_design_path(cfg: dict[str, object]) -> Path | None:
    """Resolve the default template design path from `[templates]`."""

    design = _parse_optional_template_name(cfg.get("default_name"), field="templates.default_name")
    if design is None:
        return None
    return _resolve_design_path(design, field="templates.default_name")


def _resolve_template_section_path(
    data: dict[str, object],
    *,
    section: str,
    default_template_path: Path,
    default_design_path: Path | None,
) -> Path:
    """Resolve a template file path for a config section."""

    cfg = _get_dict(data, section)
    _reject_legacy_template_path(cfg, section=section)
    design_name = _parse_optional_template_name(cfg.get("name"), field=f"{section}.name")
    if design_name is None:
        if default_design_path is None:
            return default_template_path
        return default_design_path / default_template_path.name
    design_path = _resolve_design_path(design_name, field=f"{section}.name")
    return design_path / default_template_path.name


def _reject_legacy_template_path(cfg: dict[str, object], *, section: str) -> None:
    """Reject deprecated template path overrides in favor of design names."""

    if "path" in cfg:
        raise ValueError(
            f'{section}.path is unsupported in this build; use {section}.name = "<design>"'
        )


def _resolve_design_path(design: str, *, field: str) -> Path:
    """Resolve a design path and rewrite errors with config field context."""

    try:
        return resolve_template_design_path(design)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from exc


def _parse_optional_template_name(value: object, *, field: str) -> str | None:
    """Parse an optional template design name, rejecting blank strings."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a non-empty string")
    name = value.strip()
    if not name:
        raise ValueError(f"{field} must be a non-empty string")
    return name


def _load_toml(path: Path) -> dict[str, object]:
    """Load a TOML file into a raw dictionary."""

    with path.open("rb") as handle:
        return tomllib.load(handle)


def _get_dict(data: dict[str, object], key: str) -> dict[str, object]:
    """Return a dict section or an empty dict when absent."""

    value = data.get(key)
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise ValueError(f"{key} must be a table")


def _get_nested_dict(data: dict[str, object], *keys: str) -> dict[str, object]:
    """Return a nested dict section or an empty dict when any segment is missing."""

    current: dict[str, object] = data
    path_parts: list[str] = []
    for key in keys:
        path_parts.append(key)
        value = current.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError(f"{'.'.join(path_parts)} must be a table")
        current = value
    return current


def _parse_optional_unset_str(value: object, *, field: str) -> str | None:
    """Parse a string field where empty string means unset."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalized = value.strip()
    return normalized or None


def _parse_bool(value: object, *, field: str, default: bool) -> bool:
    """Parse a strict boolean-like config value with a default."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"{field} must be a boolean")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{field} must be a boolean")
    raise ValueError(f"{field} must be a boolean")


def _parse_optional_signing_key_mode(
    value: object,
    *,
    field: str,
) -> Literal["embedded", "sharded"] | None:
    """Parse the optional signing-key storage mode."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be 'embedded', 'sharded', or empty")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in {"embedded", "sharded"}:
        raise ValueError(f"{field} must be 'embedded', 'sharded', or empty")
    return cast(Literal["embedded", "sharded"], normalized)


def _parse_payload_codec(
    value: object,
    *,
    field: str,
) -> Literal["auto", "raw", "gzip"]:
    """Parse backup payload codec mode."""

    if value is None:
        return "auto"
    if not isinstance(value, str):
        raise ValueError(f"{field} must be 'auto', 'raw', or 'gzip'")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{field} must be 'auto', 'raw', or 'gzip'")
    if normalized not in {"auto", "raw", "gzip"}:
        raise ValueError(f"{field} must be 'auto', 'raw', or 'gzip'")
    return cast(Literal["auto", "raw", "gzip"], normalized)


def _parse_required_qr_payload_codec(
    value: object,
    *,
    field: str,
) -> Literal["raw", "base64"]:
    """Parse required backup QR payload transport mode."""

    if value is None:
        raise ValueError(f"{field} is required and must be 'raw' or 'base64'")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be 'raw' or 'base64'")
    normalized = value.strip().lower()
    if normalized not in {"raw", "base64"}:
        raise ValueError(f"{field} must be 'raw' or 'base64'")
    return cast(Literal["raw", "base64"], normalized)


def _parse_optional_positive_int_or_unset_zero(value: object, *, field: str) -> int | None:
    """Parse positive integers where `0` means unset."""

    if value is None:
        return None
    parsed = _parse_int_strict(value, field=field)
    if parsed == 0:
        return None
    if parsed < 0:
        raise ValueError(f"{field} must be a positive integer or 0")
    return parsed


def _parse_optional_render_jobs(
    value: object,
    *,
    field: str,
) -> int | Literal["auto"] | None:
    """Parse runtime render worker count or the `auto` sentinel."""

    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized == "auto":
            return "auto"
        parsed = _parse_int_strict(normalized, field=field)
        if parsed <= 0:
            raise ValueError(f"{field} must be 'auto' or a positive integer")
        return parsed
    parsed = _parse_int_strict(value, field=field)
    if parsed <= 0:
        raise ValueError(f"{field} must be 'auto' or a positive integer")
    return parsed


def _parse_int_strict(value: object, *, field: str) -> int:
    """Parse an integer field without silently accepting booleans."""

    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{field} must be an integer")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} must be an integer")
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(f"{field} must be an integer") from exc
    raise ValueError(f"{field} must be an integer")


def _parse_color(
    value: object,
    *,
    field: str,
) -> str | tuple[int, int, int] | tuple[int, int, int, int] | None:
    """Parse QR color values from strings or RGB/RGBA tuples."""

    if value is None:
        return None
    if isinstance(value, str):
        if value.strip().lower() in ("none", "transparent"):
            return None
        return value
    if isinstance(value, (list, tuple)):
        if len(value) not in {3, 4}:
            raise ValueError(f"{field} must be a color string or RGB/RGBA tuple")
        channels = tuple(
            _parse_int_strict(component, field=f"{field}[{index}]")
            for index, component in enumerate(value)
        )
        if len(channels) == 3:
            return channels
        return cast(tuple[int, int, int, int], channels)
    raise ValueError(f"{field} must be a color string or RGB/RGBA tuple")


def _parse_int(value: object, *, default: int) -> int:
    """Parse an integer-like value or return the provided default."""

    return _parse_number(value, cast=int, default=default)


def _parse_optional_int(value: object) -> int | None:
    """Parse an optional integer-like value."""

    return _parse_optional_number(value, cast=int, label="integer")


def _parse_optional_str(value: object) -> str | None:
    """Return a string value or `None` for unsupported types."""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None


def _parse_optional_bool(value: object, *, field: str) -> bool | None:
    """Parse an optional boolean value and reject invalid coercions."""

    if value is None:
        return None
    return _parse_bool(value, field=field, default=False)


def _parse_number(value: object, *, cast: Callable[[int | float | str], _T], default: _T) -> _T:
    """Cast scalar config values with a fallback default."""

    if isinstance(value, (int, float, str)):
        return cast(value)
    return default


def _parse_optional_number(
    value: object,
    *,
    cast: Callable[[int | float | str], _T],
    default: _T | None = None,
    label: str,
) -> _T | None:
    """Cast optional scalar config values and reject unsupported container types."""

    if value is None:
        return default
    if isinstance(value, (int, float, str)):
        return cast(value)
    raise ValueError(f"expected {label} value")
