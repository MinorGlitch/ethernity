"""Build layout reports from measured direct PDF page plans."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ethernity.render.direct_pdf.components import TextBoxPlan
from ethernity.render.direct_pdf.page import (
    DirectPdfPagePlan,
    PaintPlan,
)
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.types import (
    ComponentLayout,
    LayoutReport,
    PageLayout,
    RenderRect,
    RenderTextLine,
)

DIRECT_PDF_BACKEND_NAME = "direct_pdf"


def build_direct_layout_report(
    page_plans: Sequence[DirectPdfPagePlan],
    *,
    backend: str = DIRECT_PDF_BACKEND_NAME,
) -> LayoutReport:
    """Build the measured layout report for direct PDF page plans."""

    page_tuple = tuple(page_plans)
    pages = tuple(_page_layout(page_plan) for page_plan in page_tuple)
    return LayoutReport(
        backend=backend,
        page_count=len(page_tuple),
        pages=pages,
    )


def _page_layout(page_plan: DirectPdfPagePlan) -> PageLayout:
    layout = page_plan.layout
    return PageLayout(
        page_number=layout.page_number,
        rect=_render_rect(layout.rect),
        component_ids=layout.component_ids,
        overflow_component_ids=layout.overflow_component_ids,
        out_of_bounds_component_ids=layout.out_of_bounds_component_ids,
        components=tuple(_component_layout(plan) for plan in page_plan.plans),
        separation_constraints=layout.separation_constraints,
    )


def _component_layout(plan: PaintPlan) -> ComponentLayout:
    layout = plan.layout
    used_rect = getattr(layout, "used_rect", None)
    return ComponentLayout(
        component_id=layout.component_id,
        rect=_render_rect(layout.rect),
        used_rect=_render_rect(used_rect) if isinstance(used_rect, PdfRect) else None,
        overflow=layout.overflow,
        component_type=_optional_str(getattr(layout, "component_type", None)),
        policy=_optional_value(getattr(layout, "policy", None)),
        line_count=_optional_int(getattr(layout, "line_count", None)),
        overflow_line_count=_optional_int(getattr(layout, "overflow_line_count", None)),
        font_size_pt=_optional_float(getattr(layout, "font_size_pt", None)),
        text_lines=(
            tuple(
                RenderTextLine(
                    line.text,
                    line.x_mm,
                    line.baseline_y_mm,
                    (
                        plan.fit.style.color.red,
                        plan.fit.style.color.green,
                        plan.fit.style.color.blue,
                    ),
                )
                for line in plan.lines
            )
            if isinstance(plan, TextBoxPlan)
            else ()
        ),
        text_metadata=plan.text_metadata if isinstance(plan, TextBoxPlan) else None,
    )


def _render_rect(rect: PdfRect) -> RenderRect:
    return RenderRect(
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


__all__ = ["DIRECT_PDF_BACKEND_NAME", "build_direct_layout_report"]
