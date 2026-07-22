"""Validate config API patches and normalize accepted values."""

from __future__ import annotations

from typing import cast

from ethernity.config.api.contracts import ConfigPatchError
from ethernity.config.install import list_render_styles
from ethernity.config.value_constraints import (
    EXTENSION_SIGNING_KEY_MODES as _EXTENSION_SIGNING_KEY_MODES,
    EXTENSION_UNLOCK_POLICIES as _EXTENSION_UNLOCK_POLICIES,
    PAGE_SIZES as _PAGE_SIZES,
    PAYLOAD_CODECS as _PAYLOAD_CODECS,
    QR_ERROR_LEVELS as _QR_ERROR_LEVELS,
    QR_PAYLOAD_CODECS as _QR_PAYLOAD_CODECS,
    SIGNING_KEY_MODES as _SIGNING_KEY_MODES,
)
from ethernity.core.bounds import MAX_DECOMPRESSED_PAYLOAD_BYTES
from ethernity.formats.extension_envelope import MIN_EXTENSION_CHUNK_SIZE

_CONFIG_SET_ALLOWED_KEYS = frozenset({"values", "onboarding"})


def validate_patch_shape(patch: dict[str, object]) -> None:
    unknown_keys = sorted(set(patch) - _CONFIG_SET_ALLOWED_KEYS)
    if unknown_keys:
        field = unknown_keys[0]
        raise ConfigPatchError(
            code="CONFIG_UNKNOWN_FIELD",
            message=f"unknown config patch field: {field}",
            details={"field": field},
        )


def merge_values_patch(
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
            merge_values_patch(cast(dict[str, object], existing), value, prefix=(*prefix, key))
            continue
        target[key] = value


def validate_config_values(values: dict[str, object]) -> dict[str, object]:
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
        "page": {"size": page_size},
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
        "debug": {"max_bytes": debug_max_bytes},
        "runtime": {"render_jobs": render_jobs},
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
    canonical = text.upper() if allowed in {_PAGE_SIZES, _QR_ERROR_LEVELS} else text.lower()
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


__all__ = ["merge_values_patch", "validate_config_values", "validate_patch_shape"]
