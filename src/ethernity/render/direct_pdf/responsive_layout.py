"""Dimension-driven layout helpers for direct PDF renderers.

The helpers in this module operate only on physical page geometry.  They deliberately do not
know about named paper sizes or design names, so a renderer can be measured against any portrait
page that satisfies its minimum legibility constraints.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ethernity.render.direct_pdf.types import PdfRect

GridDistribution = Literal["start", "center", "space_between"]

_GEOMETRY_EPSILON_MM = 0.01


@dataclass(frozen=True)
class GridPolicy:
    """Constraints and preferences used to resolve a responsive rectangular grid."""

    max_columns: int
    max_rows: int
    preferred_item_width_mm: float
    preferred_item_height_mm: float
    minimum_item_width_mm: float
    minimum_item_height_mm: float
    minimum_column_gap_mm: float = 0.0
    minimum_row_gap_mm: float = 0.0
    preserve_item_aspect_ratio: bool = False
    horizontal_distribution: GridDistribution = "start"
    vertical_distribution: GridDistribution = "start"

    def __post_init__(self) -> None:
        if self.max_columns <= 0:
            raise ValueError("max_columns must be positive")
        if self.max_rows <= 0:
            raise ValueError("max_rows must be positive")
        for field_name, value in (
            ("preferred_item_width_mm", self.preferred_item_width_mm),
            ("preferred_item_height_mm", self.preferred_item_height_mm),
            ("minimum_item_width_mm", self.minimum_item_width_mm),
            ("minimum_item_height_mm", self.minimum_item_height_mm),
        ):
            _require_finite_positive(value, field_name=field_name)
        for field_name, value in (
            ("minimum_column_gap_mm", self.minimum_column_gap_mm),
            ("minimum_row_gap_mm", self.minimum_row_gap_mm),
        ):
            _require_finite_non_negative(value, field_name=field_name)
        if self.preferred_item_width_mm < self.minimum_item_width_mm:
            raise ValueError("preferred_item_width_mm must be at least minimum_item_width_mm")
        if self.preferred_item_height_mm < self.minimum_item_height_mm:
            raise ValueError("preferred_item_height_mm must be at least minimum_item_height_mm")
        _validate_distribution(self.horizontal_distribution, field_name="horizontal_distribution")
        _validate_distribution(self.vertical_distribution, field_name="vertical_distribution")


@dataclass(frozen=True)
class ResolvedGrid:
    """A grid capacity and item geometry measured inside a concrete container."""

    container: PdfRect
    columns: int
    rows: int
    item_width_mm: float
    item_height_mm: float
    column_gap_mm: float
    row_gap_mm: float
    horizontal_distribution: GridDistribution
    vertical_distribution: GridDistribution

    @property
    def capacity(self) -> int:
        return self.columns * self.rows

    @property
    def used_width_mm(self) -> float:
        return self.columns * self.item_width_mm + (self.columns - 1) * self.column_gap_mm

    @property
    def used_height_mm(self) -> float:
        return self.rows * self.item_height_mm + (self.rows - 1) * self.row_gap_mm

    def item_rects(self, item_count: int, *, reserve_all_rows: bool = False) -> tuple[PdfRect, ...]:
        """Place up to ``capacity`` items in row-major order."""

        if item_count < 0:
            raise ValueError("item_count must be non-negative")
        if item_count > self.capacity:
            raise ValueError(
                f"item_count exceeds resolved grid capacity: {item_count} > {self.capacity}"
            )
        if item_count == 0:
            return ()

        rows_used = self.rows if reserve_all_rows else math.ceil(item_count / self.columns)
        content_height_mm = rows_used * self.item_height_mm + (rows_used - 1) * self.row_gap_mm
        origin_y_mm, row_gap_mm = _distributed_origin_and_gap(
            start_mm=self.container.y_mm,
            available_mm=self.container.height_mm,
            item_size_mm=self.item_height_mm,
            item_count=rows_used,
            minimum_gap_mm=self.row_gap_mm,
            distribution=self.vertical_distribution,
            reserved_content_size_mm=content_height_mm,
        )

        rects: list[PdfRect] = []
        for index in range(item_count):
            row = index // self.columns
            column = index % self.columns
            items_in_row = min(self.columns, item_count - row * self.columns)
            origin_x_mm, column_gap_mm = _distributed_origin_and_gap(
                start_mm=self.container.x_mm,
                available_mm=self.container.width_mm,
                item_size_mm=self.item_width_mm,
                item_count=items_in_row,
                minimum_gap_mm=self.column_gap_mm,
                distribution=self.horizontal_distribution,
            )
            rects.append(
                PdfRect(
                    origin_x_mm + column * (self.item_width_mm + column_gap_mm),
                    origin_y_mm + row * (self.item_height_mm + row_gap_mm),
                    self.item_width_mm,
                    self.item_height_mm,
                )
            )
        return tuple(rects)


def resolve_grid(container: PdfRect, policy: GridPolicy) -> ResolvedGrid:
    """Resolve the highest-capacity legible grid that fits ``container``.

    Capacity is maximized first.  Within equal capacities, the candidate with the largest item area
    wins.  This keeps pagination stable while allowing cards to shrink only as far as the declared
    physical minimums.
    """

    if container.width_mm <= _GEOMETRY_EPSILON_MM or container.height_mm <= _GEOMETRY_EPSILON_MM:
        raise ValueError("grid container must have positive area")

    candidates: list[ResolvedGrid] = []
    for columns in range(1, policy.max_columns + 1):
        available_item_width_mm = (
            container.width_mm - (columns - 1) * policy.minimum_column_gap_mm
        ) / columns
        for rows in range(1, policy.max_rows + 1):
            available_item_height_mm = (
                container.height_mm - (rows - 1) * policy.minimum_row_gap_mm
            ) / rows
            if policy.preserve_item_aspect_ratio:
                scale = min(
                    1.0,
                    available_item_width_mm / policy.preferred_item_width_mm,
                    available_item_height_mm / policy.preferred_item_height_mm,
                )
                item_width_mm = policy.preferred_item_width_mm * scale
                item_height_mm = policy.preferred_item_height_mm * scale
            else:
                item_width_mm = min(policy.preferred_item_width_mm, available_item_width_mm)
                item_height_mm = min(policy.preferred_item_height_mm, available_item_height_mm)
            if item_width_mm + _GEOMETRY_EPSILON_MM < policy.minimum_item_width_mm:
                continue
            if item_height_mm + _GEOMETRY_EPSILON_MM < policy.minimum_item_height_mm:
                continue
            candidates.append(
                ResolvedGrid(
                    container=container,
                    columns=columns,
                    rows=rows,
                    item_width_mm=item_width_mm,
                    item_height_mm=item_height_mm,
                    column_gap_mm=policy.minimum_column_gap_mm,
                    row_gap_mm=policy.minimum_row_gap_mm,
                    horizontal_distribution=policy.horizontal_distribution,
                    vertical_distribution=policy.vertical_distribution,
                )
            )
    if not candidates:
        raise ValueError(
            "page body cannot satisfy minimum grid geometry: "
            f"container={container.width_mm:.3f}x{container.height_mm:.3f}mm, "
            f"minimum_item={policy.minimum_item_width_mm:.3f}x"
            f"{policy.minimum_item_height_mm:.3f}mm, "
            f"minimum_gap={policy.minimum_column_gap_mm:.3f}x"
            f"{policy.minimum_row_gap_mm:.3f}mm"
        )
    return max(
        candidates,
        key=lambda candidate: (
            candidate.capacity,
            candidate.item_width_mm * candidate.item_height_mm,
            candidate.columns,
        ),
    )


def _distributed_origin_and_gap(
    *,
    start_mm: float,
    available_mm: float,
    item_size_mm: float,
    item_count: int,
    minimum_gap_mm: float,
    distribution: GridDistribution,
    reserved_content_size_mm: float | None = None,
) -> tuple[float, float]:
    if item_count <= 0:
        raise ValueError("item_count must be positive")
    minimum_content_mm = (
        item_count * item_size_mm + (item_count - 1) * minimum_gap_mm
        if reserved_content_size_mm is None
        else reserved_content_size_mm
    )
    remaining_mm = available_mm - minimum_content_mm
    if remaining_mm < -_GEOMETRY_EPSILON_MM:
        raise ValueError("resolved grid content exceeds its container")
    remaining_mm = max(0.0, remaining_mm)
    if distribution == "start":
        return start_mm, minimum_gap_mm
    if distribution == "center":
        return start_mm + remaining_mm / 2.0, minimum_gap_mm
    if item_count == 1:
        return start_mm + remaining_mm / 2.0, minimum_gap_mm
    return start_mm, minimum_gap_mm + remaining_mm / (item_count - 1)


def _validate_distribution(value: str, *, field_name: str) -> None:
    if value not in {"start", "center", "space_between"}:
        raise ValueError(f"{field_name} must be start, center, or space_between")


def _require_finite_positive(value: float, *, field_name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be finite and positive")


def _require_finite_non_negative(value: float, *, field_name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")


__all__ = [
    "GridDistribution",
    "GridPolicy",
    "ResolvedGrid",
    "resolve_grid",
]
