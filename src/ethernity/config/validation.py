"""Normalize configuration values and report constraints independently of their caller."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from ethernity.config.install import resolve_render_style_path
from ethernity.config.types import DEFAULT_EXTENSION_CHUNKING_PROFILE
from ethernity.config.value_constraints import (
    PAGE_SIZES,
    PAYLOAD_CODECS,
    QR_ERROR_LEVELS,
    QR_PAYLOAD_CODECS,
    SIGNING_KEY_MODES,
)
from ethernity.core import validation as value_validation
from ethernity.crypto.sharding import MAX_SHARES
from ethernity.formats.extension_constants import CHUNK_ALGORITHM_FASTCDC
from ethernity.formats.extension_document import ExtensionChunkingProfile


@dataclass(frozen=True)
class ConfigIssue:
    field: str
    reason: str
    message: str
    conflict: bool = False


class ConfigValueError(ValueError):
    def __init__(self, field: str, reason: str, message: str, *, conflict: bool = False):
        self.issue = ConfigIssue(field, reason, message, conflict)
        super().__init__(f"{field} {message}")


@dataclass(frozen=True)
class _ValueRule:
    kind: Literal["design", "enum", "int", "string", "bool"]
    choices: tuple[str, ...] = ()
    optional: bool = False
    maximum: int | None = None


# Only editable values belong here. TOML defaults and additional QR drawing parameters
# remain in the loader, while display labels and controls remain in the settings task.
_VALUE_RULES = {
    "render.style": _ValueRule("design"),
    "page.size": _ValueRule("enum", PAGE_SIZES),
    "qr.error": _ValueRule("enum", QR_ERROR_LEVELS),
    "qr.chunk_size": _ValueRule("int"),
    **{
        f"extension.chunking.{name}": _ValueRule("int")
        for name in ("target_size", "min_size", "max_size")
    },
    **{
        f"defaults.{group}.{name}": _ValueRule("string", optional=True)
        for group, name in (
            ("backup", "base_dir"),
            ("backup", "output_dir"),
            ("recover", "output"),
            ("add_files", "base_dir"),
        )
    },
    **{
        f"defaults.backup.{name}": _ValueRule("int", optional=True, maximum=MAX_SHARES)
        for name in (
            "shard_threshold",
            "shard_count",
            "signing_key_shard_threshold",
            "signing_key_shard_count",
        )
    },
    "defaults.backup.signing_key_mode": _ValueRule("enum", SIGNING_KEY_MODES, optional=True),
    "defaults.backup.payload_codec": _ValueRule("enum", PAYLOAD_CODECS),
    **{
        f"defaults.{group}.qr_payload_codec": _ValueRule("enum", QR_PAYLOAD_CODECS)
        for group in ("backup", "add_files")
    },
    **{
        f"ui.{name}": _ValueRule("bool")
        for name in ("quiet", "no_color", "no_animations", "show_internals")
    },
    "debug.max_bytes": _ValueRule("int", optional=True),
}


CONFIG_VALUE_FIELDS = frozenset(_VALUE_RULES)


def require_int(value: object, *, field: str) -> int:
    try:
        return value_validation.require_int(value, label=field)
    except ValueError as exc:
        raise ConfigValueError(field, "integer", "must be an integer") from exc


def require_bool(value: object, *, field: str) -> bool:
    try:
        return value_validation.require_bool(value, label=field)
    except ValueError as exc:
        raise ConfigValueError(field, "boolean", "must be a boolean") from exc


def normalize_choice(
    value: object, *, field: str, choices: tuple[str, ...], optional: bool = False
) -> str | None:
    if optional and (value is None or isinstance(value, str) and not value.strip()):
        return None
    if choices == QR_PAYLOAD_CODECS:
        message = "must be 'raw' or 'base64'"
        if value is None:
            message = f"is required and {message}"
    elif choices == PAYLOAD_CODECS:
        message = "must be 'auto', 'raw', or 'gzip'"
    elif choices == SIGNING_KEY_MODES:
        message = "must be 'embedded', 'sharded', or empty"
    else:
        message = f"must be one of: {', '.join(choices)}"
    if not isinstance(value, str):
        raise ConfigValueError(field, "choice", message)
    text = value.strip()
    normalized = text.upper() if choices in (PAGE_SIZES, QR_ERROR_LEVELS) else text.lower()
    if normalized not in choices:
        raise ConfigValueError(field, "choice", message)
    return normalized


def normalize_value(field: str, value: object) -> object:
    """Normalize one editable value, without applying missing-file defaults."""
    rule = _VALUE_RULES[field]
    if rule.kind == "enum":
        return normalize_choice(value, field=field, choices=rule.choices, optional=rule.optional)
    if rule.optional and value is None:
        return None
    if rule.kind == "int":
        return _normalize_integer(value, field=field, rule=rule)
    if rule.kind == "bool":
        return require_bool(value, field=field)
    if not isinstance(value, str):
        message = "must be a non-empty string" if rule.kind == "design" else "must be a string"
        raise ConfigValueError(field, "string", message)
    normalized = value.strip()
    if rule.kind == "design":
        if not normalized:
            raise ConfigValueError(field, "choice", "must be a non-empty string")
        try:
            resolve_render_style_path(normalized)
        except ValueError as exc:
            raise ConfigValueError(field, "choice", str(exc)) from exc
        return normalized.lower()
    return normalized or None


def _normalize_integer(value: object, *, field: str, rule: _ValueRule) -> int | None:
    parsed = require_int(value, field=field)
    if rule.optional and parsed == 0:
        return None
    try:
        value_validation.require_positive_int(parsed, label=field)
    except ValueError as exc:
        raise ConfigValueError(field, "positive", "must be a positive integer") from exc
    if rule.maximum is not None and parsed > rule.maximum:
        raise ConfigValueError(field, "maximum", f"must be <= {rule.maximum}")
    return parsed


def backup_default_issues(values: Mapping[str, object]) -> tuple[ConfigIssue, ...]:
    """Validate recovery quorums and signing-key dependencies after scalar normalization."""
    issues: list[ConfigIssue] = []
    for prefix in ("", "signing_key_"):
        threshold, count = (
            values.get(f"{prefix}shard_threshold"),
            values.get(f"{prefix}shard_count"),
        )
        if not all(
            value is None or type(value) is int and value > 0 for value in (threshold, count)
        ):
            continue
        field = f"defaults.backup.{prefix}shard_threshold"
        if (threshold is None) != (count is None):
            issues.append(
                ConfigIssue(
                    field, "paired_count", "and the created sheet count must be set together", True
                )
            )
        elif (
            threshold is not None and count is not None and cast(int, count) < cast(int, threshold)
        ):
            issues.append(
                ConfigIssue(
                    f"defaults.backup.{prefix}shard_count",
                    "count_below_threshold",
                    "must be at least the required sheet count",
                    True,
                )
            )
    mode = values.get("signing_key_mode")
    if mode == "sharded" and (
        values.get("shard_threshold") is None or values.get("shard_count") is None
    ):
        issues.append(
            ConfigIssue(
                "defaults.backup.signing_key_mode",
                "signing_key_dependency",
                "requires passphrase recovery sheets",
                True,
            )
        )
    if mode != "sharded" and any(
        values.get(f"signing_key_shard_{name}") is not None for name in ("threshold", "count")
    ):
        issues.append(
            ConfigIssue(
                "defaults.backup.signing_key_mode",
                "signing_key_dependency",
                "must be sharded when signing-key sheet counts are set",
                True,
            )
        )
    return tuple(issues)


def build_chunking_profile(values: dict[str, object]) -> ExtensionChunkingProfile:
    """Apply default sizes and the format's existing chunking constraints."""
    defaults = DEFAULT_EXTENSION_CHUNKING_PROFILE
    sizes = {
        name: cast(
            int,
            normalize_value(
                f"extension.chunking.{name}", values.get(name, getattr(defaults, name))
            ),
        )
        for name in ("target_size", "min_size", "max_size")
    }
    try:
        return ExtensionChunkingProfile(algorithm_id=CHUNK_ALGORITHM_FASTCDC, **sizes)
    except ValueError as exc:
        raise ConfigValueError("extension.chunking", "chunking", str(exc)) from exc


def assess_config_values(
    values: dict[str, object],
) -> tuple[dict[str, object], tuple[ConfigIssue, ...]]:
    """Collect all editable-setting errors without modifying the supplied values."""
    normalized: dict[str, object] = {}
    issues: list[ConfigIssue] = []
    invalid_sections: set[str] = set()
    for field in _VALUE_RULES:
        parts = field.split(".")
        source, target = values, normalized
        for index, key in enumerate(parts[:-1], start=1):
            section = source.get(key)
            if not isinstance(section, dict):
                section_field = ".".join(parts[:index])
                if section_field not in invalid_sections:
                    issues.append(ConfigIssue(section_field, "section", "must be an object"))
                    invalid_sections.add(section_field)
                break
            source = section
            target = cast(dict[str, object], target.setdefault(key, {}))
        else:
            value = source.get(parts[-1])
            try:
                value = normalize_value(field, value)
            except ConfigValueError as exc:
                issues.append(exc.issue)
            target[parts[-1]] = value

    backup = cast(
        dict[str, object], cast(dict[str, object], normalized.get("defaults", {})).get("backup", {})
    )
    issues.extend(backup_default_issues(backup))
    if not any(issue.field.startswith("extension") for issue in issues):
        chunking = cast(
            dict[str, object], cast(dict[str, object], normalized["extension"])["chunking"]
        )
        try:
            build_chunking_profile(chunking)
        except ConfigValueError as exc:
            issues.append(exc.issue)
    return normalized, tuple(issues)


__all__ = [
    "CONFIG_VALUE_FIELDS",
    "ConfigIssue",
    "ConfigValueError",
    "assess_config_values",
    "backup_default_issues",
    "build_chunking_profile",
    "normalize_choice",
    "normalize_value",
    "require_bool",
    "require_int",
]
