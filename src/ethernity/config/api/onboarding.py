"""Validate and apply first-run onboarding marker updates."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.config._toml_support import write_text_atomic
from ethernity.config.api.contracts import ConfigPatchError, ConfigTargetSource
from ethernity.config.install import (
    ONBOARDING_FIELDS,
    clear_first_run_onboarding_marker,
    first_run_onboarding_marker_path,
    mark_first_run_onboarding_complete,
)

_CONFIG_ONBOARDING_ALLOWED_KEYS = frozenset({"mark_complete", "configured_fields"})


@dataclass(frozen=True)
class OnboardingPatchPlan:
    mark_complete: bool
    configured_fields: frozenset[str]


def build_onboarding_patch_plan(
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
        configured_fields=(
            frozenset() if normalized_fields is None else frozenset(normalized_fields)
        ),
    )


def apply_onboarding_plan(plan: OnboardingPatchPlan) -> None:
    if plan.mark_complete:
        mark_first_run_onboarding_complete(configured_fields=set(plan.configured_fields))
        return
    clear_first_run_onboarding_marker()


def read_marker_state() -> str | None:
    marker_path = first_run_onboarding_marker_path()
    if not marker_path.exists():
        return None
    return marker_path.read_text(encoding="utf-8")


def restore_marker_state(marker_state: str | None) -> None:
    marker_path = first_run_onboarding_marker_path()
    if marker_state is None:
        clear_first_run_onboarding_marker()
        return
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(marker_path, marker_state)


__all__ = [
    "OnboardingPatchPlan",
    "apply_onboarding_plan",
    "build_onboarding_patch_plan",
    "read_marker_state",
    "restore_marker_state",
]
