"""Measure and draw labeled recovery fields in a bordered box."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.render.direct_pdf.components import Panel, TextBox
from ethernity.render.direct_pdf.metadata import RecoveryField
from ethernity.render.direct_pdf.page import PaintPlan
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy, fit_text_to_width
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle


@dataclass(frozen=True)
class MetadataBoxStyle:
    label: TextStyle
    value: TextStyle
    guidance: TextStyle
    border: PdfColor
    fill: PdfColor
    label_height_mm: float
    box_offset_mm: float
    minimum_height_mm: float
    horizontal_padding_mm: float
    measurement_padding_mm: float
    value_bottom_inset_mm: float = 0.0
    label_right_inset_mm: float = 0.0
    line_width_mm: float = 0.2
    value_line_height: float = 1.2
    value_top_inset_mm: float = 2.0
    row_gap_mm: float = 3.0


@dataclass(frozen=True)
class MeasuredMetadataBox:
    field: RecoveryField
    box_height_mm: float
    guidance_height_mm: float

    def advance_mm(self, style: MetadataBoxStyle) -> float:
        return style.box_offset_mm + self.box_height_mm + style.row_gap_mm


def measure_metadata_box(
    surface: PdfSurface, field: RecoveryField, *, width_mm: float, style: MetadataBoxStyle
) -> MeasuredMetadataBox:
    value_width = width_mm - 2 * style.horizontal_padding_mm
    if value_width <= 0:
        raise ValueError("Recovery metadata width must be positive")
    fit = fit_text_to_width(
        surface,
        "\n".join(field.value_lines),
        style.value,
        max_width_mm=value_width,
        policy=TextFitPolicy.WRAP,
        line_height_multiplier=style.value_line_height,
    )
    guidance_height = 0.0
    if field.guidance:
        guidance_height = (
            fit_text_to_width(
                surface,
                field.guidance,
                style.guidance,
                max_width_mm=value_width,
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.15,
            ).height_mm
            + 1.0
        )
    return MeasuredMetadataBox(
        field,
        max(
            style.minimum_height_mm, style.measurement_padding_mm + guidance_height + fit.height_mm
        ),
        guidance_height,
    )


def metadata_box_plans(
    surface: PdfSurface,
    row: MeasuredMetadataBox,
    *,
    prefix: str,
    index: int,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    style: MetadataBoxStyle,
) -> tuple[list[PaintPlan], float]:
    field = row.field
    box_y = y_mm + style.box_offset_mm
    value_x = x_mm + style.horizontal_padding_mm
    value_width = width_mm - 2 * style.horizontal_padding_mm
    value_y = box_y + style.value_top_inset_mm
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-metadata-label-{index}",
            text=field.label.upper(),
            style=style.label,
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(x_mm, y_mm, width_mm - style.label_right_inset_mm, style.label_height_mm),
        ),
        Panel(
            component_id=f"{prefix}-metadata-box-{index}",
            stroke=style.border,
            fill=style.fill,
            line_width_mm=style.line_width_mm,
        ).plan(surface, PdfRect(x_mm, box_y, width_mm, row.box_height_mm)),
    ]
    if field.guidance:
        plans.append(
            TextBox(
                component_id=f"{prefix}-metadata-guidance-{index}",
                text=field.guidance,
                style=style.guidance,
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.15,
            ).plan(surface, PdfRect(value_x, value_y, value_width, row.guidance_height_mm - 1.0))
        )
        value_y += row.guidance_height_mm
    plans.append(
        TextBox(
            component_id=f"{prefix}-metadata-value-{index}",
            text="\n".join(field.value_lines),
            text_metadata=field.text_metadata,
            style=style.value,
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=style.value_line_height,
        ).plan(
            surface,
            PdfRect(
                value_x,
                value_y,
                value_width,
                box_y + row.box_height_mm - value_y - style.value_bottom_inset_mm,
            ),
        )
    )
    return plans, y_mm + row.advance_mm(style)
