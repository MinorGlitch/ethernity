"""Page-level planning and proof containers for direct PDF rendering."""

from __future__ import annotations

import math
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
class ComponentGroup:
    """A named semantic group of planned components used by layout constraints."""

    group_id: str
    component_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_identifier(self.group_id, field_name="group_id")
        if not self.component_ids:
            raise ValueError("component_ids must be non-empty")
        for component_id in self.component_ids:
            _validate_identifier(component_id, field_name="component_id")
        duplicate_ids = _duplicates(self.component_ids)
        if duplicate_ids:
            raise ValueError(f"duplicate component id in component group: {duplicate_ids[0]}")


@dataclass(frozen=True)
class LayoutRegion:
    """A named fixed page region used by layout constraints.

    Regions are independent of paper dimensions and can represent page-safe, content,
    header, footer, or other semantic zones computed by a page builder.
    """

    region_id: str
    rect: PdfRect

    def __post_init__(self) -> None:
        _validate_identifier(self.region_id, field_name="region_id")


SeparationTarget = ComponentGroup | LayoutRegion


@dataclass(frozen=True)
class SeparationConstraint:
    """Require two explicitly declared layout targets to remain separated."""

    constraint_id: str
    first: SeparationTarget
    second: SeparationTarget
    minimum_clearance_mm: float = 0.0

    def __post_init__(self) -> None:
        _validate_identifier(self.constraint_id, field_name="constraint_id")
        if not isinstance(self.first, (ComponentGroup, LayoutRegion)):
            raise TypeError("first must be a ComponentGroup or LayoutRegion")
        if not isinstance(self.second, (ComponentGroup, LayoutRegion)):
            raise TypeError("second must be a ComponentGroup or LayoutRegion")
        if not math.isfinite(self.minimum_clearance_mm):
            raise ValueError("minimum_clearance_mm must be finite")
        if self.minimum_clearance_mm < 0:
            raise ValueError("minimum_clearance_mm must be non-negative")


@dataclass(frozen=True)
class SeparationConstraintProof:
    """Result of validating one page separation constraint."""

    constraint_id: str
    first_region_id: str
    second_region_id: str
    minimum_clearance_mm: float
    measured_clearance_mm: float
    checked_pair_count: int
    satisfied: bool


@dataclass(frozen=True)
class DirectPdfPageProof:
    """Proof inventory for one planned PDF page."""

    page_number: int
    rect: PdfRect
    component_ids: tuple[str, ...]
    overflow_component_ids: tuple[str, ...]
    out_of_bounds_component_ids: tuple[str, ...] = ()
    separation_constraints: tuple[SeparationConstraintProof, ...] = ()

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
    separation_constraints: Sequence[SeparationConstraint] = (),
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
    constraint_tuple = tuple(separation_constraints)
    duplicate_constraint_ids = _duplicates(
        tuple(constraint.constraint_id for constraint in constraint_tuple)
    )
    if duplicate_constraint_ids:
        raise ValueError(
            f"duplicate separation constraint id in page plan: {duplicate_constraint_ids[0]}"
        )
    separation_constraint_proofs = _validate_separation_constraints(
        plan_tuple,
        constraint_tuple,
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
        separation_constraints=separation_constraint_proofs,
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


@dataclass(frozen=True)
class _ResolvedConstraintRect:
    item_id: str
    rect: PdfRect


def _validate_separation_constraints(
    plans: Sequence[PaintPlan],
    constraints: Sequence[SeparationConstraint],
) -> tuple[SeparationConstraintProof, ...]:
    component_rects = {plan.component_id: plan.proof.rect for plan in plans}
    proofs: list[SeparationConstraintProof] = []
    for constraint in constraints:
        first_rects = _resolve_constraint_target(
            constraint,
            constraint.first,
            component_rects=component_rects,
        )
        second_rects = _resolve_constraint_target(
            constraint,
            constraint.second,
            component_rects=component_rects,
        )
        measured_clearances: list[float] = []
        for first in first_rects:
            for second in second_rects:
                horizontal_gap_mm = _axis_gap(
                    first.rect.x_mm,
                    first.rect.right_mm,
                    second.rect.x_mm,
                    second.rect.right_mm,
                )
                vertical_gap_mm = _axis_gap(
                    first.rect.y_mm,
                    first.rect.bottom_mm,
                    second.rect.y_mm,
                    second.rect.bottom_mm,
                )
                measured_clearance_mm = max(0.0, horizontal_gap_mm, vertical_gap_mm)
                measured_clearances.append(measured_clearance_mm)
                if (
                    horizontal_gap_mm + _GEOMETRY_EPSILON_MM < constraint.minimum_clearance_mm
                    and vertical_gap_mm + _GEOMETRY_EPSILON_MM < constraint.minimum_clearance_mm
                ):
                    relationship = (
                        "rectangles overlap"
                        if horizontal_gap_mm < 0 and vertical_gap_mm < 0
                        else "clearance is too small"
                    )
                    raise ValueError(
                        f"layout separation constraint '{constraint.constraint_id}' violated: "
                        f"{first.item_id} in '{_target_id(constraint.first)}' and "
                        f"{second.item_id} in '{_target_id(constraint.second)}'; "
                        f"{relationship}; required {constraint.minimum_clearance_mm:.3f} mm, "
                        f"measured {measured_clearance_mm:.3f} mm "
                        f"(horizontal gap {horizontal_gap_mm:.3f} mm, "
                        f"vertical gap {vertical_gap_mm:.3f} mm)"
                    )
        proofs.append(
            SeparationConstraintProof(
                constraint_id=constraint.constraint_id,
                first_region_id=_target_id(constraint.first),
                second_region_id=_target_id(constraint.second),
                minimum_clearance_mm=constraint.minimum_clearance_mm,
                measured_clearance_mm=min(measured_clearances),
                checked_pair_count=len(measured_clearances),
                satisfied=True,
            )
        )
    return tuple(proofs)


def _resolve_constraint_target(
    constraint: SeparationConstraint,
    target: SeparationTarget,
    *,
    component_rects: dict[str, PdfRect],
) -> tuple[_ResolvedConstraintRect, ...]:
    if isinstance(target, LayoutRegion):
        return (_ResolvedConstraintRect(item_id=f"region '{target.region_id}'", rect=target.rect),)

    resolved: list[_ResolvedConstraintRect] = []
    for component_id in target.component_ids:
        component_rect = component_rects.get(component_id)
        if component_rect is None:
            raise ValueError(
                f"layout separation constraint '{constraint.constraint_id}' group "
                f"'{target.group_id}' references missing component id: {component_id}"
            )
        resolved.append(
            _ResolvedConstraintRect(
                item_id=f"component '{component_id}'",
                rect=component_rect,
            )
        )
    return tuple(resolved)


def _target_id(target: SeparationTarget) -> str:
    if isinstance(target, ComponentGroup):
        return target.group_id
    return target.region_id


def _axis_gap(
    first_start_mm: float,
    first_end_mm: float,
    second_start_mm: float,
    second_end_mm: float,
) -> float:
    return max(second_start_mm - first_end_mm, first_start_mm - second_end_mm)


def _validate_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _duplicates(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


__all__ = [
    "ComponentGroup",
    "DirectPdfPagePlan",
    "DirectPdfPageProof",
    "LayoutRegion",
    "PaintPlan",
    "PlacementProof",
    "SeparationConstraint",
    "SeparationConstraintProof",
    "SeparationTarget",
    "build_page_plan",
]
