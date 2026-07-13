"""Public data contracts for config snapshots and patches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

ConfigTargetSource: TypeAlias = Literal["default", "user", "explicit"]


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


__all__ = ["ApiConfigSnapshot", "ConfigPatchError", "ConfigTargetSource"]
