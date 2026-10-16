"""Read configuration values and available settings for the editor."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ethernity.config._toml_support import load_toml
from ethernity.config.editing.models import ConfigSnapshot, ConfigTargetSource
from ethernity.config.install import (
    ONBOARDING_FIELDS,
    first_run_onboarding_configured_fields,
    first_run_onboarding_needed,
    list_render_styles,
)
from ethernity.config.load import load_app_config
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.config.types import AppConfig
from ethernity.config.validation import ConfigValueError, normalize_value
from ethernity.config.value_constraints import (
    PAGE_SIZES as _PAGE_SIZES,
    PAYLOAD_CODECS as _PAYLOAD_CODECS,
    QR_ERROR_LEVELS as _QR_ERROR_LEVELS,
    QR_PAYLOAD_CODECS as _QR_PAYLOAD_CODECS,
    SIGNING_KEY_MODES as _SIGNING_KEY_MODES,
)


def snapshot_from_path(path: Path, *, source: ConfigTargetSource) -> ConfigSnapshot:
    if not path.exists():
        return ConfigSnapshot(
            path=str(path),
            source=source,
            status="valid",
            errors=(),
            values=_default_snapshot_values(),
            options=_config_options(),
            onboarding=_snapshot_onboarding(source=source),
        )

    status: Literal["valid", "invalid_toml", "invalid_values"] = "valid"
    errors: list[dict[str, object]] = []
    raw: dict[str, object] = {}
    try:
        raw = load_toml(path)
    except (OSError, ValueError) as exc:
        status = "invalid_toml"
        errors.append(_config_load_error(exc, code="CONFIG_TOML_INVALID"))

    if status == "valid":
        try:
            config = load_app_config(path)
            values = _snapshot_values_from_loaded(config)
        except (OSError, RuntimeError, ValueError) as exc:
            status = "invalid_values"
            errors.append(_config_load_error(exc, code="CONFIG_INVALID_CURRENT"))
            values = _snapshot_values_from_raw(raw)
    else:
        values = _snapshot_values_from_raw(raw)

    return ConfigSnapshot(
        path=str(path),
        source=source,
        status=status,
        errors=tuple(errors),
        values=values,
        options=_config_options(),
        onboarding=_snapshot_onboarding(source=source),
    )


def _snapshot_onboarding(*, source: ConfigTargetSource) -> dict[str, object]:
    if source != "user":
        return {
            "needed": False,
            "configured_fields": [],
            "available_fields": list(ONBOARDING_FIELDS),
        }
    return {
        "needed": first_run_onboarding_needed(),
        "configured_fields": sorted(first_run_onboarding_configured_fields()),
        "available_fields": list(ONBOARDING_FIELDS),
    }


def _config_load_error(exc: BaseException, *, code: str) -> dict[str, object]:
    return {
        "code": code,
        "message": str(exc),
        "details": {"error_type": type(exc).__name__},
    }


def _default_snapshot_values() -> dict[str, object]:
    config = load_app_config(DEFAULT_CONFIG_PATH)
    return _snapshot_values_from_loaded(config)


def _snapshot_values_from_loaded(config: AppConfig) -> dict[str, object]:
    cli_defaults = config.cli_defaults
    return {
        "render": {"style": config.design_name},
        "page": {"size": config.paper_size},
        "qr": {"error": config.qr_config.error, "chunk_size": config.qr_chunk_size},
        "extension": {
            "chunking": {
                "target_size": config.extension_chunking.target_size,
                "min_size": config.extension_chunking.min_size,
                "max_size": config.extension_chunking.max_size,
            },
        },
        "defaults": {
            "backup": {
                "base_dir": cli_defaults.backup.base_dir,
                "output_dir": cli_defaults.backup.output_dir,
                "shard_threshold": cli_defaults.backup.shard_threshold,
                "shard_count": cli_defaults.backup.shard_count,
                "signing_key_mode": cli_defaults.backup.signing_key_mode,
                "signing_key_shard_threshold": cli_defaults.backup.signing_key_shard_threshold,
                "signing_key_shard_count": cli_defaults.backup.signing_key_shard_count,
                "payload_codec": cli_defaults.backup.payload_codec,
                "qr_payload_codec": cli_defaults.backup.qr_payload_codec,
            },
            "recover": {"output": cli_defaults.recover.output},
            "add_files": {
                "base_dir": cli_defaults.add_files.base_dir,
                "qr_payload_codec": cli_defaults.add_files.qr_payload_codec,
            },
        },
        "ui": {
            "quiet": cli_defaults.ui.quiet,
            "no_color": cli_defaults.ui.no_color,
            "no_animations": cli_defaults.ui.no_animations,
            "show_internals": cli_defaults.ui.show_internals,
        },
        "debug": {"max_bytes": cli_defaults.debug.max_bytes},
    }


def _snapshot_values_from_raw(raw: dict[str, object]) -> dict[str, object]:
    values = _default_snapshot_values()
    _overlay_raw_values(values, raw)
    return values


def _overlay_raw_values(
    values: dict[str, object], raw: dict[str, object], prefix: tuple[str, ...] = ()
) -> None:
    for key, default in values.items():
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(default, dict):
            if isinstance(value, dict):
                _overlay_raw_values(default, value, (*prefix, key))
            else:
                values[key] = value
            continue
        try:
            values[key] = normalize_value(".".join((*prefix, key)), value)
        except ConfigValueError:
            # Keep invalid values visible so users can repair them before saving.
            values[key] = value


def _config_options() -> dict[str, object]:
    return {
        "render_styles": sorted(list_render_styles().keys()),
        "page_sizes": list(_PAGE_SIZES),
        "qr_error_correction": list(_QR_ERROR_LEVELS),
        "payload_codecs": list(_PAYLOAD_CODECS),
        "qr_payload_codecs": list(_QR_PAYLOAD_CODECS),
        "signing_key_modes": list(_SIGNING_KEY_MODES),
        "onboarding_fields": list(ONBOARDING_FIELDS),
    }


__all__ = ["snapshot_from_path"]
