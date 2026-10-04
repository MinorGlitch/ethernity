"""Shared single-page fallback placement for Forge shard documents."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.render.direct_pdf.fallback_layout import (
    FallbackColumnPlacement,
    FallbackEntry,
    fallback_capacity,
    paginate_single_page_fallback_columns,
)
from ethernity.render.direct_pdf.types import PdfRect


@dataclass(frozen=True)
class ForgeShardFallbackLayoutProfile:
    """One typography and density profile for a Forge shard fallback."""

    column_count: int
    font_size_pt: float
    row_height_mm: float


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


def place_forge_shard_fallback_entries(
    entries: Sequence[FallbackEntry],
    *,
    area: PdfRect,
    profile: ForgeShardFallbackLayoutProfile,
    reserved_height_mm: float,
    renderer_label: str,
) -> tuple[FallbackColumnPlacement, ...]:
    """Place all Forge shard fallback entries on one page."""

    return paginate_single_page_fallback_columns(
        entries,
        column_count=profile.column_count,
        rows_per_column=fallback_capacity(
            area,
            row_height_mm=profile.row_height_mm,
            reserved_height_mm=reserved_height_mm,
        ),
        renderer_label=renderer_label,
    )


__all__ = [
    "ForgeShardFallbackLayoutProfile",
    "forge_shard_fallback_profiles",
    "place_forge_shard_fallback_entries",
]
