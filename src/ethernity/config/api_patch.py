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

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from ethernity.config._toml_support import (
    toml_quote as _toml_quote,
    upsert_table_key as _upsert_table_key,
    write_text_atomic as _write_text_atomic,
)
from ethernity.config.install import (
    ONBOARDING_FIELDS,
    clear_first_run_onboarding_marker,
    first_run_onboarding_configured_fields,
    first_run_onboarding_marker_path,
    first_run_onboarding_needed,
    list_render_styles,
    mark_first_run_onboarding_complete,
    resolve_config_snapshot_path,
    resolve_writable_config_path,
)
from ethernity.config.load import _load_toml, load_app_config, load_cli_defaults
from ethernity.config.paths import DEFAULT_CONFIG_PATH, DEFAULT_RENDER_STYLE
from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES
from ethernity.formats.extension_envelope import MIN_EXTENSION_CHUNK_SIZE

ConfigTargetSource = Literal["default", "user", "explicit"]

_CONFIG_SET_ALLOWED_KEYS = frozenset({"values", "onboarding"})
_CONFIG_ONBOARDING_ALLOWED_KEYS = frozenset({"mark_complete", "configured_fields"})
_PAGE_SIZES = ("A4", "LETTER")
_QR_ERROR_LEVELS = ("L", "M", "Q", "H")
_PAYLOAD_CODECS = ("auto", "raw", "gzip")
_QR_PAYLOAD_CODECS = ("raw", "base64")
_SIGNING_KEY_MODES = ("embedded", "sharded")
_EXTENSION_UNLOCK_POLICIES = ("self-contained", "reuse-root")
_EXTENSION_SIGNING_KEY_MODES = ("not-stored", "sharded")


def _extension_chunking_profile_is_valid(*, target_size: int, min_size: int, max_size: int) -> bool:
    return (
        MIN_EXTENSION_CHUNK_SIZE <= min_size <= target_size <= max_size
        and target_size <= MAX_DECOMPRESSED_PAYLOAD_BYTES
        and max_size <= MAX_DECOMPRESSED_PAYLOAD_BYTES
    )


@dataclass(frozen=True)
class ConfigPatchError(ValueError):
    code: str
    message: str
    details: dict[str, Any]

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)


@dataclass(frozen=True)
class ApiConfigSnapshot:
    path: str
    source: ConfigTargetSource
    status: Literal["valid", "invalid_toml", "invalid_values"]
    errors: tuple[dict[str, object], ...]
    values: dict[str, object]
    options: dict[str, object]
    onboarding: dict[str, object]


@dataclass(frozen=True)
class OnboardingPatchPlan:
    mark_complete: bool
    configured_fields: frozenset[str]


def get_api_config_snapshot(path: str | Path | None = None) -> ApiConfigSnapshot:
    target_path, source = _resolve_config_target(path, for_write=False)
    return _snapshot_from_path(target_path, source=source)


def apply_api_config_patch(
    path: str | Path | None,
    patch: dict[str, object],
) -> ApiConfigSnapshot:
    target_path, source = _resolve_config_target(path, for_write=True)
    _validate_patch_shape(patch)
    onboarding_plan = _build_onboarding_patch_plan(patch.get("onboarding"), source=source)

    original_text = target_path.read_text(encoding="utf-8") if target_path.exists() else None
    current = _snapshot_from_path(target_path, source=source)
    current_values = copy.deepcopy(current.values)
    patch_values = patch.get("values")
    if patch_values is not None:
        if not isinstance(patch_values, dict):
            raise ConfigPatchError(
                code="CONFIG_INVALID_VALUE",
                message="values must be an object",
                details={"field": "values"},
            )
        _merge_values_patch(current_values, patch_values, prefix=("values",))

    validated_values = _validate_config_values(current_values)
    base_text = (
        original_text
        if original_text is not None and current.status != "invalid_toml"
        else DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    )
    updated = _apply_values_to_text(base_text, validated_values)
    config_changed = original_text is None or updated != original_text
    marker_state = _read_marker_state() if onboarding_plan is not None else None
    writable_target_path: Path | None = None
    created_config = False

    try:
        writable_target_path = target_path
        created_config = original_text is None and config_changed
        if config_changed:
            _write_text_atomic(writable_target_path, updated)
        if onboarding_plan is not None:
            _apply_onboarding_plan(onboarding_plan)
    except Exception:
        if onboarding_plan is not None:
            _restore_marker_state(marker_state)
        if writable_target_path is not None:
            if created_config:
                writable_target_path.unlink(missing_ok=True)
            elif config_changed and original_text is not None:
                _write_text_atomic(writable_target_path, original_text)
        raise

    return _snapshot_from_path(writable_target_path or target_path, source=source)


def _resolve_config_target(
    path: str | Path | None,
    *,
    for_write: bool,
) -> tuple[Path, ConfigTargetSource]:
    source: ConfigTargetSource = "explicit" if path else "user"
    if for_write:
        return resolve_writable_config_path(path), source
    target_path = resolve_config_snapshot_path(path)
    if not path and target_path == DEFAULT_CONFIG_PATH:
        source = "default"
    return target_path, source


def _snapshot_from_path(path: Path, *, source: ConfigTargetSource) -> ApiConfigSnapshot:
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
        raw = _load_toml(path)
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
    config,
    cli_defaults,
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
                "signing_key_shard_threshold": (cli_defaults.extend.signing_key_shard_threshold),
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
    if not _extension_chunking_profile_is_valid(
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


def _validate_patch_shape(patch: dict[str, object]) -> None:
    unknown_keys = sorted(set(patch) - _CONFIG_SET_ALLOWED_KEYS)
    if unknown_keys:
        field = unknown_keys[0]
        raise ConfigPatchError(
            code="CONFIG_UNKNOWN_FIELD",
            message=f"unknown config patch field: {field}",
            details={"field": field},
        )


def _merge_values_patch(
    target: dict[str, object],
    patch: dict[str, object],
    *,
    prefix: tuple[str, ...],
) -> None:
    for key, value in patch.items():
        if key not in target:
            field = ".".join((*prefix, key))
            raise ConfigPatchError(
                code="CONFIG_UNKNOWN_FIELD",
                message=f"unknown config field: {field}",
                details={"field": field},
            )
        existing = target[key]
        if isinstance(existing, dict):
            if not isinstance(value, dict):
                field = ".".join((*prefix, key))
                raise ConfigPatchError(
                    code="CONFIG_INVALID_VALUE",
                    message=f"{field} must be an object",
                    details={"field": field},
                )
            _merge_values_patch(cast(dict[str, object], existing), value, prefix=(*prefix, key))
            continue
        target[key] = value


def _validate_config_values(values: dict[str, object]) -> dict[str, object]:
    render = _expect_section(values, "render")
    page = _expect_section(values, "page")
    qr = _expect_section(values, "qr")
    extension = _expect_section(values, "extension")
    extension_chunking = _expect_section(extension, "chunking", prefix="extension")
    defaults = _expect_section(values, "defaults")
    backup = _expect_section(defaults, "backup", prefix="defaults")
    recover = _expect_section(defaults, "recover", prefix="defaults")
    extend = _expect_section(defaults, "extend", prefix="defaults")
    ui = _expect_section(values, "ui")
    debug = _expect_section(values, "debug")
    runtime = _expect_section(values, "runtime")

    render_style = _validate_design_name(render.get("style"), field="values.render.style")
    page_size = _validate_enum(page.get("size"), field="values.page.size", allowed=_PAGE_SIZES)
    qr_error = _validate_enum(qr.get("error"), field="values.qr.error", allowed=_QR_ERROR_LEVELS)
    qr_chunk_size = _validate_positive_int(qr.get("chunk_size"), field="values.qr.chunk_size")
    chunking_target_size = _validate_positive_int(
        extension_chunking.get("target_size"),
        field="values.extension.chunking.target_size",
    )
    chunking_min_size = _validate_positive_int(
        extension_chunking.get("min_size"),
        field="values.extension.chunking.min_size",
    )
    chunking_max_size = _validate_positive_int(
        extension_chunking.get("max_size"),
        field="values.extension.chunking.max_size",
    )
    for field, value in (
        ("target_size", chunking_target_size),
        ("min_size", chunking_min_size),
        ("max_size", chunking_max_size),
    ):
        _validate_extension_chunking_size(field=field, value=value)
    if not chunking_min_size <= chunking_target_size <= chunking_max_size:
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message=("extension.chunking sizes must satisfy min_size <= target_size <= max_size"),
            details={"field": "values.extension.chunking"},
        )

    shard_threshold = _validate_optional_count(
        backup.get("shard_threshold"),
        field="values.defaults.backup.shard_threshold",
    )
    shard_count = _validate_optional_count(
        backup.get("shard_count"),
        field="values.defaults.backup.shard_count",
    )
    if (shard_threshold is None) != (shard_count is None):
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message="defaults.backup.shard_threshold and shard_count must be set together",
            details={"field": "values.defaults.backup"},
        )
    if shard_threshold is not None and shard_count is not None and shard_count < shard_threshold:
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message="defaults.backup.shard_count must be >= shard_threshold",
            details={"field": "values.defaults.backup.shard_count"},
        )

    signing_key_mode = _validate_optional_enum(
        backup.get("signing_key_mode"),
        field="values.defaults.backup.signing_key_mode",
        allowed=_SIGNING_KEY_MODES,
    )
    if signing_key_mode == "sharded" and (shard_threshold is None or shard_count is None):
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message="defaults.backup.signing_key_mode='sharded' requires passphrase sharding",
            details={"field": "values.defaults.backup.signing_key_mode"},
        )

    signing_key_shard_threshold = _validate_optional_count(
        backup.get("signing_key_shard_threshold"),
        field="values.defaults.backup.signing_key_shard_threshold",
    )
    signing_key_shard_count = _validate_optional_count(
        backup.get("signing_key_shard_count"),
        field="values.defaults.backup.signing_key_shard_count",
    )
    if (signing_key_shard_threshold is None) != (signing_key_shard_count is None):
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message=(
                "defaults.backup.signing_key_shard_threshold and signing_key_shard_count "
                "must be set together"
            ),
            details={"field": "values.defaults.backup"},
        )
    if signing_key_shard_threshold is not None or signing_key_shard_count is not None:
        if signing_key_mode != "sharded":
            raise ConfigPatchError(
                code="CONFIG_CONFLICT",
                message=(
                    "defaults.backup.signing_key_shard_threshold and signing_key_shard_count "
                    "require signing_key_mode='sharded'"
                ),
                details={"field": "values.defaults.backup.signing_key_mode"},
            )
        if (
            signing_key_shard_threshold is not None
            and signing_key_shard_count is not None
            and signing_key_shard_count < signing_key_shard_threshold
        ):
            raise ConfigPatchError(
                code="CONFIG_CONFLICT",
                message=(
                    "defaults.backup.signing_key_shard_count must be >= signing_key_shard_threshold"
                ),
                details={"field": "values.defaults.backup.signing_key_shard_count"},
            )

    extend_unlock_policy = _validate_optional_enum(
        extend.get("unlock_policy"),
        field="values.defaults.extend.unlock_policy",
        allowed=_EXTENSION_UNLOCK_POLICIES,
    )
    extend_shard_threshold = _validate_optional_count(
        extend.get("shard_threshold"),
        field="values.defaults.extend.shard_threshold",
    )
    extend_shard_count = _validate_optional_count(
        extend.get("shard_count"),
        field="values.defaults.extend.shard_count",
    )
    if (extend_shard_threshold is None) != (extend_shard_count is None):
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message="defaults.extend.shard_threshold and shard_count must be set together",
            details={"field": "values.defaults.extend"},
        )
    if (
        extend_shard_threshold is not None
        and extend_shard_count is not None
        and extend_shard_count < extend_shard_threshold
    ):
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message="defaults.extend.shard_count must be >= shard_threshold",
            details={"field": "values.defaults.extend.shard_count"},
        )
    if extend_unlock_policy == "reuse-root" and (
        extend_shard_threshold is not None or extend_shard_count is not None
    ):
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message="defaults.extend.unlock_policy='reuse-root' cannot set extension shards",
            details={"field": "values.defaults.extend.unlock_policy"},
        )

    extend_signing_key_mode = _validate_optional_enum(
        extend.get("signing_key_mode"),
        field="values.defaults.extend.signing_key_mode",
        allowed=_EXTENSION_SIGNING_KEY_MODES,
    )
    extend_signing_key_shard_threshold = _validate_optional_count(
        extend.get("signing_key_shard_threshold"),
        field="values.defaults.extend.signing_key_shard_threshold",
    )
    extend_signing_key_shard_count = _validate_optional_count(
        extend.get("signing_key_shard_count"),
        field="values.defaults.extend.signing_key_shard_count",
    )
    if (extend_signing_key_shard_threshold is None) != (extend_signing_key_shard_count is None):
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message=(
                "defaults.extend.signing_key_shard_threshold and signing_key_shard_count "
                "must be set together"
            ),
            details={"field": "values.defaults.extend"},
        )
    if extend_signing_key_shard_threshold is not None or extend_signing_key_shard_count is not None:
        if extend_signing_key_mode != "sharded":
            raise ConfigPatchError(
                code="CONFIG_CONFLICT",
                message=(
                    "defaults.extend.signing_key_shard_threshold and "
                    "signing_key_shard_count require signing_key_mode='sharded'"
                ),
                details={"field": "values.defaults.extend.signing_key_mode"},
            )
        if (
            extend_signing_key_shard_threshold is not None
            and extend_signing_key_shard_count is not None
            and extend_signing_key_shard_count < extend_signing_key_shard_threshold
        ):
            raise ConfigPatchError(
                code="CONFIG_CONFLICT",
                message=(
                    "defaults.extend.signing_key_shard_count must be >= signing_key_shard_threshold"
                ),
                details={"field": "values.defaults.extend.signing_key_shard_count"},
            )

    render_jobs = _validate_render_jobs(
        runtime.get("render_jobs"), field="values.runtime.render_jobs"
    )
    debug_max_bytes = _validate_optional_positive_int(
        debug.get("max_bytes"),
        field="values.debug.max_bytes",
    )

    return {
        "render": {"style": render_style},
        "page": {
            "size": page_size,
        },
        "qr": {
            "error": qr_error,
            "chunk_size": qr_chunk_size,
        },
        "extension": {
            "chunking": {
                "target_size": chunking_target_size,
                "min_size": chunking_min_size,
                "max_size": chunking_max_size,
            },
        },
        "defaults": {
            "backup": {
                "base_dir": _validate_optional_string(
                    backup.get("base_dir"),
                    field="values.defaults.backup.base_dir",
                ),
                "output_dir": _validate_optional_string(
                    backup.get("output_dir"),
                    field="values.defaults.backup.output_dir",
                ),
                "shard_threshold": shard_threshold,
                "shard_count": shard_count,
                "signing_key_mode": signing_key_mode,
                "signing_key_shard_threshold": signing_key_shard_threshold,
                "signing_key_shard_count": signing_key_shard_count,
                "payload_codec": _validate_enum(
                    backup.get("payload_codec"),
                    field="values.defaults.backup.payload_codec",
                    allowed=_PAYLOAD_CODECS,
                ),
                "qr_payload_codec": _validate_enum(
                    backup.get("qr_payload_codec"),
                    field="values.defaults.backup.qr_payload_codec",
                    allowed=_QR_PAYLOAD_CODECS,
                ),
            },
            "recover": {
                "output": _validate_optional_string(
                    recover.get("output"),
                    field="values.defaults.recover.output",
                ),
            },
            "extend": {
                "base_dir": _validate_optional_string(
                    extend.get("base_dir"),
                    field="values.defaults.extend.base_dir",
                ),
                "unlock_policy": extend_unlock_policy,
                "shard_threshold": extend_shard_threshold,
                "shard_count": extend_shard_count,
                "signing_key_mode": extend_signing_key_mode,
                "signing_key_shard_threshold": extend_signing_key_shard_threshold,
                "signing_key_shard_count": extend_signing_key_shard_count,
                "qr_payload_codec": _validate_enum(
                    extend.get("qr_payload_codec"),
                    field="values.defaults.extend.qr_payload_codec",
                    allowed=_QR_PAYLOAD_CODECS,
                ),
            },
        },
        "ui": {
            "quiet": _validate_bool(ui.get("quiet"), field="values.ui.quiet"),
            "no_color": _validate_bool(ui.get("no_color"), field="values.ui.no_color"),
            "no_animations": _validate_bool(
                ui.get("no_animations"),
                field="values.ui.no_animations",
            ),
            "show_internals": _validate_bool(
                ui.get("show_internals"),
                field="values.ui.show_internals",
            ),
        },
        "debug": {
            "max_bytes": debug_max_bytes,
        },
        "runtime": {
            "render_jobs": render_jobs,
        },
    }


def _expect_section(
    values: dict[str, object],
    key: str,
    *,
    prefix: str | None = None,
) -> dict[str, object]:
    value = values.get(key)
    if not isinstance(value, dict):
        field = f"{prefix}.{key}" if prefix else key
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"values.{field} must be an object",
            details={"field": f"values.{field}"},
        )
    return value


def _validate_design_name(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{field} must be a non-empty string",
            details={"field": field},
        )
    normalized = value.strip().lower()
    if normalized not in list_render_styles():
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{field} must be a supported design name",
            details={"field": field, "value": value},
        )
    return normalized


def _validate_enum(value: object, *, field: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str):
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{field} must be one of: {', '.join(allowed)}",
            details={"field": field},
        )
    text = value.strip()
    if allowed in {_PAGE_SIZES, _QR_ERROR_LEVELS}:
        canonical = text.upper()
    else:
        canonical = text.lower()
    if canonical not in allowed:
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{field} must be one of: {', '.join(allowed)}",
            details={"field": field, "value": value},
        )
    return canonical


def _validate_optional_enum(value: object, *, field: str, allowed: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _validate_enum(value, field=field, allowed=allowed)


def _validate_bool(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigPatchError(
        code="CONFIG_INVALID_VALUE",
        message=f"{field} must be a boolean",
        details={"field": field},
    )


def _validate_positive_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{field} must be a positive integer",
            details={"field": field},
        )
    return value


def _validate_extension_chunking_size(*, field: str, value: int) -> None:
    label = f"values.extension.chunking.{field}"
    if value < MIN_EXTENSION_CHUNK_SIZE:
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{label} must be >= {MIN_EXTENSION_CHUNK_SIZE}",
            details={"field": label},
        )
    if value > MAX_DECOMPRESSED_PAYLOAD_BYTES:
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{label} must be <= MAX_DECOMPRESSED_PAYLOAD_BYTES",
            details={"field": label},
        )


def _validate_optional_positive_int(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value == 0:
        return None
    return _validate_positive_int(value, field=field)


def _validate_optional_count(value: object, *, field: str) -> int | None:
    parsed = _validate_optional_positive_int(value, field=field)
    if parsed is not None and parsed > 255:
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{field} must be <= 255",
            details={"field": field, "value": parsed},
        )
    return parsed


def _validate_optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{field} must be a string or null",
            details={"field": field},
        )
    normalized = value.strip()
    return normalized or None


def _validate_render_jobs(value: object, *, field: str) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized == "auto":
            return "auto"
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message=f"{field} must be 'auto', a positive integer, or null",
            details={"field": field, "value": value},
        )
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise ConfigPatchError(
        code="CONFIG_INVALID_VALUE",
        message=f"{field} must be 'auto', a positive integer, or null",
        details={"field": field, "value": value},
    )


def _apply_values_to_text(original: str, values: dict[str, object]) -> str:
    line_ending = "\r\n" if "\r\n" in original else "\n"
    updated = original

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

    style = cast(str, render["style"])
    updated = _upsert_table_key(updated, table="render", key="style", value=_toml_quote(style))

    updated = _upsert_table_key(
        updated,
        table="page",
        key="size",
        value=_toml_quote(cast(str, page["size"])),
    )
    updated = _upsert_table_key(
        updated,
        table="qr",
        key="error",
        value=_toml_quote(cast(str, qr["error"])),
    )
    updated = _upsert_table_key(
        updated,
        table="qr",
        key="chunk_size",
        value=str(cast(int, qr["chunk_size"])),
    )
    updated = _upsert_table_key(
        updated,
        table="extension.chunking",
        key="target_size",
        value=str(cast(int, extension_chunking["target_size"])),
    )
    updated = _upsert_table_key(
        updated,
        table="extension.chunking",
        key="min_size",
        value=str(cast(int, extension_chunking["min_size"])),
    )
    updated = _upsert_table_key(
        updated,
        table="extension.chunking",
        key="max_size",
        value=str(cast(int, extension_chunking["max_size"])),
    )

    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="base_dir",
        value=_toml_quote(cast(str | None, backup["base_dir"]) or ""),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="output_dir",
        value=_toml_quote(cast(str | None, backup["output_dir"]) or ""),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="shard_threshold",
        value=str(cast(int | None, backup["shard_threshold"]) or 0),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="shard_count",
        value=str(cast(int | None, backup["shard_count"]) or 0),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="signing_key_mode",
        value=_toml_quote(cast(str | None, backup["signing_key_mode"]) or ""),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="signing_key_shard_threshold",
        value=str(cast(int | None, backup["signing_key_shard_threshold"]) or 0),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="signing_key_shard_count",
        value=str(cast(int | None, backup["signing_key_shard_count"]) or 0),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="payload_codec",
        value=_toml_quote(cast(str, backup["payload_codec"])),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.backup",
        key="qr_payload_codec",
        value=_toml_quote(cast(str, backup["qr_payload_codec"])),
    )

    updated = _upsert_table_key(
        updated,
        table="defaults.recover",
        key="output",
        value=_toml_quote(cast(str | None, recover["output"]) or ""),
    )

    updated = _upsert_table_key(
        updated,
        table="defaults.extend",
        key="base_dir",
        value=_toml_quote(cast(str | None, extend["base_dir"]) or ""),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.extend",
        key="unlock_policy",
        value=_toml_quote(cast(str | None, extend["unlock_policy"]) or ""),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.extend",
        key="shard_threshold",
        value=str(cast(int | None, extend["shard_threshold"]) or 0),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.extend",
        key="shard_count",
        value=str(cast(int | None, extend["shard_count"]) or 0),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.extend",
        key="signing_key_mode",
        value=_toml_quote(cast(str | None, extend["signing_key_mode"]) or ""),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.extend",
        key="signing_key_shard_threshold",
        value=str(cast(int | None, extend["signing_key_shard_threshold"]) or 0),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.extend",
        key="signing_key_shard_count",
        value=str(cast(int | None, extend["signing_key_shard_count"]) or 0),
    )
    updated = _upsert_table_key(
        updated,
        table="defaults.extend",
        key="qr_payload_codec",
        value=_toml_quote(cast(str, extend["qr_payload_codec"])),
    )

    updated = _upsert_table_key(
        updated,
        table="ui",
        key="quiet",
        value=_toml_bool(cast(bool, ui["quiet"])),
    )
    updated = _upsert_table_key(
        updated,
        table="ui",
        key="no_color",
        value=_toml_bool(cast(bool, ui["no_color"])),
    )
    updated = _upsert_table_key(
        updated,
        table="ui",
        key="no_animations",
        value=_toml_bool(cast(bool, ui["no_animations"])),
    )
    updated = _upsert_table_key(
        updated,
        table="ui",
        key="show_internals",
        value=_toml_bool(cast(bool, ui["show_internals"])),
    )

    updated = _upsert_table_key(
        updated,
        table="debug",
        key="max_bytes",
        value=str(cast(int | None, debug["max_bytes"]) or 0),
    )

    render_jobs = runtime["render_jobs"]
    updated = _upsert_table_key(
        updated,
        table="runtime",
        key="render_jobs",
        value=(
            _toml_quote(render_jobs)
            if isinstance(render_jobs, str)
            else str(render_jobs)
            if render_jobs is not None
            else _toml_quote("")
        ),
    )

    if not updated.endswith(("\n", "\r\n")):
        updated += line_ending
    return updated


def _table_header_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return None
    if stripped.startswith("[["):
        return None
    return stripped[1:-1].strip()


def _build_onboarding_patch_plan(
    onboarding: object,
    *,
    source: ConfigTargetSource,
) -> OnboardingPatchPlan | None:
    if onboarding is None:
        return None
    if source != "user":
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message="onboarding metadata can only be updated for the default user config",
            details={"field": "onboarding"},
        )
    if not isinstance(onboarding, dict):
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message="onboarding must be an object",
            details={"field": "onboarding"},
        )

    unknown_keys = sorted(set(onboarding) - _CONFIG_ONBOARDING_ALLOWED_KEYS)
    if unknown_keys:
        field = f"onboarding.{unknown_keys[0]}"
        raise ConfigPatchError(
            code="CONFIG_UNKNOWN_FIELD",
            message=f"unknown config field: {field}",
            details={"field": field},
        )

    mark_complete = onboarding.get("mark_complete")
    configured_fields = onboarding.get("configured_fields")
    normalized_fields: set[str] | None = None
    if configured_fields is not None:
        if not isinstance(configured_fields, list):
            raise ConfigPatchError(
                code="CONFIG_INVALID_VALUE",
                message="onboarding.configured_fields must be an array of strings",
                details={"field": "onboarding.configured_fields"},
            )
        normalized_fields = set()
        for value in configured_fields:
            if not isinstance(value, str) or not value.strip():
                raise ConfigPatchError(
                    code="CONFIG_INVALID_VALUE",
                    message="onboarding.configured_fields entries must be non-empty strings",
                    details={"field": "onboarding.configured_fields"},
                )
            normalized = value.strip()
            if normalized not in ONBOARDING_FIELDS:
                raise ConfigPatchError(
                    code="CONFIG_UNKNOWN_FIELD",
                    message=f"unknown onboarding field: {normalized}",
                    details={"field": "onboarding.configured_fields", "value": normalized},
                )
            normalized_fields.add(normalized)

    if mark_complete is None:
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message="onboarding.mark_complete is required when onboarding is provided",
            details={"field": "onboarding.mark_complete"},
        )
    if not isinstance(mark_complete, bool):
        raise ConfigPatchError(
            code="CONFIG_INVALID_VALUE",
            message="onboarding.mark_complete must be a boolean",
            details={"field": "onboarding.mark_complete"},
        )
    if not mark_complete and normalized_fields is not None:
        raise ConfigPatchError(
            code="CONFIG_CONFLICT",
            message="onboarding.configured_fields requires onboarding.mark_complete=true",
            details={"field": "onboarding.configured_fields"},
        )

    return OnboardingPatchPlan(
        mark_complete=mark_complete,
        configured_fields=frozenset()
        if normalized_fields is None
        else frozenset(normalized_fields),
    )


def _apply_onboarding_plan(plan: OnboardingPatchPlan) -> None:
    if plan.mark_complete:
        mark_first_run_onboarding_complete(configured_fields=set(plan.configured_fields))
        return
    clear_first_run_onboarding_marker()


def _read_marker_state() -> str | None:
    marker_path = first_run_onboarding_marker_path()
    if not marker_path.exists():
        return None
    return marker_path.read_text(encoding="utf-8")


def _restore_marker_state(marker_state: str | None) -> None:
    marker_path = first_run_onboarding_marker_path()
    if marker_state is None:
        clear_first_run_onboarding_marker()
        return
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(marker_path, marker_state)


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


__all__ = [
    "ApiConfigSnapshot",
    "ConfigPatchError",
    "get_api_config_snapshot",
    "apply_api_config_patch",
]
