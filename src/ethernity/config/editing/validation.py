"""Validate config editing service patches and normalize accepted values."""

from __future__ import annotations

from ethernity.config.editing.models import ConfigPatchError
from ethernity.config.validation import CONFIG_VALUE_FIELDS, assess_config_values

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
        field = ".".join((*prefix, key))
        config_field = ".".join((*prefix[1:], key))
        is_section = any(path.startswith(f"{config_field}.") for path in CONFIG_VALUE_FIELDS)
        if config_field not in CONFIG_VALUE_FIELDS and not is_section:
            raise ConfigPatchError(
                code="CONFIG_UNKNOWN_FIELD",
                message=f"unknown config field: {field}",
                details={"field": field},
            )
        if is_section:
            if not isinstance(value, dict):
                raise ConfigPatchError(
                    code="CONFIG_INVALID_VALUE",
                    message=f"{field} must be an object",
                    details={"field": field},
                )
            existing = target.get(key)
            section = existing if isinstance(existing, dict) else {}
            merge_values_patch(section, value, prefix=(*prefix, key))
            target[key] = section
        else:
            target[key] = value


def validate_config_values(values: dict[str, object]) -> dict[str, object]:
    normalized, issues = assess_config_values(values)
    if issues:
        issue = issues[0]
        field = f"values.{issue.field}"
        raise ConfigPatchError(
            code="CONFIG_CONFLICT" if issue.conflict else "CONFIG_INVALID_VALUE",
            message=f"{field} {issue.message}",
            details={"field": field},
        )
    return normalized


__all__ = ["merge_values_patch", "validate_config_values", "validate_patch_shape"]
