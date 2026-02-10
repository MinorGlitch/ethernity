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
from .geometry import fallback_lines_per_page_text_only
from .spec import DocumentSpec
from .template_style import TemplateCapabilities, load_template_style
from .types import Layout, RenderInputs

_MAIN_MAX_ROWS_CAP = 3
_MAIN_FIRST_PAGE_ROWS_CAP = 2
_MAIN_FIRST_PAGE_CONTENT_START_THRESHOLD_MM = 45.0

_RECOVERY_COLUMN_GAP_MM = 12.0
_RECOVERY_NUMBER_GUTTER_MM = 14.0
_RECOVERY_CONTENT_PADDING_MM = 6.0
_RECOVERY_WIDE_LINE_BONUS_MM = 53.0
_SIGNING_INTER_COLUMN_GAP_MM = 8.0
_SIGNING_SECTION_PADDING_MM = 8.0
_SHARD_CARD_PADDING_MM = 8.0

_RECOVERY_BASE_FOOTER_RESERVE_MM = 76.0
_RECOVERY_META_BASELINE_LINES = 3
_RECOVERY_META_SECTION_OVERHEAD_MM = 12.0
_RECOVERY_META_EXTRA_LINE_MM = 8.0
_RECOVERY_CONTINUATION_ROW_PENALTY_LINES = 2
_RECOVERY_WIDE_FIRST_PAGE_BONUS_LINES = 8
_RECOVERY_LIGHT_META_FIRST_PAGE_BONUS_LINES = 10
_RECOVERY_NO_QUORUM_FIRST_PAGE_BONUS_LINES = 2

_SHARD_FIRST_PAGE_PENALTY_LINES = 2
_SIGNING_PAYLOAD_ZONE_HEIGHT_MM = 47.0
_SHARD_PAYLOAD_ZONE_HEIGHT_MM = 56.0
_RECOVERY_LINE_HEIGHT_FLOOR_MM = 5.8
_SHARD_LINE_HEIGHT_FLOOR_MM = 4.8


def _shard_first_page_penalty_lines(capabilities: TemplateCapabilities) -> int:
    return max(0, _SHARD_FIRST_PAGE_PENALTY_LINES - capabilities.shard_first_page_bonus_lines)


def _signing_key_shard_first_page_bonus_lines(capabilities: TemplateCapabilities) -> int:
    return max(0, capabilities.signing_key_shard_first_page_bonus_lines)


def resolve_layout_capabilities(inputs: RenderInputs) -> TemplateCapabilities:
    return load_template_style(inputs.template_path).capabilities


def fallback_text_width_override_mm(
    *,
    capabilities: TemplateCapabilities,
    doc_type: str,
    spec: DocumentSpec,
    page_w: float,
    margin: float,
) -> float | None:
    if not capabilities.advanced_fallback_layout:
        return None

    normalized_doc_type = _normalized_doc_type(doc_type)
    usable_w = page_w - 2 * margin

    if normalized_doc_type == DOC_TYPE_RECOVERY:
        column_w = max(1.0, (usable_w - _RECOVERY_COLUMN_GAP_MM) / 2.0)
        line_width = max(1.0, column_w - _RECOVERY_NUMBER_GUTTER_MM - _RECOVERY_CONTENT_PADDING_MM)
        if capabilities.wide_recovery_fallback_lines:
            line_width = max(1.0, line_width + _RECOVERY_WIDE_LINE_BONUS_MM)
        return line_width
    if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD:
        qr_zone_mm = float(spec.qr_grid.qr_size_mm)
        # Signing-shard templates place QR in a narrow side column; using the raw
        # QR geometry can underestimate text width and force unnecessary wraps.
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
    recovery_has_quorum: bool | None = None,
) -> tuple[float, int]:
    if not capabilities.advanced_fallback_layout:
        return line_height, fallback_lines_per_page_val

    normalized_doc_type = _normalized_doc_type(doc_type)
    if normalized_doc_type == DOC_TYPE_RECOVERY:
        effective_line_height = max(line_height, _RECOVERY_LINE_HEIGHT_FLOOR_MM)
        if include_recovery_metadata_footer:
            metadata_footer_reserve_mm = recovery_metadata_footer_reserve_mm(
                recovery_meta_lines_extra
            )
            available = max(0.0, page_h - margin - content_start_y - metadata_footer_reserve_mm)
            effective_lines = max(1, int(available // max(effective_line_height, 0.1)))
            if capabilities.wide_recovery_fallback_lines:
                effective_lines += _RECOVERY_WIDE_FIRST_PAGE_BONUS_LINES
            effective_lines += _recovery_first_page_light_meta_bonus_lines(
                recovery_meta_lines_extra
            )
            if capabilities.wide_recovery_fallback_lines and recovery_has_quorum is False:
                effective_lines += _RECOVERY_NO_QUORUM_FIRST_PAGE_BONUS_LINES
        else:
            effective_lines = fallback_lines_per_page_text_only(
                content_start_y,
                page_h,
                margin,
                effective_line_height,
            )
            effective_lines = max(
                1,
                effective_lines - _RECOVERY_CONTINUATION_ROW_PENALTY_LINES,
            )
        return effective_line_height, effective_lines

    if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD:
        effective_lines = max(1, int(_SIGNING_PAYLOAD_ZONE_HEIGHT_MM // max(line_height, 0.1)))
        if include_instructions:
            effective_lines = max(
                1,
                effective_lines
                - _shard_first_page_penalty_lines(capabilities)
                + _signing_key_shard_first_page_bonus_lines(capabilities),
            )
        return line_height, effective_lines

    if normalized_doc_type == DOC_TYPE_SHARD:
        effective_line_height = max(line_height, _SHARD_LINE_HEIGHT_FLOOR_MM)
        effective_lines = max(
            1,
            int(_SHARD_PAYLOAD_ZONE_HEIGHT_MM // max(effective_line_height, 0.1)),
        )
        if include_instructions:
            effective_lines = max(
                1,
                effective_lines - _shard_first_page_penalty_lines(capabilities),
            )
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
    recovery_has_quorum: bool | None = None,
) -> int:
    if not capabilities.advanced_fallback_layout:
        return lines_capacity

    normalized_doc_type = _normalized_doc_type(doc_type)
    if normalized_doc_type == DOC_TYPE_SIGNING_KEY_SHARD:
        zone_lines = max(
            1,
            int(_SIGNING_PAYLOAD_ZONE_HEIGHT_MM // max(page_layout.line_height, 0.1)),
        )
        if page_idx <= 0:
            zone_lines = max(
                1,
                zone_lines
                - _shard_first_page_penalty_lines(capabilities)
                + _signing_key_shard_first_page_bonus_lines(capabilities),
            )
        return min(lines_capacity, zone_lines)

    if normalized_doc_type == DOC_TYPE_SHARD:
        zone_lines = max(1, int(_SHARD_PAYLOAD_ZONE_HEIGHT_MM // max(page_layout.line_height, 0.1)))
        if page_idx <= 0:
            zone_lines = max(1, zone_lines - _shard_first_page_penalty_lines(capabilities))
        return min(lines_capacity, zone_lines)

    if normalized_doc_type == DOC_TYPE_RECOVERY:
        if page_idx <= 0:
            metadata_footer_reserve_mm = recovery_metadata_footer_reserve_mm(
                recovery_meta_lines_extra
            )
            available = max(
                0.0,
                page_layout.page_h - page_layout.margin - page_layout.content_start_y,
            )
            line_height = max(page_layout.line_height, 0.1)
            usable = max(0.0, available - metadata_footer_reserve_mm)
            zone_lines = max(1, int(usable // line_height))
            if capabilities.wide_recovery_fallback_lines:
                zone_lines += _RECOVERY_WIDE_FIRST_PAGE_BONUS_LINES
                if recovery_has_quorum is False:
                    zone_lines += _RECOVERY_NO_QUORUM_FIRST_PAGE_BONUS_LINES
            zone_lines += _recovery_first_page_light_meta_bonus_lines(recovery_meta_lines_extra)
            return min(lines_capacity, zone_lines)
        return max(1, lines_capacity - _RECOVERY_CONTINUATION_ROW_PENALTY_LINES)

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


def recovery_metadata_footer_reserve_mm(meta_lines_extra: int) -> float:
    extra_lines = max(0, int(meta_lines_extra) - _RECOVERY_META_BASELINE_LINES)
    section_overhead_mm = _RECOVERY_META_SECTION_OVERHEAD_MM if extra_lines > 0 else 0.0
    return (
        _RECOVERY_BASE_FOOTER_RESERVE_MM
        + section_overhead_mm
        + (extra_lines * _RECOVERY_META_EXTRA_LINE_MM)
    )


def _normalized_doc_type(doc_type: str) -> str:
    return doc_type.strip().lower()


def _recovery_first_page_light_meta_bonus_lines(meta_lines_extra: int) -> int:
    # Passphrase-only recoveries have far less footer metadata than shard-backed
    # recoveries, so they can safely fit additional fallback lines on page 1.
    normalized = max(0, int(meta_lines_extra))
    if 1 <= normalized <= 3:
        return _RECOVERY_LIGHT_META_FIRST_PAGE_BONUS_LINES
    return 0


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
