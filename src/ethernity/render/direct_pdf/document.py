"""Measured document plans and the shared direct-PDF rendering lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.layout_report import build_direct_layout_report
from ethernity.render.direct_pdf.page import DirectPdfPagePlan
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.types import (
    FallbackSummary,
    RenderedDocumentSummary,
    RenderInputs,
    RenderResult,
)


@dataclass(frozen=True)
class DirectPdfDocumentPlan:
    """Measured pages and content layouts for any direct-PDF document."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    document_summary: RenderedDocumentSummary
    fallback_summary: FallbackSummary | None = None


DocumentPlanBuilder = Callable[[PdfSurface, RenderInputs], DirectPdfDocumentPlan]


def build_document_surface(
    inputs: RenderInputs, *, creation_date: datetime | None = None
) -> FpdfSurface:
    """Prepare the configured page geometry and bundled fonts for document planning."""

    page = resolve_page_geometry(inputs)
    surface = FpdfSurface(page_width_mm=page.width_mm, page_height_mm=page.height_mm)
    if creation_date is not None:
        surface.set_creation_date(creation_date)
    packaged_direct_pdf_assets().register_fonts(surface)
    return surface


def render_document_plan(
    inputs: RenderInputs,
    *,
    style_name: str,
    builder: DocumentPlanBuilder,
    creation_date: datetime | None = None,
) -> RenderResult:
    """Measure, diagnose, paint, and write one document through a common runner."""

    surface = build_document_surface(inputs, creation_date=creation_date)

    plan = builder(surface, inputs)
    layout_report = build_direct_layout_report(plan.page_plans)
    write_direct_layout_debug_json(
        inputs=inputs,
        page_plans=plan.page_plans,
        style_name=style_name,
        layout_report=layout_report,
    )

    for page_plan in plan.page_plans:
        page_plan.paint(surface)
    surface.output(inputs.output_path)
    return RenderResult(
        fallback_summary=plan.fallback_summary,
        document_summary=plan.document_summary,
        layout_report=layout_report,
    )


def explicit_creation_date(inputs: RenderInputs) -> datetime | None:
    """Resolve explicit render timestamps for deterministic PDF metadata."""

    value = inputs.context.get("created_timestamp_utc")
    if value is None:
        value = inputs.context.get("created_date")
    if isinstance(value, datetime):
        resolved = value
    elif isinstance(value, date):
        resolved = datetime.combine(value, time.min, tzinfo=timezone.utc)
    elif isinstance(value, str):
        normalized = value.strip()
        resolved = None
        for pattern in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d"):
            try:
                resolved = datetime.strptime(normalized, pattern).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        if resolved is None:
            return None
    else:
        return None
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


__all__ = [
    "DirectPdfDocumentPlan",
    "DocumentPlanBuilder",
    "build_document_surface",
    "explicit_creation_date",
    "render_document_plan",
]
