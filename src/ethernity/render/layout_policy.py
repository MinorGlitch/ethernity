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

from .doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from .spec import DocumentSpec
from .template_style import (
    RecoveryFallbackLayout,
    ShardFallbackLayout,
    TemplateCapabilities,
    load_template_style,
)
from .types import Layout, RenderInputs

_MAIN_MAX_ROWS_CAP = 3
_MAIN_FIRST_PAGE_ROWS_CAP = 2
_MAIN_FIRST_PAGE_CONTENT_START_THRESHOLD_MM = 45.0

_RECOVERY_COLUMN_GAP_MM = 12.0
_RECOVERY_NUMBER_GUTTER_MM = 14.0
_RECOVERY_CONTENT_PADDING_MM = 6.0
_SIGNING_INTER_COLUMN_GAP_MM = 8.0
_SIGNING_SECTION_PADDING_MM = 8.0
_SHARD_CARD_PADDING_MM = 8.0


def resolve_layout_capabilities(inputs: RenderInputs) -> TemplateCapabilities:
    return load_template_style(inputs.template_path).capabilities


def fallback_text_width_override_mm(
    *,
    capabilities: TemplateCapabilities,
    doc_type: str,
    spec: DocumentSpec,
    page_w: float,
    margin: float,
    include_instructions: bool,
) -> float | None:
    if not capabilities.advanced_fallback_layout or capabilities.fallback_layout is None:
        return None

    normalized_doc_type = _normalized_doc_type(doc_type)
    usable_w = page_w - 2 * margin

    if normalized_doc_type == DOC_TYPE_RECOVERY:
        profile = capabilities.fallback_layout.recovery
        column_w = max(1.0, (usable_w - _RECOVERY_COLUMN_GAP_MM) / 2.0)
        line_width = max(1.0, column_w - _RECOVERY_NUMBER_GUTTER_MM - _RECOVERY_CONTENT_PADDING_MM)
        width_bonus = (
            profile.first_page_text_width_bonus_mm
            if include_instructions
            else profile.continuation_text_width_bonus_mm
        )
        return max(1.0, line_width + width_bonus)
    if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD:
        qr_zone_mm = float(spec.qr_grid.qr_size_mm)
        qr_column_mm = min(qr_zone_mm, usable_w / 3.0)
        return max(
            1.0,
            usable_w - qr_column_mm - _SIGNING_INTER_COLUMN_GAP_MM - _SIGNING_SECTION_PADDING_MM,
        )
    if normalized_doc_type == DOC_TYPE_SHARD:
        return max(1.0, usable_w - _SHARD_CARD_PADDING_MM)
    return None


def should_force_max_rows(*, capabilities: TemplateCapabilities) -> bool:
    # Card-heavy templates can overflow if rows are forced from raw QR geometry.
    return not capabilities.advanced_fallback_layout


def max_rows_override_for_template(
    *,
    capabilities: TemplateCapabilities,
    doc_type: str,
    max_rows: int | None,
    include_instructions: bool,
    content_start_y: float,
) -> int | None:
    if not capabilities.advanced_fallback_layout or max_rows is None:
        return max_rows

    normalized_doc_type = _normalized_doc_type(doc_type)
    if normalized_doc_type not in {DOC_TYPE_MAIN, DOC_TYPE_KIT}:
        return max_rows

    capped_rows = min(int(max_rows), _MAIN_MAX_ROWS_CAP)
    if (
        normalized_doc_type == DOC_TYPE_MAIN
        and include_instructions
        and content_start_y >= _MAIN_FIRST_PAGE_CONTENT_START_THRESHOLD_MM
    ):
        return min(capped_rows, _MAIN_FIRST_PAGE_ROWS_CAP)
    return capped_rows


def adjust_layout_fallback_capacity(
    *,
    capabilities: TemplateCapabilities,
    doc_type: str,
    content_start_y: float,
    page_h: float,
    margin: float,
    line_height: float,
    fallback_lines_per_page_val: int,
    include_recovery_metadata_footer: bool,
    recovery_meta_lines_extra: int,
    include_instructions: bool,
) -> tuple[float, int]:
    if not capabilities.advanced_fallback_layout or capabilities.fallback_layout is None:
        return line_height, fallback_lines_per_page_val

    normalized_doc_type = _normalized_doc_type(doc_type)
    if normalized_doc_type == DOC_TYPE_RECOVERY:
        recovery_profile = capabilities.fallback_layout.recovery
        effective_line_height = max(line_height, recovery_profile.line_height_floor_mm)
        reserve_mm = _recovery_footer_reserve_mm(
            profile=recovery_profile,
            meta_lines_extra=recovery_meta_lines_extra,
            include_recovery_metadata_footer=include_recovery_metadata_footer,
        )
        available = max(0.0, page_h - margin - content_start_y - reserve_mm)
        effective_lines = max(1, int(available // max(effective_line_height, 0.1)))
        return effective_line_height, effective_lines

    if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD:
        signing_key_shard_profile: ShardFallbackLayout = (
            capabilities.fallback_layout.signing_key_shard
        )
        effective_line_height = max(line_height, signing_key_shard_profile.line_height_floor_mm)
        zone_mm = (
            signing_key_shard_profile.first_page_payload_zone_height_mm
            if include_instructions
            else signing_key_shard_profile.continuation_payload_zone_height_mm
        )
        effective_lines = max(1, int(zone_mm // max(effective_line_height, 0.1)))
        return effective_line_height, effective_lines

    if normalized_doc_type == DOC_TYPE_SHARD:
        shard_profile: ShardFallbackLayout = capabilities.fallback_layout.shard
        effective_line_height = max(line_height, shard_profile.line_height_floor_mm)
        zone_mm = (
            shard_profile.first_page_payload_zone_height_mm
            if include_instructions
            else shard_profile.continuation_payload_zone_height_mm
        )
        effective_lines = max(1, int(zone_mm // max(effective_line_height, 0.1)))
        return effective_line_height, effective_lines

    return line_height, fallback_lines_per_page_val


def adjust_page_fallback_capacity(
    *,
    capabilities: TemplateCapabilities,
    doc_type: str,
    page_layout: Layout,
    lines_capacity: int,
    page_idx: int,
    recovery_meta_lines_extra: int,
) -> int:
    if not capabilities.advanced_fallback_layout or capabilities.fallback_layout is None:
        return lines_capacity

    normalized_doc_type = _normalized_doc_type(doc_type)
    if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD:
        signing_key_shard_profile: ShardFallbackLayout = (
            capabilities.fallback_layout.signing_key_shard
        )
        line_height = max(
            page_layout.line_height,
            signing_key_shard_profile.line_height_floor_mm,
            0.1,
        )
        zone_mm = (
            signing_key_shard_profile.first_page_payload_zone_height_mm
            if page_idx <= 0
            else signing_key_shard_profile.continuation_payload_zone_height_mm
        )
        zone_lines = max(1, int(zone_mm // line_height))
        return min(lines_capacity, zone_lines)

    if normalized_doc_type == DOC_TYPE_SHARD:
        shard_profile: ShardFallbackLayout = capabilities.fallback_layout.shard
        line_height = max(page_layout.line_height, shard_profile.line_height_floor_mm, 0.1)
        zone_mm = (
            shard_profile.first_page_payload_zone_height_mm
            if page_idx <= 0
            else shard_profile.continuation_payload_zone_height_mm
        )
        zone_lines = max(1, int(zone_mm // line_height))
        return min(lines_capacity, zone_lines)

    if normalized_doc_type == DOC_TYPE_RECOVERY:
        recovery_profile = capabilities.fallback_layout.recovery
        line_height = max(page_layout.line_height, recovery_profile.line_height_floor_mm, 0.1)
        reserve_mm = _recovery_footer_reserve_mm(
            profile=recovery_profile,
            meta_lines_extra=recovery_meta_lines_extra,
            include_recovery_metadata_footer=page_idx <= 0,
        )
        available = max(
            0.0,
            page_layout.page_h - page_layout.margin - page_layout.content_start_y - reserve_mm,
        )
        zone_lines = max(1, int(available // line_height))
        return min(lines_capacity, zone_lines)

    return lines_capacity


def should_repeat_primary_qr_on_shard_continuation(
    *,
    capabilities: TemplateCapabilities,
    doc_type: str,
) -> bool:
    if not capabilities.repeat_primary_qr_on_shard_continuation:
        return False
    normalized_doc_type = _normalized_doc_type(doc_type)
    return normalized_doc_type in {DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD}


def extra_main_first_page_qr_slots(
    *,
    capabilities: TemplateCapabilities,
    doc_type: str,
    page_idx: int,
) -> int:
    if not capabilities.extra_main_first_page_qr_slot:
        return 0
    if page_idx != 0:
        return 0
    normalized_doc_type = _normalized_doc_type(doc_type)
    if normalized_doc_type != DOC_TYPE_MAIN:
        return 0
    return 1


def _recovery_footer_reserve_mm(
    *,
    profile: RecoveryFallbackLayout,
    meta_lines_extra: int,
    include_recovery_metadata_footer: bool,
) -> float:
    if not include_recovery_metadata_footer:
        return profile.continuation_footer_reserve_mm

    extra_lines = max(0, int(meta_lines_extra) - int(profile.meta_baseline_lines))
    section_overhead_mm = profile.meta_section_overhead_mm if extra_lines > 0 else 0.0
    return (
        profile.first_page_footer_reserve_mm
        + section_overhead_mm
        + (extra_lines * profile.meta_extra_line_mm)
    )


def _normalized_doc_type(doc_type: str) -> str:
    return doc_type.strip().lower()


__all__ = [
    "adjust_layout_fallback_capacity",
    "adjust_page_fallback_capacity",
    "extra_main_first_page_qr_slots",
    "fallback_text_width_override_mm",
    "max_rows_override_for_template",
    "resolve_layout_capabilities",
    "should_force_max_rows",
    "should_repeat_primary_qr_on_shard_continuation",
]
