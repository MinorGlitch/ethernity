"""Shared measured fallback layout for Sentinel shard documents."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.encoding.zbase32 import ZBASE32_ALPHABET
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackEntry,
    FallbackSectionLines,
    fallback_entries,
    fallback_sections,
    paginate_single_page_fallback_columns,
)
from ethernity.render.direct_pdf.responsive_layout import GridPolicy, ResolvedGrid, resolve_grid
from ethernity.render.direct_pdf.sentinel.common import SENTINEL_BLACK, SentinelPageLayout
from ethernity.render.direct_pdf.sentinel.theme import SENTINEL_THEME
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_measure import measured_grouped_line_length
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.types import FallbackSection

_GROUP_SIZE = 4
_TEXT_SIZE_PT = 6.0
_MAX_COLUMNS = 2
_ROW_HEIGHT_MM = 2.5
_ROW_GAP_MM = 0.15
_RESCUE_ROW_HEIGHT_MM = 2.3
_RESCUE_ROW_GAP_MM = 0.05
_COLUMN_GAP_MM = 4.0
_HORIZONTAL_INSET_MM = 4.5
_BOTTOM_Y_MM = 275.0
_BOTTOM_PADDING_MM = 0.8
_TEXT_WIDTH_SAFETY_MM = 0.5


@dataclass(frozen=True)
class SentinelShardFallbackLayoutProfile:
    """One measured typography and grid profile for a Sentinel shard fallback."""

    columns: int
    text_size_pt: float
    title_size_pt: float
    row_height_mm: float
    row_gap_mm: float


@dataclass(frozen=True)
class SentinelShardFallbackPageEntry:
    """One fallback entry placed within the Sentinel fallback panel."""

    entry: FallbackEntry
    rect: PdfRect


@dataclass(frozen=True)
class SentinelShardFallbackPage:
    """One fully placed Sentinel shard fallback page."""

    page_number: int
    panel_rect: PdfRect
    layout_profile: SentinelShardFallbackLayoutProfile
    entries: tuple[SentinelShardFallbackPageEntry, ...]


SENTINEL_SHARD_FALLBACK_PROFILES = (
    SentinelShardFallbackLayoutProfile(
        columns=1,
        text_size_pt=_TEXT_SIZE_PT,
        title_size_pt=7.0,
        row_height_mm=_ROW_HEIGHT_MM,
        row_gap_mm=_ROW_GAP_MM,
    ),
    SentinelShardFallbackLayoutProfile(
        columns=2,
        text_size_pt=_TEXT_SIZE_PT,
        title_size_pt=_TEXT_SIZE_PT,
        row_height_mm=_RESCUE_ROW_HEIGHT_MM,
        row_gap_mm=_RESCUE_ROW_GAP_MM,
    ),
)


def resolve_sentinel_shard_fallback_layout(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    page_layout: SentinelPageLayout,
    minimum_top_y_mm: float,
    line_start_offset_mm: float,
    renderer_label: str,
) -> tuple[tuple[FallbackSectionLines, ...], tuple[SentinelShardFallbackPage, ...]]:
    """Select the least-dense Sentinel profile that clears the upper content."""

    for profile in SENTINEL_SHARD_FALLBACK_PROFILES:
        resolved_sections, pages = build_sentinel_shard_fallback_candidate(
            surface,
            sections,
            page_layout=page_layout,
            layout_profile=profile,
            line_start_offset_mm=line_start_offset_mm,
            renderer_label=renderer_label,
        )
        if pages[0].panel_rect.y_mm >= minimum_top_y_mm:
            return resolved_sections, pages
    raise ValueError(
        f"{renderer_label} cannot fit between the upper content and footer "
        f"using up to {_MAX_COLUMNS} measured columns"
    )


def build_sentinel_shard_fallback_candidate(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    page_layout: SentinelPageLayout,
    layout_profile: SentinelShardFallbackLayoutProfile,
    line_start_offset_mm: float,
    renderer_label: str,
) -> tuple[tuple[FallbackSectionLines, ...], tuple[SentinelShardFallbackPage, ...]]:
    """Measure and place one Sentinel fallback layout candidate."""

    column_width_mm = _fallback_column_width(
        page_layout,
        columns=layout_profile.columns,
    )
    style = SENTINEL_THEME.mono_style(
        size_pt=layout_profile.text_size_pt,
        color=SENTINEL_BLACK,
    )
    line_length = measured_grouped_line_length(
        surface,
        style=style,
        alphabet=ZBASE32_ALPHABET,
        group_size=_GROUP_SIZE,
        max_width_mm=column_width_mm,
        safety_mm=_TEXT_WIDTH_SAFETY_MM,
    )
    resolved_sections = fallback_sections(
        sections,
        group_size=_GROUP_SIZE,
        line_length=line_length,
    )
    page = _paginate_fallback_entries(
        fallback_entries(resolved_sections),
        page_layout=page_layout,
        layout_profile=layout_profile,
        line_start_offset_mm=line_start_offset_mm,
        renderer_label=renderer_label,
    )
    return resolved_sections, (page,)


def _fallback_column_width(page_layout: SentinelPageLayout, *, columns: int) -> float:
    if columns <= 0:
        raise ValueError("fallback columns must be positive")
    inner_width_mm = page_layout.safe_rect.width_mm - (2.0 * _HORIZONTAL_INSET_MM)
    column_width_mm = (inner_width_mm - ((columns - 1) * _COLUMN_GAP_MM)) / columns
    if column_width_mm <= 0:
        raise ValueError("Sentinel shard fallback has no horizontal text capacity")
    return column_width_mm


def _paginate_fallback_entries(
    entries: Sequence[FallbackEntry],
    *,
    page_layout: SentinelPageLayout,
    layout_profile: SentinelShardFallbackLayoutProfile,
    line_start_offset_mm: float,
    renderer_label: str,
) -> SentinelShardFallbackPage:
    if not entries:
        raise ValueError(f"{renderer_label} has no fallback entries to render")
    panel_rect, grid = _fallback_grid(
        page_layout,
        entry_count=len(entries),
        layout_profile=layout_profile,
        line_start_offset_mm=line_start_offset_mm,
    )
    placements = paginate_single_page_fallback_columns(
        entries,
        column_count=grid.columns,
        rows_per_column=grid.rows,
        renderer_label=renderer_label,
    )
    return SentinelShardFallbackPage(
        page_number=1,
        panel_rect=panel_rect,
        layout_profile=layout_profile,
        entries=tuple(
            SentinelShardFallbackPageEntry(
                entry=placement.entry,
                rect=PdfRect(
                    grid.container.x_mm
                    + placement.column_index * (grid.item_width_mm + grid.column_gap_mm),
                    grid.container.y_mm
                    + placement.row_index * (grid.item_height_mm + grid.row_gap_mm),
                    grid.item_width_mm,
                    grid.item_height_mm,
                ),
            )
            for placement in placements
        ),
    )


def _fallback_grid(
    page_layout: SentinelPageLayout,
    *,
    entry_count: int,
    layout_profile: SentinelShardFallbackLayoutProfile,
    line_start_offset_mm: float,
) -> tuple[PdfRect, ResolvedGrid]:
    columns = layout_profile.columns
    if columns <= 0 or columns > _MAX_COLUMNS:
        raise ValueError(f"fallback columns must be between 1 and {_MAX_COLUMNS}")
    rows = math.ceil(entry_count / columns)
    rows_height_mm = rows * layout_profile.row_height_mm + (rows - 1) * layout_profile.row_gap_mm
    panel_bottom_mm = page_layout.map_y(_BOTTOM_Y_MM)
    panel_height_mm = line_start_offset_mm + rows_height_mm + _BOTTOM_PADDING_MM
    area = PdfRect(
        page_layout.safe_rect.x_mm,
        panel_bottom_mm - panel_height_mm,
        page_layout.safe_rect.width_mm,
        panel_height_mm,
    )
    row_area = PdfRect(
        area.x_mm + _HORIZONTAL_INSET_MM,
        area.y_mm + line_start_offset_mm,
        area.width_mm - (2.0 * _HORIZONTAL_INSET_MM),
        rows_height_mm,
    )
    item_width_mm = _fallback_column_width(page_layout, columns=columns)
    grid = resolve_grid(
        row_area,
        GridPolicy(
            max_columns=columns,
            max_rows=rows,
            preferred_item_width_mm=item_width_mm,
            preferred_item_height_mm=layout_profile.row_height_mm,
            minimum_item_width_mm=item_width_mm,
            minimum_item_height_mm=layout_profile.row_height_mm,
            minimum_column_gap_mm=(_COLUMN_GAP_MM if columns > 1 else 0.0),
            minimum_row_gap_mm=layout_profile.row_gap_mm,
        ),
    )
    return area, grid


__all__ = [
    "SENTINEL_SHARD_FALLBACK_PROFILES",
    "SentinelShardFallbackLayoutProfile",
    "SentinelShardFallbackPage",
    "SentinelShardFallbackPageEntry",
    "build_sentinel_shard_fallback_candidate",
    "resolve_sentinel_shard_fallback_layout",
]
