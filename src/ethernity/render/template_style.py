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

"""Load and validate the live per-design capabilities from ``style.json``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ethernity.render.designs import resolve_design_directory

_STYLE_CONTEXT_PATH = "path"
_STYLE_TOP_LEVEL_KEYS = frozenset({"name", "capabilities"})
_BOOL_CAPABILITY_FIELDS = (
    "recovery_first_page_single_section",
    "recovery_kit_index_document",
)
_CAPABILITY_KEYS = frozenset({*_BOOL_CAPABILITY_FIELDS, "main_qr_grid_size_mm"})


@dataclass(frozen=True)
class TemplateCapabilities:
    """Design-specific behavior still consumed by the active render pipeline."""

    recovery_first_page_single_section: bool = False
    recovery_kit_index_document: bool = False
    main_qr_grid_size_mm: float | None = None


@dataclass(frozen=True)
class TemplateStyle:
    """Validated style metadata for one render design."""

    name: str
    capabilities: TemplateCapabilities


class _TemplateCapabilitiesData(BaseModel):
    """Pydantic boundary model for the optional ``capabilities`` object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recovery_first_page_single_section: bool = False
    recovery_kit_index_document: bool = False
    main_qr_grid_size_mm: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_object(cls, value: object, info: ValidationInfo) -> object:
        path = _context_path(info)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError(f"invalid 'capabilities' object in {path}")
        _reject_unknown_keys(
            value,
            allowed_keys=_CAPABILITY_KEYS,
            section="capabilities",
            path=path,
        )
        return value

    @field_validator(*_BOOL_CAPABILITY_FIELDS, mode="before")
    @classmethod
    def _validate_bool(cls, value: object, info: ValidationInfo) -> bool:
        if isinstance(value, bool):
            return value
        raise ValueError(f"missing or invalid '{info.field_name}' boolean in {_context_path(info)}")

    @field_validator("main_qr_grid_size_mm", mode="before")
    @classmethod
    def _validate_optional_positive_number(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> float | None:
        if value is None:
            return None
        return _require_positive_number_value(
            value,
            key=info.field_name,
            path=_context_path(info),
        )

    def to_public(self) -> TemplateCapabilities:
        return TemplateCapabilities(
            recovery_first_page_single_section=self.recovery_first_page_single_section,
            recovery_kit_index_document=self.recovery_kit_index_document,
            main_qr_grid_size_mm=self.main_qr_grid_size_mm,
        )


class _TemplateStyleData(BaseModel):
    """Pydantic boundary model for raw ``style.json`` content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    capabilities: _TemplateCapabilitiesData = Field(default_factory=_TemplateCapabilitiesData)

    @model_validator(mode="before")
    @classmethod
    def _validate_object(cls, value: object, info: ValidationInfo) -> object:
        path = _context_path(info)
        if not isinstance(value, dict):
            raise ValueError(f"template style must be a JSON object: {path}")
        _reject_unknown_keys(
            value,
            allowed_keys=_STYLE_TOP_LEVEL_KEYS,
            section="template style",
            path=path,
        )
        return value

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: object, info: ValidationInfo) -> str:
        if isinstance(value, str) and value.strip():
            return value
        raise ValueError(f"missing or invalid 'name' string in {_context_path(info)}")

    @field_validator("capabilities", mode="before")
    @classmethod
    def _validate_capabilities(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError(f"invalid 'capabilities' object in {_context_path(info)}")
        return value

    def to_public(self) -> TemplateStyle:
        return TemplateStyle(name=self.name, capabilities=self.capabilities.to_public())


def load_template_style(design: str | Path) -> TemplateStyle:
    """Load the style for a render design name, directory, or manifest path."""

    template_dir = resolve_design_directory(design)
    return _load_style_for_dir(template_dir)


@lru_cache(maxsize=32)
def _load_style_for_dir(template_dir: Path) -> TemplateStyle:
    """Load and validate ``style.json`` for a template directory."""

    style_path = template_dir / "style.json"
    if not style_path.is_file():
        raise ValueError(f"missing template style file: {style_path}")

    try:
        raw = style_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read template style file: {style_path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in template style file: {style_path}") from exc

    return _load_style_data(data, path=style_path).to_public()


def _load_style_data(data: object, *, path: Path) -> _TemplateStyleData:
    if not isinstance(data, dict):
        raise ValueError(f"template style must be a JSON object: {path}")
    try:
        return _TemplateStyleData.model_validate(data, context={_STYLE_CONTEXT_PATH: path})
    except ValidationError as exc:
        raise ValueError(_style_validation_message(exc, path=path)) from exc


def _context_path(info: ValidationInfo) -> Path:
    context = info.context
    if isinstance(context, dict):
        value = context.get(_STYLE_CONTEXT_PATH)
        if isinstance(value, Path):
            return value
    return Path("style.json")


def _style_validation_message(exc: ValidationError, *, path: Path) -> str:
    error = exc.errors()[0]
    context_error = error.get("ctx", {}).get("error")
    if isinstance(context_error, ValueError):
        return str(context_error)

    loc = tuple(error.get("loc", ()))
    field = str(loc[-1]) if loc else "template style"
    if field == "main_qr_grid_size_mm":
        return f"missing or invalid '{field}' positive number in {path}"
    if field == "name":
        return f"missing or invalid 'name' string in {path}"
    if field == "capabilities":
        return f"invalid 'capabilities' object in {path}"
    return f"invalid template style in {path}"


def _require_positive_number_value(value: object, *, key: str | None, path: Path) -> float:
    if key is None:
        key = "number"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"missing or invalid '{key}' positive number in {path}")
    return float(value)


def _reject_unknown_keys(
    data: dict[str, object],
    *,
    allowed_keys: frozenset[str],
    section: str,
    path: Path,
) -> None:
    """Reject unknown keys in a style section."""

    unknown = sorted(key for key in data if key not in allowed_keys)
    if unknown:
        unknown_text = ", ".join(unknown)
        raise ValueError(f"unknown key(s) in {section} ({unknown_text}) in {path}")


__all__ = ["TemplateCapabilities", "TemplateStyle", "load_template_style"]
