"""Build public layout proofs from measured direct PDF page plans."""

from __future__ import annotations

from typing import Any, Sequence

from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.types import (
    RenderComponentLayoutProof,
    RenderLayoutProof,
    RenderPageLayoutProof,
    RenderRectProof,
)

DIRECT_PDF_BACKEND_NAME = "direct_pdf"


def build_direct_layout_proof(
    page_plans: Sequence[DirectPdfPagePlan],
    *,
    backend: str = DIRECT_PDF_BACKEND_NAME,
) -> RenderLayoutProof:
    """Build the public geometry proof for direct PDF page plans."""

    page_tuple = tuple(page_plans)
    pages = tuple(_page_layout_proof(page_plan) for page_plan in page_tuple)
    return RenderLayoutProof(
        backend=backend,
        page_count=len(page_tuple),
        pages=pages,
    )


def _page_layout_proof(page_plan: DirectPdfPagePlan) -> RenderPageLayoutProof:
    proof = page_plan.proof
    return RenderPageLayoutProof(
        page_number=proof.page_number,
        rect=_rect_proof(proof.rect),
        component_ids=proof.component_ids,
        overflow_component_ids=proof.overflow_component_ids,
        out_of_bounds_component_ids=proof.out_of_bounds_component_ids,
        components=tuple(_component_layout_proof(plan) for plan in page_plan.plans),
    )


def _component_layout_proof(plan: PaintPlan) -> RenderComponentLayoutProof:
    proof = plan.proof
    used_rect = getattr(proof, "used_rect", None)
    return RenderComponentLayoutProof(
        component_id=proof.component_id,
        rect=_rect_proof(proof.rect),
        used_rect=_rect_proof(used_rect) if isinstance(used_rect, PdfRect) else None,
        overflow=proof.overflow,
        component_type=_optional_str(getattr(proof, "component_type", None)),
        policy=_optional_value(getattr(proof, "policy", None)),
        line_count=_optional_int(getattr(proof, "line_count", None)),
        overflow_line_count=_optional_int(getattr(proof, "overflow_line_count", None)),
        font_size_pt=_optional_float(getattr(proof, "font_size_pt", None)),
    )


def _rect_proof(rect: PdfRect) -> RenderRectProof:
    return RenderRectProof(
        x_mm=rect.x_mm,
        y_mm=rect.y_mm,
        width_mm=rect.width_mm,
        height_mm=rect.height_mm,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_value(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return str(value)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


__all__ = ["DIRECT_PDF_BACKEND_NAME", "build_direct_layout_proof"]
