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

from .installer import (
    DEFAULT_TEMPLATE_STYLE,
    ONBOARDING_FIELDS,
    _toml_quote,
    _upsert_table_key,
    _write_text_atomic,
    clear_first_run_onboarding_marker,
    first_run_onboarding_configured_fields,
    first_run_onboarding_needed,
    list_template_designs,
    mark_first_run_onboarding_complete,
    resolve_writable_config_path,
)
from .loader import _load_toml, load_app_config, load_cli_defaults

ConfigTargetSource = Literal["user", "explicit"]

_CONFIG_SET_ALLOWED_KEYS = frozenset({"values", "onboarding"})
_CONFIG_ONBOARDING_ALLOWED_KEYS = frozenset({"mark_complete", "configured_fields"})
_PAGE_SIZES = ("A4", "LETTER")
_QR_ERROR_LEVELS = ("L", "M", "Q", "H")
_PAYLOAD_CODECS = ("auto", "raw", "gzip")
_QR_PAYLOAD_CODECS = ("raw", "base64")
_SIGNING_KEY_MODES = ("embedded", "sharded")


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
    values: dict[str, object]
    options: dict[str, object]
    onboarding: dict[str, object]


def get_api_config_snapshot(path: str | Path | None = None) -> ApiConfigSnapshot:
    target_path, source = _resolve_config_target(path)
    return _snapshot_from_path(target_path, source=source)


def apply_api_config_patch(
    path: str | Path | None,
    patch: dict[str, object],
) -> ApiConfigSnapshot:
    target_path, source = _resolve_config_target(path)
    _validate_patch_shape(patch)

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
    original = target_path.read_text(encoding="utf-8")
    updated = _apply_values_to_text(original, validated_values)
    if updated != original:
        _write_text_atomic(target_path, updated)

    onboarding_patch = patch.get("onboarding")
    if onboarding_patch is not None:
        _apply_onboarding_patch(onboarding_patch, source=source)

    return _snapshot_from_path(target_path, source=source)


def _resolve_config_target(path: str | Path | None) -> tuple[Path, ConfigTargetSource]:
    source: ConfigTargetSource = "explicit" if path else "user"
    return resolve_writable_config_path(path), source


def _snapshot_from_path(path: Path, *, source: ConfigTargetSource) -> ApiConfigSnapshot:
    raw = _load_toml(path)
    config = load_app_config(path)
    cli_defaults = load_cli_defaults(path)
    values = {
        "templates": {
            "default_name": _raw_default_design(raw),
        },
        "page": {
            "size": config.paper_size,
        },
        "qr": {
            "error": config.qr_config.error,
            "chunk_size": config.qr_chunk_size,
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
            "recover": {
                "output": cli_defaults.recover.output,
            },
        },
        "ui": {
            "quiet": cli_defaults.ui.quiet,
            "no_color": cli_defaults.ui.no_color,
            "no_animations": cli_defaults.ui.no_animations,
        },
        "debug": {
            "max_bytes": cli_defaults.debug.max_bytes,
        },
        "runtime": {
            "render_jobs": cli_defaults.runtime.render_jobs,
        },
    }
    return ApiConfigSnapshot(
        path=str(path),
        source=source,
        values=cast(dict[str, object], values),
        options=_config_options(),
        onboarding={
            "needed": first_run_onboarding_needed(),
            "configured_fields": sorted(first_run_onboarding_configured_fields()),
            "available_fields": list(ONBOARDING_FIELDS),
        },
    )


def _raw_default_design(raw: dict[str, object]) -> str:
    templates = raw.get("templates")
    if isinstance(templates, dict):
        value = templates.get("default_name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_TEMPLATE_STYLE


def _config_options() -> dict[str, object]:
    return {
        "template_designs": sorted(list_template_designs().keys()),
        "page_sizes": list(_PAGE_SIZES),
        "qr_error_correction": list(_QR_ERROR_LEVELS),
        "payload_codecs": list(_PAYLOAD_CODECS),
        "qr_payload_codecs": list(_QR_PAYLOAD_CODECS),
        "signing_key_modes": list(_SIGNING_KEY_MODES),
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
    templates = _expect_section(values, "templates")
    page = _expect_section(values, "page")
    qr = _expect_section(values, "qr")
    defaults = _expect_section(values, "defaults")
    backup = _expect_section(defaults, "backup", prefix="defaults")
    recover = _expect_section(defaults, "recover", prefix="defaults")
    ui = _expect_section(values, "ui")
    debug = _expect_section(values, "debug")
    runtime = _expect_section(values, "runtime")

    template_design = _validate_design_name(
        templates.get("default_name"), field="values.templates.default_name"
    )
    page_size = _validate_enum(page.get("size"), field="values.page.size", allowed=_PAGE_SIZES)
    qr_error = _validate_enum(qr.get("error"), field="values.qr.error", allowed=_QR_ERROR_LEVELS)
    qr_chunk_size = _validate_positive_int(qr.get("chunk_size"), field="values.qr.chunk_size")

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

    render_jobs = _validate_render_jobs(
        runtime.get("render_jobs"), field="values.runtime.render_jobs"
    )
    debug_max_bytes = _validate_optional_positive_int(
        debug.get("max_bytes"),
        field="values.debug.max_bytes",
    )

    return {
        "templates": {
            "default_name": template_design,
        },
        "page": {
            "size": page_size,
        },
        "qr": {
            "error": qr_error,
            "chunk_size": qr_chunk_size,
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
        },
        "ui": {
            "quiet": _validate_bool(ui.get("quiet"), field="values.ui.quiet"),
            "no_color": _validate_bool(ui.get("no_color"), field="values.ui.no_color"),
            "no_animations": _validate_bool(
                ui.get("no_animations"),
                field="values.ui.no_animations",
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
    normalized = value.strip()
    if normalized not in list_template_designs():
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

    templates = cast(dict[str, object], values["templates"])
    page = cast(dict[str, object], values["page"])
    qr = cast(dict[str, object], values["qr"])
    defaults = cast(dict[str, object], values["defaults"])
    backup = cast(dict[str, object], defaults["backup"])
    recover = cast(dict[str, object], defaults["recover"])
    ui = cast(dict[str, object], values["ui"])
    debug = cast(dict[str, object], values["debug"])
    runtime = cast(dict[str, object], values["runtime"])

    design = cast(str, templates["default_name"])
    updated = _upsert_table_key(
        updated, table="templates", key="default_name", value=_toml_quote(design)
    )
    for section in (
        "template",
        "recovery_template",
        "shard_template",
        "signing_key_shard_template",
        "kit_template",
    ):
        updated = _upsert_table_key(updated, table=section, key="name", value=_toml_quote(design))

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


def _apply_onboarding_patch(onboarding: object, *, source: ConfigTargetSource) -> None:
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

    if mark_complete is None and normalized_fields is None:
        return
    if mark_complete is None:
        mark_complete = True
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

    if mark_complete:
        mark_first_run_onboarding_complete(configured_fields=normalized_fields)
        return
    clear_first_run_onboarding_marker()


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


__all__ = [
    "ApiConfigSnapshot",
    "ConfigPatchError",
    "get_api_config_snapshot",
    "apply_api_config_patch",
]
