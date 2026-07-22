"""Orchestrate config snapshot reads and transactional patch writes."""

from __future__ import annotations

import copy
from pathlib import Path

from ethernity.config._toml_support import write_text_atomic
from ethernity.config.api.contracts import ApiConfigSnapshot, ConfigPatchError, ConfigTargetSource
from ethernity.config.api.onboarding import (
    apply_onboarding_plan,
    build_onboarding_patch_plan,
    read_marker_state,
    restore_marker_state,
)
from ethernity.config.api.snapshots import snapshot_from_path
from ethernity.config.api.toml_writer import update_config_toml
from ethernity.config.api.validation import (
    merge_values_patch,
    validate_config_values,
    validate_patch_shape,
)
from ethernity.config.install import resolve_config_snapshot_path, resolve_writable_config_path
from ethernity.config.paths import DEFAULT_CONFIG_PATH


def get_api_config_snapshot(path: str | Path | None = None) -> ApiConfigSnapshot:
    target_path, source = _resolve_config_target(path, for_write=False)
    return snapshot_from_path(target_path, source=source)


def apply_api_config_patch(
    path: str | Path | None,
    patch: dict[str, object],
) -> ApiConfigSnapshot:
    target_path, source = _resolve_config_target(path, for_write=True)
    validate_patch_shape(patch)
    onboarding_plan = build_onboarding_patch_plan(patch.get("onboarding"), source=source)

    original_text = target_path.read_text(encoding="utf-8") if target_path.exists() else None
    current = snapshot_from_path(target_path, source=source)
    current_values = copy.deepcopy(current.values)
    patch_values = patch.get("values")
    if patch_values is not None:
        if not isinstance(patch_values, dict):
            raise ConfigPatchError(
                code="CONFIG_INVALID_VALUE",
                message="values must be an object",
                details={"field": "values"},
            )
        merge_values_patch(current_values, patch_values, prefix=("values",))

    validated_values = validate_config_values(current_values)
    base_text = (
        original_text
        if original_text is not None and current.status != "invalid_toml"
        else DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    )
    updated = update_config_toml(base_text, validated_values)
    config_changed = original_text is None or updated != original_text
    marker_state = read_marker_state() if onboarding_plan is not None else None
    writable_target_path: Path | None = None
    created_config = False

    try:
        writable_target_path = target_path
        created_config = original_text is None and config_changed
        if config_changed:
            write_text_atomic(writable_target_path, updated)
        if onboarding_plan is not None:
            apply_onboarding_plan(onboarding_plan)
    except Exception:
        if onboarding_plan is not None:
            restore_marker_state(marker_state)
        if writable_target_path is not None:
            if created_config:
                writable_target_path.unlink(missing_ok=True)
            elif config_changed and original_text is not None:
                write_text_atomic(writable_target_path, original_text)
        raise

    return snapshot_from_path(writable_target_path or target_path, source=source)


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


__all__ = ["apply_api_config_patch", "get_api_config_snapshot"]
