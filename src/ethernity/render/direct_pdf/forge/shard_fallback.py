"""Shared single-page fallback placement for Forge shard documents."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.render.direct_pdf.fallback_layout import (
    FallbackEntry,
    paginate_single_page_fallback_columns,
)
from ethernity.render.direct_pdf.types import PdfRect


@dataclass(frozen=True)
class ForgeShardFallbackLayoutProfile:
    """One typography and density profile for a Forge shard fallback."""

    column_count: int
    font_size_pt: float
    row_height_mm: float


@dataclass(frozen=True)
class ForgeShardFallbackPageEntry:
    """One Forge fallback entry placed in a column-major grid."""

    entry: FallbackEntry
    row_index: int
    column_index: int


def forge_shard_fallback_profiles(
    *,
    standard_row_height_mm: float,
    dense_row_height_mm: float,
) -> tuple[ForgeShardFallbackLayoutProfile, ...]:
    """Build the two supported Forge shard density profiles."""

    return (
        ForgeShardFallbackLayoutProfile(
            column_count=1,
            font_size_pt=6.0,
            row_height_mm=standard_row_height_mm,
        ),
        ForgeShardFallbackLayoutProfile(
            column_count=2,
            font_size_pt=6.0,
            row_height_mm=dense_row_height_mm,
        ),
    )


def forge_shard_fallback_column_width(
    area: PdfRect,
    *,
    column_count: int,
    horizontal_padding_mm: float,
    column_gap_mm: float,
) -> float:
    """Return the usable width of one Forge fallback column."""

    if column_count <= 0:
        raise ValueError("fallback column count must be positive")
    content_width_mm = area.width_mm - 2.0 * horizontal_padding_mm
    gap_width_mm = (column_count - 1) * column_gap_mm
    column_width_mm = (content_width_mm - gap_width_mm) / column_count
    if column_width_mm <= 0:
        raise ValueError("Forge shard fallback columns have no usable width")
    return column_width_mm


def forge_shard_fallback_rows_per_column(
    area: PdfRect,
    *,
    row_height_mm: float,
    reserved_height_mm: float,
) -> int:
    """Return the number of readable fallback rows in one Forge column."""

    if row_height_mm <= 0:
        raise ValueError("fallback row height must be positive")
    if reserved_height_mm < 0:
        raise ValueError("fallback reserved height must be non-negative")
    return math.floor(max(0.0, area.height_mm - reserved_height_mm) / row_height_mm)


def forge_shard_fallback_capacity(
    area: PdfRect,
    *,
    profile: ForgeShardFallbackLayoutProfile,
    reserved_height_mm: float,
) -> int:
    """Return the single-page capacity of a Forge fallback profile."""

    return (
        forge_shard_fallback_rows_per_column(
            area,
            row_height_mm=profile.row_height_mm,
            reserved_height_mm=reserved_height_mm,
        )
        * profile.column_count
    )


def place_forge_shard_fallback_entries(
    entries: Sequence[FallbackEntry],
    *,
    area: PdfRect,
    profile: ForgeShardFallbackLayoutProfile,
    reserved_height_mm: float,
    renderer_label: str,
) -> tuple[ForgeShardFallbackPageEntry, ...]:
    """Place all Forge shard fallback entries on one page."""

    placements = paginate_single_page_fallback_columns(
        entries,
        column_count=profile.column_count,
        rows_per_column=forge_shard_fallback_rows_per_column(
            area,
            row_height_mm=profile.row_height_mm,
            reserved_height_mm=reserved_height_mm,
        ),
        renderer_label=renderer_label,
    )
    return tuple(
        ForgeShardFallbackPageEntry(
            entry=placement.entry,
            row_index=placement.row_index,
            column_index=placement.column_index,
        )
        for placement in placements
    )


__all__ = [
    "ForgeShardFallbackLayoutProfile",
    "ForgeShardFallbackPageEntry",
    "forge_shard_fallback_capacity",
    "forge_shard_fallback_column_width",
    "forge_shard_fallback_profiles",
    "forge_shard_fallback_rows_per_column",
    "place_forge_shard_fallback_entries",
]
