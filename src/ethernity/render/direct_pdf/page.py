"""Page-level planning and proof containers for direct PDF rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.types import PdfRect

_GEOMETRY_EPSILON_MM = 0.01


class PlacementProof(Protocol):
    """Common proof shape emitted by planned components."""

    @property
    def component_id(self) -> str:
        """Component identifier attached to this proof."""

    @property
    def rect(self) -> PdfRect:
        """Assigned component rectangle in page coordinates."""

    @property
    def overflow(self) -> bool:
        """Whether the planned component overflowed its assigned box."""


class PaintPlan(Protocol):
    """A measured plan that can paint itself and expose placement proof."""

    @property
    def component_id(self) -> str:
        """Component identifier for inventory and proof aggregation."""

    @property
    def proof(self) -> PlacementProof:
        """Placement proof emitted by the plan."""

    def paint(self, surface: PdfSurface) -> None:
        """Paint the measured plan to a PDF surface."""


@dataclass(frozen=True)
class DirectPdfPageProof:
    """Proof inventory for one planned PDF page."""

    page_number: int
    rect: PdfRect
    component_ids: tuple[str, ...]
    overflow_component_ids: tuple[str, ...]
    out_of_bounds_component_ids: tuple[str, ...] = ()

    @property
    def overflow(self) -> bool:
        return bool(self.overflow_component_ids or self.out_of_bounds_component_ids)


@dataclass(frozen=True)
class DirectPdfPagePlan:
    """A direct-PDF page assembled from measured component plans."""

    page_number: int
    rect: PdfRect
    plans: tuple[PaintPlan, ...]
    proof: DirectPdfPageProof

    def paint(self, surface: PdfSurface) -> None:
        """Append and paint this page to the PDF surface."""

        surface.add_page()
        for plan in self.plans:
            plan.paint(surface)


def build_page_plan(
    *,
    page_number: int,
    rect: PdfRect,
    plans: Sequence[PaintPlan],
) -> DirectPdfPagePlan:
    """Build a page plan and aggregate component proof inventory."""

    if page_number <= 0:
        raise ValueError("page_number must be positive")
    if rect.width_mm <= 0 or rect.height_mm <= 0:
        raise ValueError("page rect must be positive")
    plan_tuple = tuple(plans)
    component_ids = tuple(plan.component_id for plan in plan_tuple)
    duplicate_ids = _duplicates(component_ids)
    if duplicate_ids:
        raise ValueError(f"duplicate component id in page plan: {duplicate_ids[0]}")
    out_of_bounds_component_ids = _out_of_bounds_component_ids(rect, plan_tuple)
    if out_of_bounds_component_ids:
        raise ValueError(f"component outside page bounds: {out_of_bounds_component_ids[0]}")
    used_rect_out_of_bounds_ids = _used_rect_out_of_bounds_component_ids(plan_tuple)
    if used_rect_out_of_bounds_ids:
        raise ValueError(
            f"component used rect outside assigned bounds: {used_rect_out_of_bounds_ids[0]}"
        )
    overflow_component_ids = tuple(
        plan.component_id for plan in plan_tuple if bool(plan.proof.overflow)
    )
    proof = DirectPdfPageProof(
        page_number=page_number,
        rect=rect,
        component_ids=component_ids,
        overflow_component_ids=overflow_component_ids,
        out_of_bounds_component_ids=(),
    )
    return DirectPdfPagePlan(
        page_number=page_number,
        rect=rect,
        plans=plan_tuple,
        proof=proof,
    )


def _out_of_bounds_component_ids(
    page_rect: PdfRect,
    plans: Sequence[PaintPlan],
) -> tuple[str, ...]:
    return tuple(
        plan.component_id for plan in plans if not _contains_rect(page_rect, plan.proof.rect)
    )


def _used_rect_out_of_bounds_component_ids(plans: Sequence[PaintPlan]) -> tuple[str, ...]:
    component_ids: list[str] = []
    for plan in plans:
        used_rect = getattr(plan.proof, "used_rect", None)
        if isinstance(used_rect, PdfRect) and not _contains_rect(plan.proof.rect, used_rect):
            component_ids.append(plan.component_id)
    return tuple(component_ids)


def _contains_rect(outer: PdfRect, inner: PdfRect) -> bool:
    return (
        inner.x_mm >= outer.x_mm - _GEOMETRY_EPSILON_MM
        and inner.y_mm >= outer.y_mm - _GEOMETRY_EPSILON_MM
        and inner.right_mm <= outer.right_mm + _GEOMETRY_EPSILON_MM
        and inner.bottom_mm <= outer.bottom_mm + _GEOMETRY_EPSILON_MM
    )


def _duplicates(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


__all__ = [
    "DirectPdfPagePlan",
    "DirectPdfPageProof",
    "PaintPlan",
    "PlacementProof",
    "build_page_plan",
]
