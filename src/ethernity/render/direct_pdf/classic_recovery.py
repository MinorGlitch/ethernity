"""Passphrase continuation pages for the classic PDF designs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.render.direct_pdf.classic_layout import (
    ClassicLayout,
    build_classic_body_zone_constraints,
    build_page_background,
)
from ethernity.render.direct_pdf.components import Panel, TextBox
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.recovery_metadata import RecoveryPassphraseContinuationPage
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.types import RenderTextMetadata


@dataclass(frozen=True)
class ClassicPassphrasePageStyle:
    """Design-owned colors, typography, and value-line spacing."""

    background: PdfColor
    panel_fill: PdfColor
    panel_stroke: PdfColor
    title: TextStyle
    instructions: TextStyle
    value: TextStyle
    line_height_multiplier: float


@dataclass(frozen=True)
class ClassicPassphrasePageGeometry:
    """Design-owned rectangles below the measured local header."""

    title: PdfRect
    instructions: PdfRect
    value: PdfRect


def build_classic_passphrase_continuation_page(
    surface: PdfSurface,
    *,
    prefix: str,
    layout: ClassicLayout,
    page_number: int,
    continuation_page: RecoveryPassphraseContinuationPage,
    header_plans: Sequence[PaintPlan],
    geometry: ClassicPassphrasePageGeometry,
    style: ClassicPassphrasePageStyle,
    renderer_label: str,
) -> DirectPdfPagePlan:
    """Build the shared continuation structure using a design's measured header and style."""

    value = geometry.value
    content_plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-passphrase-continuation-title",
            text=(
                "PASSPHRASE CONTINUATION "
                f"{continuation_page.page_index} / {continuation_page.total_pages}"
            ),
            style=style.title,
            policy=TextFitPolicy.FAIL,
        ).plan(surface, geometry.title),
        TextBox(
            component_id=f"{prefix}-passphrase-continuation-instructions",
            text=continuation_page.instructions,
            style=style.instructions,
            policy=TextFitPolicy.WRAP,
        ).plan(surface, geometry.instructions),
        Panel(
            component_id=f"{prefix}-passphrase-continuation-panel",
            stroke=style.panel_stroke,
            fill=style.panel_fill,
            line_width_mm=0.3,
        ).plan(
            surface,
            PdfRect(
                value.x_mm - 2.0, value.y_mm - 2.0, value.width_mm + 4.0, value.height_mm + 4.0
            ),
        ),
        TextBox(
            component_id=f"{prefix}-passphrase-continuation-value",
            text=continuation_page.text,
            text_metadata=RenderTextMetadata(
                "recovery_passphrase",
                print_mode=continuation_page.print_mode,
                continuation_index=continuation_page.page_index,
            ),
            style=style.value,
            policy=TextFitPolicy.FAIL,
            line_height_multiplier=style.line_height_multiplier,
        ).plan(surface, value),
    ]
    return build_page_plan(
        page_number=page_number,
        rect=layout.page.rect,
        plans=[
            *build_page_background(surface, layout=layout, prefix=prefix, fill=style.background),
            *header_plans,
            *content_plans,
        ],
        separation_constraints=build_classic_body_zone_constraints(
            prefix=prefix,
            header_plans=header_plans,
            content_plans=content_plans,
            layout=layout,
            renderer_label=renderer_label,
        ),
    )


__all__ = [
    "ClassicPassphrasePageGeometry",
    "ClassicPassphrasePageStyle",
    "build_classic_passphrase_continuation_page",
]
