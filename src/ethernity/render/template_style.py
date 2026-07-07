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

"""Load and validate per-design render style metadata from `style.json`."""

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
from ethernity.render.doc_types import DOC_TYPES

_STYLE_CONTEXT_PATH = "path"
_STYLE_TOP_LEVEL_KEYS = frozenset({"name", "header", "content_offset", "capabilities"})
_HEADER_KEYS = frozenset({"meta_row_gap_mm", "stack_gap_mm", "divider_thickness_mm"})
_CONTENT_OFFSET_KEYS = frozenset({"divider_gap_extra_mm", "doc_types"})
_FALLBACK_LAYOUT_KEYS = frozenset({"recovery", "shard", "signing_key_shard"})
_RECOVERY_FALLBACK_LAYOUT_KEYS = frozenset(
    {
        "line_height_floor_mm",
        "first_page_footer_reserve_mm",
        "continuation_footer_reserve_mm",
        "meta_baseline_lines",
        "meta_extra_line_mm",
        "meta_section_overhead_mm",
        "first_page_text_width_bonus_mm",
        "continuation_text_width_bonus_mm",
    }
)
_SHARD_FALLBACK_LAYOUT_KEYS = frozenset(
    {
        "line_height_floor_mm",
        "first_page_payload_zone_height_mm",
        "continuation_payload_zone_height_mm",
    }
)
_BOOL_CAPABILITY_FIELDS = (
    "inject_forge_copy",
    "recovery_first_page_single_section",
    "repeat_primary_qr_on_shard_continuation",
    "advanced_fallback_layout",
    "extra_main_first_page_qr_slot",
    "uniform_main_qr_capacity",
    "repeat_main_instructions_on_all_pages",
    "recovery_kit_index_document",
)
_OPTIONAL_POSITIVE_NUMBER_CAPABILITY_FIELDS = ("main_qr_grid_size_mm",)
_OPTIONAL_POSITIVE_INT_CAPABILITY_FIELDS = ("main_qr_grid_max_cols",)
_NON_NEGATIVE_INT_CAPABILITY_FIELDS = (
    "recovery_line_groups_bonus",
    "recovery_first_page_bonus_lines",
    "recovery_first_page_bonus_lines_per_extra_section",
    "recovery_continuation_bonus_lines",
    "recovery_main_section_start_reserved_lines",
    "recovery_quorumless_line_groups_bonus",
    "recovery_quorumless_first_page_bonus_lines",
    "recovery_quorumless_continuation_bonus_lines",
    "shard_line_groups_bonus",
    "shard_first_page_estimate_bonus_lines",
    "shard_first_page_bonus_lines",
    "signing_key_shard_line_groups_bonus",
    "signing_key_shard_first_page_estimate_bonus_lines",
    "signing_key_shard_first_page_bonus_lines",
)
_CAPABILITY_KEYS = frozenset(
    {
        *_BOOL_CAPABILITY_FIELDS,
        *_OPTIONAL_POSITIVE_NUMBER_CAPABILITY_FIELDS,
        *_OPTIONAL_POSITIVE_INT_CAPABILITY_FIELDS,
        "fallback_layout",
        *_NON_NEGATIVE_INT_CAPABILITY_FIELDS,
    }
)
_NUMBER_FIELDS = frozenset(
    {
        "meta_row_gap_mm",
        "stack_gap_mm",
        "divider_thickness_mm",
        "divider_gap_extra_mm",
        "first_page_text_width_bonus_mm",
        "continuation_text_width_bonus_mm",
    }
)
_POSITIVE_NUMBER_FIELDS = frozenset({"line_height_floor_mm", "main_qr_grid_size_mm"})
_NON_NEGATIVE_NUMBER_FIELDS = frozenset(
    {
        "first_page_footer_reserve_mm",
        "continuation_footer_reserve_mm",
        "meta_extra_line_mm",
        "meta_section_overhead_mm",
        "first_page_payload_zone_height_mm",
        "continuation_payload_zone_height_mm",
    }
)
_NON_NEGATIVE_INT_FIELDS = frozenset({"meta_baseline_lines", *_NON_NEGATIVE_INT_CAPABILITY_FIELDS})
_POSITIVE_INT_FIELDS = frozenset(_OPTIONAL_POSITIVE_INT_CAPABILITY_FIELDS)


@dataclass(frozen=True)
class HeaderStyle:
    """Header spacing/thickness overrides loaded from template style."""

    meta_row_gap_mm: float
    stack_gap_mm: float
    divider_thickness_mm: float


@dataclass(frozen=True)
class ContentOffsetStyle:
    """Content offset overrides scoped to document types."""

    divider_gap_extra_mm: float
    doc_types: frozenset[str]


@dataclass(frozen=True)
class RecoveryFallbackLayout:
    line_height_floor_mm: float
    first_page_footer_reserve_mm: float
    continuation_footer_reserve_mm: float
    meta_baseline_lines: int
    meta_extra_line_mm: float
    meta_section_overhead_mm: float
    first_page_text_width_bonus_mm: float
    continuation_text_width_bonus_mm: float


@dataclass(frozen=True)
class ShardFallbackLayout:
    line_height_floor_mm: float
    first_page_payload_zone_height_mm: float
    continuation_payload_zone_height_mm: float


@dataclass(frozen=True)
class FallbackLayoutProfile:
    recovery: RecoveryFallbackLayout
    shard: ShardFallbackLayout
    signing_key_shard: ShardFallbackLayout


@dataclass(frozen=True)
class TemplateCapabilities:
    """Boolean and numeric feature toggles for template behavior."""

    inject_forge_copy: bool = False
    recovery_first_page_single_section: bool = False
    repeat_primary_qr_on_shard_continuation: bool = False
    advanced_fallback_layout: bool = False
    extra_main_first_page_qr_slot: bool = False
    uniform_main_qr_capacity: bool = False
    repeat_main_instructions_on_all_pages: bool = False
    recovery_kit_index_document: bool = False
    main_qr_grid_size_mm: float | None = None
    main_qr_grid_max_cols: int | None = None
    fallback_layout: FallbackLayoutProfile | None = None
    recovery_line_groups_bonus: int = 0
    recovery_first_page_bonus_lines: int = 0
    recovery_first_page_bonus_lines_per_extra_section: int = 0
    recovery_continuation_bonus_lines: int = 0
    recovery_main_section_start_reserved_lines: int = 0
    recovery_quorumless_line_groups_bonus: int = 0
    recovery_quorumless_first_page_bonus_lines: int = 0
    recovery_quorumless_continuation_bonus_lines: int = 0
    shard_line_groups_bonus: int = 0
    shard_first_page_estimate_bonus_lines: int = 0
    shard_first_page_bonus_lines: int = 0
    signing_key_shard_line_groups_bonus: int = 0
    signing_key_shard_first_page_estimate_bonus_lines: int = 0
    signing_key_shard_first_page_bonus_lines: int = 0


@dataclass(frozen=True)
class TemplateStyle:
    """Parsed template style bundle for a design directory."""

    name: str
    header: HeaderStyle
    content_offset: ContentOffsetStyle
    capabilities: TemplateCapabilities


class _HeaderStyleData(BaseModel):
    """Pydantic boundary model for the `header` style section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meta_row_gap_mm: float
    stack_gap_mm: float
    divider_thickness_mm: float

    @model_validator(mode="before")
    @classmethod
    def _validate_object(cls, value: object, info: ValidationInfo) -> object:
        path = _context_path(info)
        if not isinstance(value, dict):
            raise ValueError(f"missing or invalid 'header' object in {path}")
        _reject_unknown_keys(value, allowed_keys=_HEADER_KEYS, section="header", path=path)
        return value

    @field_validator("meta_row_gap_mm", "stack_gap_mm", "divider_thickness_mm", mode="before")
    @classmethod
    def _validate_number(cls, value: object, info: ValidationInfo) -> float:
        return _require_number_value(value, key=info.field_name, path=_context_path(info))

    def to_public(self) -> HeaderStyle:
        return HeaderStyle(
            meta_row_gap_mm=self.meta_row_gap_mm,
            stack_gap_mm=self.stack_gap_mm,
            divider_thickness_mm=self.divider_thickness_mm,
        )


class _ContentOffsetStyleData(BaseModel):
    """Pydantic boundary model for the `content_offset` style section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    divider_gap_extra_mm: float
    doc_types: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _validate_object(cls, value: object, info: ValidationInfo) -> object:
        path = _context_path(info)
        if not isinstance(value, dict):
            raise ValueError(f"missing or invalid 'content_offset' object in {path}")
        _reject_unknown_keys(
            value,
            allowed_keys=_CONTENT_OFFSET_KEYS,
            section="content_offset",
            path=path,
        )
        return value

    @field_validator("divider_gap_extra_mm", mode="before")
    @classmethod
    def _validate_number(cls, value: object, info: ValidationInfo) -> float:
        return _require_number_value(value, key=info.field_name, path=_context_path(info))

    @field_validator("doc_types", mode="before")
    @classmethod
    def _validate_doc_type_list(cls, value: object, info: ValidationInfo) -> tuple[str, ...]:
        path = _context_path(info)
        if value is None:
            return ()
        if not isinstance(value, list):
            raise ValueError(f"'doc_types' must be a list in {path}")
        entries: list[str] = []
        for index, entry in enumerate(value):
            if not isinstance(entry, str):
                raise ValueError(f"'doc_types[{index}]' must be a string in {path}")
            entries.append(entry)
        return tuple(entries)

    @field_validator("doc_types")
    @classmethod
    def _normalize_doc_types(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        path = _context_path(info)
        normalized_doc_types: list[str] = []
        for doc_type in value:
            normalized = doc_type.strip().lower()
            if normalized not in DOC_TYPES:
                raise ValueError(f"unknown doc type '{doc_type}' in {path}")
            normalized_doc_types.append(normalized)
        return tuple(normalized_doc_types)

    def to_public(self) -> ContentOffsetStyle:
        return ContentOffsetStyle(
            divider_gap_extra_mm=self.divider_gap_extra_mm,
            doc_types=frozenset(self.doc_types),
        )


class _RecoveryFallbackLayoutData(BaseModel):
    """Pydantic boundary model for recovery fallback layout tuning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    line_height_floor_mm: float
    first_page_footer_reserve_mm: float
    continuation_footer_reserve_mm: float
    meta_baseline_lines: int
    meta_extra_line_mm: float
    meta_section_overhead_mm: float
    first_page_text_width_bonus_mm: float
    continuation_text_width_bonus_mm: float

    @model_validator(mode="before")
    @classmethod
    def _validate_object(cls, value: object, info: ValidationInfo) -> object:
        path = _context_path(info)
        if not isinstance(value, dict):
            raise ValueError(f"missing or invalid 'recovery' object in {path}")
        _reject_unknown_keys(
            value,
            allowed_keys=_RECOVERY_FALLBACK_LAYOUT_KEYS,
            section="fallback_layout.recovery",
            path=path,
        )
        return value

    @field_validator("line_height_floor_mm", mode="before")
    @classmethod
    def _validate_positive_number(cls, value: object, info: ValidationInfo) -> float:
        return _require_positive_number_value(value, key=info.field_name, path=_context_path(info))

    @field_validator(
        "first_page_footer_reserve_mm",
        "continuation_footer_reserve_mm",
        "meta_extra_line_mm",
        "meta_section_overhead_mm",
        mode="before",
    )
    @classmethod
    def _validate_non_negative_number(cls, value: object, info: ValidationInfo) -> float:
        return _require_non_negative_number_value(
            value,
            key=info.field_name,
            path=_context_path(info),
        )

    @field_validator("meta_baseline_lines", mode="before")
    @classmethod
    def _validate_non_negative_int(cls, value: object, info: ValidationInfo) -> int:
        return _require_non_negative_int_value(value, key=info.field_name, path=_context_path(info))

    @field_validator(
        "first_page_text_width_bonus_mm",
        "continuation_text_width_bonus_mm",
        mode="before",
    )
    @classmethod
    def _validate_number(cls, value: object, info: ValidationInfo) -> float:
        return _require_number_value(value, key=info.field_name, path=_context_path(info))

    def to_public(self) -> RecoveryFallbackLayout:
        return RecoveryFallbackLayout(
            line_height_floor_mm=self.line_height_floor_mm,
            first_page_footer_reserve_mm=self.first_page_footer_reserve_mm,
            continuation_footer_reserve_mm=self.continuation_footer_reserve_mm,
            meta_baseline_lines=self.meta_baseline_lines,
            meta_extra_line_mm=self.meta_extra_line_mm,
            meta_section_overhead_mm=self.meta_section_overhead_mm,
            first_page_text_width_bonus_mm=self.first_page_text_width_bonus_mm,
            continuation_text_width_bonus_mm=self.continuation_text_width_bonus_mm,
        )


class _ShardFallbackLayoutData(BaseModel):
    """Pydantic boundary model for shard fallback layout tuning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    line_height_floor_mm: float
    first_page_payload_zone_height_mm: float
    continuation_payload_zone_height_mm: float

    @model_validator(mode="before")
    @classmethod
    def _validate_object(cls, value: object, info: ValidationInfo) -> object:
        path = _context_path(info)
        if not isinstance(value, dict):
            raise ValueError("missing or invalid shard fallback layout object")
        _reject_unknown_keys(
            value,
            allowed_keys=_SHARD_FALLBACK_LAYOUT_KEYS,
            section="fallback_layout shard profile",
            path=path,
        )
        return value

    @field_validator("line_height_floor_mm", mode="before")
    @classmethod
    def _validate_positive_number(cls, value: object, info: ValidationInfo) -> float:
        return _require_positive_number_value(value, key=info.field_name, path=_context_path(info))

    @field_validator(
        "first_page_payload_zone_height_mm",
        "continuation_payload_zone_height_mm",
        mode="before",
    )
    @classmethod
    def _validate_non_negative_number(cls, value: object, info: ValidationInfo) -> float:
        return _require_non_negative_number_value(
            value,
            key=info.field_name,
            path=_context_path(info),
        )

    def to_public(self) -> ShardFallbackLayout:
        return ShardFallbackLayout(
            line_height_floor_mm=self.line_height_floor_mm,
            first_page_payload_zone_height_mm=self.first_page_payload_zone_height_mm,
            continuation_payload_zone_height_mm=self.continuation_payload_zone_height_mm,
        )


class _FallbackLayoutProfileData(BaseModel):
    """Pydantic boundary model for `capabilities.fallback_layout`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recovery: _RecoveryFallbackLayoutData
    shard: _ShardFallbackLayoutData
    signing_key_shard: _ShardFallbackLayoutData

    @model_validator(mode="before")
    @classmethod
    def _validate_object(cls, value: object, info: ValidationInfo) -> object:
        path = _context_path(info)
        if not isinstance(value, dict):
            raise ValueError(f"missing or invalid 'fallback_layout' object in {path}")
        _reject_unknown_keys(
            value,
            allowed_keys=_FALLBACK_LAYOUT_KEYS,
            section="fallback_layout",
            path=path,
        )
        return value

    def to_public(self) -> FallbackLayoutProfile:
        return FallbackLayoutProfile(
            recovery=self.recovery.to_public(),
            shard=self.shard.to_public(),
            signing_key_shard=self.signing_key_shard.to_public(),
        )


class _TemplateCapabilitiesData(BaseModel):
    """Pydantic boundary model for the optional `capabilities` style section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inject_forge_copy: bool = False
    recovery_first_page_single_section: bool = False
    repeat_primary_qr_on_shard_continuation: bool = False
    advanced_fallback_layout: bool = False
    extra_main_first_page_qr_slot: bool = False
    uniform_main_qr_capacity: bool = False
    repeat_main_instructions_on_all_pages: bool = False
    recovery_kit_index_document: bool = False
    main_qr_grid_size_mm: float | None = None
    main_qr_grid_max_cols: int | None = None
    fallback_layout: _FallbackLayoutProfileData | None = None
    recovery_line_groups_bonus: int = 0
    recovery_first_page_bonus_lines: int = 0
    recovery_first_page_bonus_lines_per_extra_section: int = 0
    recovery_continuation_bonus_lines: int = 0
    recovery_main_section_start_reserved_lines: int = 0
    recovery_quorumless_line_groups_bonus: int = 0
    recovery_quorumless_first_page_bonus_lines: int = 0
    recovery_quorumless_continuation_bonus_lines: int = 0
    shard_line_groups_bonus: int = 0
    shard_first_page_estimate_bonus_lines: int = 0
    shard_first_page_bonus_lines: int = 0
    signing_key_shard_line_groups_bonus: int = 0
    signing_key_shard_first_page_estimate_bonus_lines: int = 0
    signing_key_shard_first_page_bonus_lines: int = 0

    @model_validator(mode="before")
    @classmethod
    def _validate_object(cls, value: object, info: ValidationInfo) -> object:
        path = _context_path(info)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError(f"invalid 'capabilities' object in {path}")
        _reject_legacy_capability_keys(value, path=path)
        _reject_unknown_keys(
            value, allowed_keys=_CAPABILITY_KEYS, section="capabilities", path=path
        )
        return value

    @field_validator(*_BOOL_CAPABILITY_FIELDS, mode="before")
    @classmethod
    def _validate_bool(cls, value: object, info: ValidationInfo) -> bool:
        if isinstance(value, bool):
            return value
        raise ValueError(f"missing or invalid '{info.field_name}' boolean in {_context_path(info)}")

    @field_validator(*_OPTIONAL_POSITIVE_NUMBER_CAPABILITY_FIELDS, mode="before")
    @classmethod
    def _validate_optional_positive_number(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> float | None:
        if value is None:
            return None
        return _require_positive_number_value(value, key=info.field_name, path=_context_path(info))

    @field_validator(*_OPTIONAL_POSITIVE_INT_CAPABILITY_FIELDS, mode="before")
    @classmethod
    def _validate_optional_positive_int(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> int | None:
        if value is None:
            return None
        return _require_positive_int_value(value, key=info.field_name, path=_context_path(info))

    @field_validator(*_NON_NEGATIVE_INT_CAPABILITY_FIELDS, mode="before")
    @classmethod
    def _validate_non_negative_int(cls, value: object, info: ValidationInfo) -> int:
        return _require_non_negative_int_value(value, key=info.field_name, path=_context_path(info))

    @field_validator("fallback_layout", mode="before")
    @classmethod
    def _validate_fallback_layout(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError(
                f"missing or invalid 'fallback_layout' object in {_context_path(info)}"
            )
        return value

    @model_validator(mode="after")
    def _validate_advanced_layout(self, info: ValidationInfo) -> _TemplateCapabilitiesData:
        if self.advanced_fallback_layout and self.fallback_layout is None:
            raise ValueError(
                "missing required 'fallback_layout' object when "
                "'advanced_fallback_layout' is enabled in "
                f"{_context_path(info)}"
            )
        return self

    def to_public(self) -> TemplateCapabilities:
        fallback_layout = (
            self.fallback_layout.to_public() if self.fallback_layout is not None else None
        )
        return TemplateCapabilities(
            inject_forge_copy=self.inject_forge_copy,
            recovery_first_page_single_section=self.recovery_first_page_single_section,
            repeat_primary_qr_on_shard_continuation=(self.repeat_primary_qr_on_shard_continuation),
            advanced_fallback_layout=self.advanced_fallback_layout,
            extra_main_first_page_qr_slot=self.extra_main_first_page_qr_slot,
            uniform_main_qr_capacity=self.uniform_main_qr_capacity,
            repeat_main_instructions_on_all_pages=self.repeat_main_instructions_on_all_pages,
            recovery_kit_index_document=self.recovery_kit_index_document,
            main_qr_grid_size_mm=self.main_qr_grid_size_mm,
            main_qr_grid_max_cols=self.main_qr_grid_max_cols,
            fallback_layout=fallback_layout,
            recovery_line_groups_bonus=self.recovery_line_groups_bonus,
            recovery_first_page_bonus_lines=self.recovery_first_page_bonus_lines,
            recovery_first_page_bonus_lines_per_extra_section=(
                self.recovery_first_page_bonus_lines_per_extra_section
            ),
            recovery_continuation_bonus_lines=self.recovery_continuation_bonus_lines,
            recovery_main_section_start_reserved_lines=(
                self.recovery_main_section_start_reserved_lines
            ),
            recovery_quorumless_line_groups_bonus=self.recovery_quorumless_line_groups_bonus,
            recovery_quorumless_first_page_bonus_lines=(
                self.recovery_quorumless_first_page_bonus_lines
            ),
            recovery_quorumless_continuation_bonus_lines=(
                self.recovery_quorumless_continuation_bonus_lines
            ),
            shard_line_groups_bonus=self.shard_line_groups_bonus,
            shard_first_page_estimate_bonus_lines=self.shard_first_page_estimate_bonus_lines,
            shard_first_page_bonus_lines=self.shard_first_page_bonus_lines,
            signing_key_shard_line_groups_bonus=self.signing_key_shard_line_groups_bonus,
            signing_key_shard_first_page_estimate_bonus_lines=(
                self.signing_key_shard_first_page_estimate_bonus_lines
            ),
            signing_key_shard_first_page_bonus_lines=(
                self.signing_key_shard_first_page_bonus_lines
            ),
        )


class _TemplateStyleData(BaseModel):
    """Pydantic boundary model for raw `style.json` content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    header: _HeaderStyleData
    content_offset: _ContentOffsetStyleData
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

    @field_validator("header", mode="before")
    @classmethod
    def _validate_header(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, dict):
            raise ValueError(f"missing or invalid 'header' object in {_context_path(info)}")
        return value

    @field_validator("content_offset", mode="before")
    @classmethod
    def _validate_content_offset(cls, value: object, info: ValidationInfo) -> object:
        if not isinstance(value, dict):
            raise ValueError(f"missing or invalid 'content_offset' object in {_context_path(info)}")
        return value

    @field_validator("capabilities", mode="before")
    @classmethod
    def _validate_capabilities(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError(f"invalid 'capabilities' object in {_context_path(info)}")
        return value

    def to_public(self) -> TemplateStyle:
        return TemplateStyle(
            name=self.name,
            header=self.header.to_public(),
            content_offset=self.content_offset.to_public(),
            capabilities=self.capabilities.to_public(),
        )


def load_template_style(design: str | Path) -> TemplateStyle:
    """Load the style for a render design name, directory, or manifest path."""

    template_dir = resolve_design_directory(design)
    return _load_style_for_dir(template_dir)


@lru_cache(maxsize=32)
def _load_style_for_dir(template_dir: Path) -> TemplateStyle:
    """Load and validate `style.json` for a template directory."""

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
    if field in _NUMBER_FIELDS:
        return f"missing or invalid '{field}' number in {path}"
    if field in _POSITIVE_NUMBER_FIELDS:
        return f"missing or invalid '{field}' positive number in {path}"
    if field in _NON_NEGATIVE_NUMBER_FIELDS:
        return f"missing or invalid '{field}' non-negative number in {path}"
    if field in _NON_NEGATIVE_INT_FIELDS:
        return f"missing or invalid '{field}' non-negative integer in {path}"
    if field in _POSITIVE_INT_FIELDS:
        return f"missing or invalid '{field}' positive integer in {path}"
    if field == "name":
        return f"missing or invalid 'name' string in {path}"
    if field in {
        "header",
        "content_offset",
        "fallback_layout",
        "recovery",
        "shard",
        "signing_key_shard",
    }:
        return f"missing or invalid '{field}' object in {path}"
    return f"invalid template style in {path}"


def _require_number_value(value: object, *, key: str | None, path: Path) -> float:
    if key is None:
        key = "number"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"missing or invalid '{key}' number in {path}")
    return float(value)


def _require_positive_number_value(value: object, *, key: str | None, path: Path) -> float:
    if key is None:
        key = "number"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"missing or invalid '{key}' positive number in {path}")
    return float(value)


def _require_non_negative_number_value(value: object, *, key: str | None, path: Path) -> float:
    if key is None:
        key = "number"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"missing or invalid '{key}' non-negative number in {path}")
    return float(value)


def _require_positive_int_value(value: object, *, key: str | None, path: Path) -> int:
    if key is None:
        key = "number"
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"missing or invalid '{key}' positive integer in {path}")
    return value


def _require_non_negative_int_value(value: object, *, key: str | None, path: Path) -> int:
    if key is None:
        key = "number"
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"missing or invalid '{key}' non-negative integer in {path}")
    return value


def _reject_legacy_capability_keys(data: dict[str, object], *, path: Path) -> None:
    removed_keys = ("wide_recovery_fallback_lines",)
    present = [key for key in removed_keys if key in data]
    if not present:
        return
    present_text = ", ".join(sorted(present))
    raise ValueError(f"legacy capability keys removed: {present_text}; remove them from {path}")


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


__all__ = [
    "FallbackLayoutProfile",
    "RecoveryFallbackLayout",
    "ShardFallbackLayout",
    "TemplateCapabilities",
    "TemplateStyle",
    "load_template_style",
]
