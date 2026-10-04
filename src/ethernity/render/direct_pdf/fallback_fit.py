"""Measure and select readable single-page fallback profiles."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ethernity.encoding.zbase32 import ZBASE32_ALPHABET
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackEntry,
    FallbackSectionLines,
    fallback_entries,
    fallback_sections,
)
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_measure import measured_grouped_line_length
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.types import FallbackSection


@dataclass(frozen=True)
class SinglePageFallbackProfile:
    """Typography and spacing supplied by a document's local layout policy."""

    columns: int
    row_height_mm: float
    body_style: TextStyle
    column_gap_mm: float
    horizontal_padding_mm: float = 0.0
    payload_inset_mm: float = 0.0
    reserved_height_mm: float = 0.0
    safety_mm: float = 0.2


@dataclass(frozen=True)
class SinglePageFallbackFit:
    """The first fitting profile and its measured, encoded fallback content."""

    profile_index: int
    sections: tuple[FallbackSectionLines, ...]
    entries: tuple[FallbackEntry, ...]


def fallback_column_width(
    area: PdfRect,
    *,
    columns: int,
    column_gap_mm: float,
    horizontal_padding_mm: float = 0.0,
) -> float:
    """Measure usable column width after outer padding and column gaps."""

    if isinstance(columns, bool) or not isinstance(columns, int) or columns <= 0:
        raise ValueError("fallback columns must be a positive integer")
    for label, value in (
        ("column gap", column_gap_mm),
        ("horizontal padding", horizontal_padding_mm),
    ):
        _validate_spacing(label, value)
    width_mm = area.width_mm - 2.0 * horizontal_padding_mm - (columns - 1) * column_gap_mm
    width_mm /= columns
    if not math.isfinite(width_mm) or width_mm <= 0:
        raise ValueError("fallback columns have no usable width")
    return width_mm


def fit_single_page_fallback(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    area: PdfRect,
    profiles: Sequence[SinglePageFallbackProfile],
    group_size: int,
    overflow_message: str,
    entries_builder: Callable[
        [Sequence[FallbackSectionLines]], tuple[FallbackEntry, ...]
    ] = fallback_entries,
) -> SinglePageFallbackFit:
    """Try profiles in caller order without choosing artwork, labels, or placement."""

    if not sections:
        raise ValueError("fallback fitting requires at least one source section")
    if not profiles:
        raise ValueError("fallback fitting requires at least one profile")
    for index, profile in enumerate(profiles):
        if not math.isfinite(profile.row_height_mm) or profile.row_height_mm <= 0:
            raise ValueError("fallback row height must be finite and positive")
        for label, value in (
            ("payload inset", profile.payload_inset_mm),
            ("reserved height", profile.reserved_height_mm),
            ("text safety", profile.safety_mm),
        ):
            _validate_spacing(label, value)
        payload_width_mm = (
            fallback_column_width(
                area,
                columns=profile.columns,
                column_gap_mm=profile.column_gap_mm,
                horizontal_padding_mm=profile.horizontal_padding_mm,
            )
            - profile.payload_inset_mm
        )
        if payload_width_mm <= profile.safety_mm:
            raise ValueError("fallback spacing leaves no usable payload width")
        line_length = measured_grouped_line_length(
            surface,
            style=profile.body_style,
            alphabet=ZBASE32_ALPHABET,
            group_size=group_size,
            max_width_mm=payload_width_mm,
            safety_mm=profile.safety_mm,
        )
        resolved_sections = fallback_sections(
            sections, group_size=group_size, line_length=line_length
        )
        entries = entries_builder(resolved_sections)
        rows = math.floor(
            max(0.0, area.height_mm - profile.reserved_height_mm) / profile.row_height_mm
        )
        if entries and len(entries) <= rows * profile.columns:
            return SinglePageFallbackFit(
                profile_index=index,
                sections=resolved_sections,
                entries=entries,
            )
    raise ValueError(overflow_message)


def _validate_spacing(label: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"fallback {label} must be finite and non-negative")


__all__ = [
    "SinglePageFallbackFit",
    "SinglePageFallbackProfile",
    "fallback_column_width",
    "fit_single_page_fallback",
]
