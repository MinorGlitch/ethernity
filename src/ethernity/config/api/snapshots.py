"""Read config state into the stable API snapshot shape."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Literal, cast

from ethernity.config._toml_support import load_toml
from ethernity.config.api.contracts import ApiConfigSnapshot, ConfigTargetSource
from ethernity.config.install import (
    ONBOARDING_FIELDS,
    first_run_onboarding_configured_fields,
    first_run_onboarding_needed,
    list_render_styles,
)
from ethernity.config.load import load_app_config, load_cli_defaults
from ethernity.config.paths import DEFAULT_CONFIG_PATH, DEFAULT_RENDER_STYLE
from ethernity.config.types import AppConfig, CliDefaults
from ethernity.config.value_constraints import (
    EXTENSION_SIGNING_KEY_MODES as _EXTENSION_SIGNING_KEY_MODES,
    EXTENSION_UNLOCK_POLICIES as _EXTENSION_UNLOCK_POLICIES,
    PAGE_SIZES as _PAGE_SIZES,
    PAYLOAD_CODECS as _PAYLOAD_CODECS,
    QR_ERROR_LEVELS as _QR_ERROR_LEVELS,
    QR_PAYLOAD_CODECS as _QR_PAYLOAD_CODECS,
    SIGNING_KEY_MODES as _SIGNING_KEY_MODES,
    extension_chunking_profile_is_valid,
)


def snapshot_from_path(path: Path, *, source: ConfigTargetSource) -> ApiConfigSnapshot:
    if not path.exists():
        return ApiConfigSnapshot(
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
            cli_defaults = load_cli_defaults(path)
            values = _snapshot_values_from_loaded(raw, config=config, cli_defaults=cli_defaults)
        except (OSError, RuntimeError, ValueError) as exc:
            status = "invalid_values"
            errors.append(_config_load_error(exc, code="CONFIG_INVALID_CURRENT"))
            values = _snapshot_values_from_raw(raw)
    else:
        values = _snapshot_values_from_raw(raw)

    return ApiConfigSnapshot(
        path=str(path),
        source=source,
        status=status,
        errors=tuple(errors),
        values=values,
        options=_config_options(),
        onboarding=_snapshot_onboarding(source=source),
    )


def _raw_render_style(raw: dict[str, object]) -> str:
    render = raw.get("render")
    if isinstance(render, dict):
        value = render.get("style")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_RENDER_STYLE


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
    cli_defaults = load_cli_defaults(DEFAULT_CONFIG_PATH)
    return _snapshot_values_from_loaded({}, config=config, cli_defaults=cli_defaults)


def _snapshot_values_from_loaded(
    raw: dict[str, object],
    *,
    config: AppConfig,
    cli_defaults: CliDefaults,
) -> dict[str, object]:
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
            "extend": {
                "base_dir": cli_defaults.extend.base_dir,
                "unlock_policy": cli_defaults.extend.unlock_policy,
                "shard_threshold": cli_defaults.extend.shard_threshold,
                "shard_count": cli_defaults.extend.shard_count,
                "signing_key_mode": cli_defaults.extend.signing_key_mode,
                "signing_key_shard_threshold": cli_defaults.extend.signing_key_shard_threshold,
                "signing_key_shard_count": cli_defaults.extend.signing_key_shard_count,
                "qr_payload_codec": cli_defaults.extend.qr_payload_codec,
            },
        },
        "ui": {
            "quiet": cli_defaults.ui.quiet,
            "no_color": cli_defaults.ui.no_color,
            "no_animations": cli_defaults.ui.no_animations,
            "show_internals": cli_defaults.ui.show_internals,
        },
        "debug": {"max_bytes": cli_defaults.debug.max_bytes},
        "runtime": {"render_jobs": cli_defaults.runtime.render_jobs},
    }


def _snapshot_values_from_raw(raw: dict[str, object]) -> dict[str, object]:
    values = copy.deepcopy(_default_snapshot_values())
    render = cast(dict[str, object], values["render"])
    page = cast(dict[str, object], values["page"])
    qr = cast(dict[str, object], values["qr"])
    extension = cast(dict[str, object], values["extension"])
    extension_chunking = cast(dict[str, object], extension["chunking"])
    defaults = cast(dict[str, object], values["defaults"])
    backup = cast(dict[str, object], defaults["backup"])
    recover = cast(dict[str, object], defaults["recover"])
    extend = cast(dict[str, object], defaults["extend"])
    ui = cast(dict[str, object], values["ui"])
    debug = cast(dict[str, object], values["debug"])
    runtime = cast(dict[str, object], values["runtime"])

    render["style"] = _raw_render_style(raw)

    render_table = _raw_table(raw, "render")
    page_table = _raw_table(raw, "page")
    qr_table = _raw_table(raw, "qr")
    extension_chunking_table = _raw_table(_raw_table(raw, "extension"), "chunking")
    backup_table = _raw_table(_raw_table(raw, "defaults"), "backup")
    recover_table = _raw_table(_raw_table(raw, "defaults"), "recover")
    extend_table = _raw_table(_raw_table(raw, "defaults"), "extend")
    ui_table = _raw_table(raw, "ui")
    debug_table = _raw_table(raw, "debug")
    runtime_table = _raw_table(raw, "runtime")
    default_extension_chunking = dict(extension_chunking)

    render["style"] = _coerce_design_name(render_table.get("style"), fallback=render["style"])
    page["size"] = _coerce_enum(page_table.get("size"), allowed=_PAGE_SIZES, fallback=page["size"])
    qr["error"] = _coerce_enum(
        qr_table.get("error"), allowed=_QR_ERROR_LEVELS, fallback=qr["error"]
    )
    qr["chunk_size"] = _coerce_optional_positive_int(
        qr_table.get("chunk_size"), fallback=qr["chunk_size"]
    )
    extension_chunking["target_size"] = _coerce_optional_positive_int(
        extension_chunking_table.get("target_size"),
        fallback=extension_chunking["target_size"],
    )
    extension_chunking["min_size"] = _coerce_optional_positive_int(
        extension_chunking_table.get("min_size"),
        fallback=extension_chunking["min_size"],
    )
    extension_chunking["max_size"] = _coerce_optional_positive_int(
        extension_chunking_table.get("max_size"),
        fallback=extension_chunking["max_size"],
    )
    if not extension_chunking_profile_is_valid(
        target_size=cast(int, extension_chunking["target_size"]),
        min_size=cast(int, extension_chunking["min_size"]),
        max_size=cast(int, extension_chunking["max_size"]),
    ):
        extension_chunking.update(default_extension_chunking)

    backup["base_dir"] = _coerce_optional_string(
        backup_table.get("base_dir"), fallback=backup["base_dir"]
    )
    backup["output_dir"] = _coerce_optional_string(
        backup_table.get("output_dir"), fallback=backup["output_dir"]
    )
    backup["shard_threshold"] = _coerce_optional_positive_int(
        backup_table.get("shard_threshold"), fallback=backup["shard_threshold"]
    )
    backup["shard_count"] = _coerce_optional_positive_int(
        backup_table.get("shard_count"), fallback=backup["shard_count"]
    )
    backup["signing_key_mode"] = _coerce_optional_enum(
        backup_table.get("signing_key_mode"),
        allowed=_SIGNING_KEY_MODES,
        fallback=backup["signing_key_mode"],
    )
    backup["signing_key_shard_threshold"] = _coerce_optional_positive_int(
        backup_table.get("signing_key_shard_threshold"),
        fallback=backup["signing_key_shard_threshold"],
    )
    backup["signing_key_shard_count"] = _coerce_optional_positive_int(
        backup_table.get("signing_key_shard_count"),
        fallback=backup["signing_key_shard_count"],
    )
    backup["payload_codec"] = _coerce_enum(
        backup_table.get("payload_codec"),
        allowed=_PAYLOAD_CODECS,
        fallback=backup["payload_codec"],
    )
    backup["qr_payload_codec"] = _coerce_enum(
        backup_table.get("qr_payload_codec"),
        allowed=_QR_PAYLOAD_CODECS,
        fallback=backup["qr_payload_codec"],
    )
    recover["output"] = _coerce_optional_string(
        recover_table.get("output"), fallback=recover["output"]
    )
    extend["base_dir"] = _coerce_optional_string(
        extend_table.get("base_dir"), fallback=extend["base_dir"]
    )
    extend["unlock_policy"] = _coerce_optional_enum(
        extend_table.get("unlock_policy"),
        allowed=_EXTENSION_UNLOCK_POLICIES,
        fallback=extend["unlock_policy"],
    )
    extend["shard_threshold"] = _coerce_optional_positive_int(
        extend_table.get("shard_threshold"), fallback=extend["shard_threshold"]
    )
    extend["shard_count"] = _coerce_optional_positive_int(
        extend_table.get("shard_count"), fallback=extend["shard_count"]
    )
    extend["signing_key_mode"] = _coerce_optional_enum(
        extend_table.get("signing_key_mode"),
        allowed=_EXTENSION_SIGNING_KEY_MODES,
        fallback=extend["signing_key_mode"],
    )
    extend["signing_key_shard_threshold"] = _coerce_optional_positive_int(
        extend_table.get("signing_key_shard_threshold"),
        fallback=extend["signing_key_shard_threshold"],
    )
    extend["signing_key_shard_count"] = _coerce_optional_positive_int(
        extend_table.get("signing_key_shard_count"),
        fallback=extend["signing_key_shard_count"],
    )
    extend["qr_payload_codec"] = _coerce_enum(
        extend_table.get("qr_payload_codec"),
        allowed=_QR_PAYLOAD_CODECS,
        fallback=extend["qr_payload_codec"],
    )
    ui["quiet"] = _coerce_bool(ui_table.get("quiet"), fallback=ui["quiet"])
    ui["no_color"] = _coerce_bool(ui_table.get("no_color"), fallback=ui["no_color"])
    ui["no_animations"] = _coerce_bool(ui_table.get("no_animations"), fallback=ui["no_animations"])
    ui["show_internals"] = _coerce_bool(
        ui_table.get("show_internals"),
        fallback=ui["show_internals"],
    )
    debug["max_bytes"] = _coerce_optional_positive_int(
        debug_table.get("max_bytes"), fallback=debug["max_bytes"]
    )
    runtime["render_jobs"] = _coerce_render_jobs(
        runtime_table.get("render_jobs"), fallback=runtime["render_jobs"]
    )
    return values


def _raw_table(raw: dict[str, object], key: str) -> dict[str, object]:
    value = raw.get(key)
    return value if isinstance(value, dict) else {}


def _coerce_enum(value: object, *, allowed: tuple[str, ...], fallback: object) -> object:
    if not isinstance(value, str):
        return fallback
    text = value.strip()
    if not text:
        return fallback
    normalized = text.upper() if allowed in {_PAGE_SIZES, _QR_ERROR_LEVELS} else text.lower()
    return normalized if normalized in allowed else fallback


def _coerce_design_name(value: object, *, fallback: object) -> object:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip().lower()
    return normalized if normalized in list_render_styles() else fallback


def _coerce_optional_enum(value: object, *, allowed: tuple[str, ...], fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, str) and not value.strip():
        return None
    return _coerce_enum(value, allowed=allowed, fallback=fallback)


def _coerce_optional_positive_int(value: object, *, fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, int) and not isinstance(value, bool):
        if value == 0:
            return None
        return value if value > 0 else fallback
    return fallback


def _coerce_optional_string(value: object, *, fallback: object) -> object:
    if value is None:
        return fallback
    if not isinstance(value, str):
        return fallback
    normalized = value.strip().lower()
    return normalized or None


def _coerce_bool(value: object, *, fallback: object) -> object:
    return value if isinstance(value, bool) else fallback


def _coerce_render_jobs(value: object, *, fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized == "auto":
            return normalized
    return fallback


def _config_options() -> dict[str, object]:
    return {
        "render_styles": sorted(list_render_styles().keys()),
        "page_sizes": list(_PAGE_SIZES),
        "qr_error_correction": list(_QR_ERROR_LEVELS),
        "payload_codecs": list(_PAYLOAD_CODECS),
        "qr_payload_codecs": list(_QR_PAYLOAD_CODECS),
        "signing_key_modes": list(_SIGNING_KEY_MODES),
        "extension_unlock_policies": list(_EXTENSION_UNLOCK_POLICIES),
        "extension_signing_key_modes": list(_EXTENSION_SIGNING_KEY_MODES),
        "onboarding_fields": list(ONBOARDING_FIELDS),
    }


__all__ = ["snapshot_from_path"]
