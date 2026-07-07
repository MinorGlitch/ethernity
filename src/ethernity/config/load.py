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
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ethernity.config.install import resolve_config_path, resolve_render_style_path
from ethernity.config.paths import (
    DEFAULT_PAPER_SIZE,
    DEFAULT_RENDER_STYLE,
)
from ethernity.config.types import (
    AppConfig,
    BackupDefaults,
    CliDefaults,
    DebugDefaults,
    ExtendDefaults,
    ExtensionChunkingDefaults,
    RecoverDefaults,
    RuntimeDefaults,
    UiDefaults,
)
from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES
from ethernity.encoding.chunking import DEFAULT_CHUNK_SIZE
from ethernity.formats.extension_envelope import MIN_EXTENSION_CHUNK_SIZE
from ethernity.qr.codec import QrConfig

_QR_ERROR_LEVELS = frozenset({"L", "M", "Q", "H"})
_PAGE_SIZES = frozenset({"A4", "LETTER"})


class _QrSectionData(BaseModel):
    """Pydantic boundary model for `[qr]` TOML values."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    error: str = "Q"
    scale: int = 4
    border: int = 4
    kind: str = "png"
    dark: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None
    light: str | tuple[int, int, int] | tuple[int, int, int, int] | None = None
    version: int | None = None
    mask: int | None = None
    micro: bool | None = None
    boost_error: bool = True
    chunk_size: int | None = None

    @field_validator("error", mode="before")
    @classmethod
    def _validate_error(cls, value: object) -> str:
        if not isinstance(value, str) or value not in _QR_ERROR_LEVELS:
            raise ValueError("qr.error must be one of: L, M, Q, H")
        return value

    @field_validator("scale", mode="before")
    @classmethod
    def _validate_scale(cls, value: object) -> int:
        parsed = _require_int(value, field="qr.scale")
        if parsed <= 0:
            raise ValueError("qr.scale must be a positive integer")
        return parsed

    @field_validator("border", mode="before")
    @classmethod
    def _validate_border(cls, value: object) -> int:
        parsed = _require_int(value, field="qr.border")
        if parsed < 0:
            raise ValueError("qr.border must be a non-negative integer")
        return parsed

    @field_validator("kind", mode="before")
    @classmethod
    def _validate_kind(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("qr.kind must be a non-empty string")
        return value

    @field_validator("dark", "light", mode="before")
    @classmethod
    def _validate_color(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> str | tuple[int, int, int] | tuple[int, int, int, int] | None:
        field_name = info.field_name or "color"
        return _parse_color(value, field=f"qr.{field_name}")

    @field_validator("version", mode="before")
    @classmethod
    def _validate_version(cls, value: object) -> int | None:
        if value is None:
            return None
        parsed = _require_int(value, field="qr.version")
        if parsed < 1 or parsed > 40:
            raise ValueError("qr.version must be between 1 and 40")
        return parsed

    @field_validator("mask", mode="before")
    @classmethod
    def _validate_mask(cls, value: object) -> int | None:
        if value is None:
            return None
        parsed = _require_int(value, field="qr.mask")
        if parsed < 0 or parsed > 7:
            raise ValueError("qr.mask must be between 0 and 7")
        return parsed

    @field_validator("micro", mode="before")
    @classmethod
    def _validate_micro(cls, value: object) -> bool | None:
        if value is None:
            return None
        return _require_bool(value, field="qr.micro")

    @field_validator("boost_error", mode="before")
    @classmethod
    def _validate_boost_error(cls, value: object) -> bool:
        return _require_bool(value, field="qr.boost_error")

    @field_validator("chunk_size", mode="before")
    @classmethod
    def _validate_chunk_size(cls, value: object) -> int | None:
        if value is None:
            return None
        parsed = _require_int(value, field="qr.chunk_size")
        if parsed <= 0:
            raise ValueError("qr.chunk_size must be a positive integer")
        return parsed

    def to_qr_config(self) -> QrConfig:
        return QrConfig(
            error=self.error,
            scale=self.scale,
            border=self.border,
            kind=self.kind,
            dark=self.dark,
            light=self.light,
            version=self.version,
            mask=self.mask,
            micro=self.micro,
            boost_error=self.boost_error,
        )


class _ExtensionChunkingData(BaseModel):
    """Pydantic boundary model for `[extension.chunking]` TOML values."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    target_size: int | None = None
    min_size: int | None = None
    max_size: int | None = None

    @field_validator("target_size", "min_size", "max_size", mode="before")
    @classmethod
    def _validate_size(cls, value: object, info: ValidationInfo) -> int | None:
        field_name = info.field_name or "value"
        label = f"extension.chunking.{field_name}"
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} must be a positive integer")
        if value <= 0:
            raise ValueError(f"{label} must be a positive integer")
        _validate_extension_chunking_size(field=field_name, value=value)
        return value

    @model_validator(mode="after")
    def _validate_order(self) -> _ExtensionChunkingData:
        chunking = self.to_public()
        if not chunking.min_size <= chunking.target_size <= chunking.max_size:
            raise ValueError(
                "extension.chunking sizes must satisfy min_size <= target_size <= max_size"
            )
        return self

    def to_public(self) -> ExtensionChunkingDefaults:
        defaults = ExtensionChunkingDefaults()
        return ExtensionChunkingDefaults(
            target_size=defaults.target_size if self.target_size is None else self.target_size,
            min_size=defaults.min_size if self.min_size is None else self.min_size,
            max_size=defaults.max_size if self.max_size is None else self.max_size,
        )


def load_app_config(path: str | Path | None = None, *, paper_size: str | None = None) -> AppConfig:
    """Load app configuration and apply defaults and render-style resolution."""

    config_path = resolve_config_path(path)
    data = _load_toml(config_path)
    cli_defaults = _parse_cli_defaults(data)
    design_name = _resolve_render_style(_get_dict(data, "render"))
    page_cfg = _get_dict(data, "page")
    resolved_paper_size = _resolve_page_size(
        override=paper_size,
        configured=page_cfg.get("size"),
    )
    qr_section = _get_dict(data, "qr")
    qr_data = _parse_qr_section(qr_section)
    qr_config = qr_data.to_qr_config()
    qr_chunk_size = DEFAULT_CHUNK_SIZE if qr_data.chunk_size is None else qr_data.chunk_size
    extension_chunking = _parse_extension_chunking_defaults(
        _get_nested_dict(data, "extension", "chunking")
    )
    return AppConfig(
        design_name=design_name,
        paper_size=resolved_paper_size,
        qr_config=qr_config,
        qr_chunk_size=qr_chunk_size,
        extension_chunking=extension_chunking,
        cli_defaults=cli_defaults,
    )


def load_cli_defaults(path: str | Path | None = None) -> CliDefaults:
    """Load only CLI defaults from the configured TOML file."""

    config_path = resolve_config_path(path)
    data = _load_toml(config_path)
    return _parse_cli_defaults(data)


def apply_render_style(config: AppConfig, style: str | None) -> AppConfig:
    """Override the configured built-in render style."""

    if not style:
        return config
    _ = resolve_render_style_path(style)
    return replace(config, design_name=style.strip().lower())


def _parse_qr_section(cfg: dict[str, object]) -> _QrSectionData:
    try:
        return _QrSectionData.model_validate(cfg)
    except ValidationError as exc:
        raise ValueError(_first_pydantic_value_error(exc)) from exc


def _resolve_page_size(*, override: str | None, configured: object) -> str:
    if override is not None:
        return _parse_page_size(override, field="paper_size")
    if configured is None:
        return DEFAULT_PAPER_SIZE
    return _parse_page_size(configured, field="page.size")


def _parse_page_size(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be one of: A4, LETTER")
    normalized = value.strip().upper()
    if normalized not in _PAGE_SIZES:
        raise ValueError(f"{field} must be one of: A4, LETTER")
    return normalized


def _resolve_render_style(cfg: dict[str, object]) -> str:
    """Resolve the single user-facing built-in render style setting."""

    style = _parse_optional_style_name(cfg.get("style"), field="render.style")
    if style is None:
        return DEFAULT_RENDER_STYLE
    _ = _resolve_style_path(style, field="render.style")
    return style.strip().lower()


def build_qr_config(cfg: dict[str, object] | None = None) -> QrConfig:
    """Build QR rendering config from a parsed TOML section."""

    return _parse_qr_section(cfg or {}).to_qr_config()


def _parse_cli_defaults(data: dict[str, object]) -> CliDefaults:
    """Parse nested CLI default sections from raw config data."""

    return CliDefaults(
        backup=_parse_backup_defaults(_get_nested_dict(data, "defaults", "backup")),
        recover=_parse_recover_defaults(_get_nested_dict(data, "defaults", "recover")),
        extend=_parse_extend_defaults(_get_nested_dict(data, "defaults", "extend")),
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


def _parse_extend_defaults(cfg: dict[str, object]) -> ExtendDefaults:
    """Parse `[defaults.extend]` values."""

    defaults = ExtendDefaults(
        base_dir=_parse_optional_unset_str(cfg.get("base_dir"), field="defaults.extend.base_dir"),
        unlock_policy=_parse_optional_extension_unlock_policy(
            cfg.get("unlock_policy"),
            field="defaults.extend.unlock_policy",
        ),
        shard_threshold=_parse_optional_positive_int_or_unset_zero(
            cfg.get("shard_threshold"),
            field="defaults.extend.shard_threshold",
        ),
        shard_count=_parse_optional_positive_int_or_unset_zero(
            cfg.get("shard_count"),
            field="defaults.extend.shard_count",
        ),
        signing_key_mode=_parse_optional_extension_signing_key_mode(
            cfg.get("signing_key_mode"),
            field="defaults.extend.signing_key_mode",
        ),
        signing_key_shard_threshold=_parse_optional_positive_int_or_unset_zero(
            cfg.get("signing_key_shard_threshold"),
            field="defaults.extend.signing_key_shard_threshold",
        ),
        signing_key_shard_count=_parse_optional_positive_int_or_unset_zero(
            cfg.get("signing_key_shard_count"),
            field="defaults.extend.signing_key_shard_count",
        ),
        qr_payload_codec=_parse_required_qr_payload_codec(
            cfg.get("qr_payload_codec", "raw"),
            field="defaults.extend.qr_payload_codec",
        ),
    )
    _validate_extend_defaults(defaults)
    return defaults


def _validate_extend_defaults(defaults: ExtendDefaults) -> None:
    """Validate cross-field extension default constraints."""

    if (defaults.shard_threshold is None) != (defaults.shard_count is None):
        raise ValueError("defaults.extend.shard_threshold and shard_count must be set together")
    if (
        defaults.shard_threshold is not None
        and defaults.shard_count is not None
        and defaults.shard_count < defaults.shard_threshold
    ):
        raise ValueError("defaults.extend.shard_count must be >= shard_threshold")
    if defaults.unlock_policy == "reuse-root" and (
        defaults.shard_threshold is not None or defaults.shard_count is not None
    ):
        raise ValueError("defaults.extend.unlock_policy='reuse-root' cannot set extension shards")

    signing_threshold = defaults.signing_key_shard_threshold
    signing_count = defaults.signing_key_shard_count
    if (signing_threshold is None) != (signing_count is None):
        raise ValueError(
            "defaults.extend.signing_key_shard_threshold and signing_key_shard_count "
            "must be set together"
        )
    if signing_threshold is not None or signing_count is not None:
        if defaults.signing_key_mode != "sharded":
            raise ValueError(
                "defaults.extend.signing_key_shard_threshold and signing_key_shard_count "
                "require signing_key_mode='sharded'"
            )
        if signing_threshold is not None and signing_count is not None:
            if signing_count < signing_threshold:
                raise ValueError(
                    "defaults.extend.signing_key_shard_count must be >= signing_key_shard_threshold"
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


def _parse_extension_chunking_defaults(cfg: dict[str, object]) -> ExtensionChunkingDefaults:
    try:
        return _ExtensionChunkingData.model_validate(cfg).to_public()
    except ValidationError as exc:
        raise ValueError(_first_pydantic_value_error(exc)) from exc


def _validate_extension_chunking_size(*, field: str, value: int) -> None:
    label = f"extension.chunking.{field}"
    if value < MIN_EXTENSION_CHUNK_SIZE:
        raise ValueError(f"{label} must be >= {MIN_EXTENSION_CHUNK_SIZE}")
    if value > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ValueError(f"{label} must be <= MAX_DECOMPRESSED_PAYLOAD_BYTES")


def _first_pydantic_value_error(exc: ValidationError) -> str:
    first_error = exc.errors()[0]
    context_error = first_error.get("ctx", {}).get("error")
    if isinstance(context_error, ValueError):
        return str(context_error)
    return str(exc)


def _resolve_style_path(style: str, *, field: str) -> Path:
    """Resolve a render style and rewrite errors with config field context."""

    try:
        return resolve_render_style_path(style)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from exc


def _parse_optional_style_name(value: object, *, field: str) -> str | None:
    """Parse an optional render style name, rejecting blank strings."""

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
    """Parse a TOML boolean config value with a default."""

    if value is None:
        return default
    return _require_bool(value, field=field)


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


def _parse_optional_extension_unlock_policy(
    value: object,
    *,
    field: str,
) -> Literal["self-contained", "reuse-root"] | None:
    """Parse the optional extension unlock policy."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be 'self-contained', 'reuse-root', or empty")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in {"self-contained", "reuse-root"}:
        raise ValueError(f"{field} must be 'self-contained', 'reuse-root', or empty")
    return cast(Literal["self-contained", "reuse-root"], normalized)


def _parse_optional_extension_signing_key_mode(
    value: object,
    *,
    field: str,
) -> Literal["not-stored", "sharded"] | None:
    """Parse the optional extension signing-key storage mode."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be 'not-stored', 'sharded', or empty")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in {"not-stored", "sharded"}:
        raise ValueError(f"{field} must be 'not-stored', 'sharded', or empty")
    return cast(Literal["not-stored", "sharded"], normalized)


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
    """Parse a TOML integer field without scalar coercion."""

    return _require_int(value, field=field)


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


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
