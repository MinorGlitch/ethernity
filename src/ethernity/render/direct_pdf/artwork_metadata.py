"""Shared measured field stacks and header columns for recovery documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from ethernity.render.direct_pdf.artwork import Artwork, color, text_style
from ethernity.render.direct_pdf.components import Panel, TextAlign, TextBox
from ethernity.render.direct_pdf.metadata import RecoveryFields
from ethernity.render.direct_pdf.metadata_box import (
    MetadataBoxStyle,
    measure_metadata_box,
    metadata_box_plans,
)
from ethernity.render.direct_pdf.page import PaintPlan
from ethernity.render.direct_pdf.text_fit import TextFitPolicy, fit_text_to_width
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.template import HeaderField, MetadataArtwork
from ethernity.render.types import RenderTextMetadata


@dataclass(frozen=True)
class MetadataLayout:
    """Measured paint plans and vertical displacement in template coordinates."""

    plans: tuple[PaintPlan, ...]
    shift_y: float


@dataclass(frozen=True)
class _FieldContent:
    label: str
    value: str
    guidance: str
    text_metadata: RenderTextMetadata | None


@dataclass(frozen=True)
class _MeasuredField:
    """Resolved field content, styles and page rectangles, all in millimetres."""

    field: HeaderField
    content: _FieldContent
    bounds: PdfRect
    label_rect: PdfRect | None
    guidance_rect: PdfRect | None
    value_rect: PdfRect
    label_style: TextStyle
    guidance_style: TextStyle
    value_style: TextStyle


def metadata_plans(
    painter: Artwork,
    spec: MetadataArtwork,
    fields: RecoveryFields,
    values: Mapping[str, str | int],
    prefix: str,
) -> MetadataLayout:
    _, sy = painter.scale
    y = spec.box[1]
    result: list[PaintPlan] = []
    if spec.flow == "boxes":
        return _boxed_fields(painter, spec, fields, prefix)
    cursor = y * sy
    max_bottom = cursor
    column_bottom: dict[float, float] = {}
    for index, field in enumerate(spec.fields):
        content = _field_content(field, fields, values)
        if content is None:
            continue
        top = cursor if spec.flow == "stack" else max(field.y * sy, column_bottom.get(field.x, 0))
        measured = _measure_field(painter, spec, field, content, top)
        result.extend(_field_plans(painter, measured, f"{prefix}-meta", index))
        height = measured.bounds.height_mm
        max_bottom = max(max_bottom, top + height)
        cursor = top + height + spec.gap
        column_bottom[field.x] = cursor
    bottom = max(max_bottom, spec.minimum_bottom * sy)
    return MetadataLayout(tuple(result), (bottom - spec.reference_bottom * sy) / sy)


def _boxed_fields(
    painter: Artwork, spec: MetadataArtwork, fields: RecoveryFields, prefix: str
) -> MetadataLayout:
    sx, sy = painter.scale
    x, y, width, _ = spec.box
    result: list[PaintPlan] = []
    style = MetadataBoxStyle(
        text_style(painter.definition, spec.label_style),
        text_style(painter.definition, spec.value_style),
        text_style(painter.definition, spec.guidance_style),
        color(spec.border),
        color(spec.fill),
        spec.label_height,
        spec.box_offset,
        spec.minimum_height,
        spec.padding,
        spec.measurement_padding,
        value_bottom_inset_mm=spec.bottom_inset,
        label_right_inset_mm=spec.label_right_inset,
        line_width_mm=spec.line_width,
        value_line_height=spec.line_height,
        row_gap_mm=spec.gap,
    )
    rows = [
        measure_metadata_box(painter.surface, field, width_mm=width * sx, style=style)
        for field in fields.visible_rows()
        if not (spec.quorum_in_header and field is fields.quorum)
    ]
    height = sum(row.advance_mm(style) for row in rows)
    start = spec.reference_bottom * sy - height if spec.bottom_anchor else y * sy
    cursor = start
    for i, row in enumerate(rows):
        plans, cursor = metadata_box_plans(
            painter.surface,
            row,
            prefix=prefix,
            index=i,
            x_mm=x * sx,
            y_mm=cursor,
            width_mm=width * sx,
            style=style,
        )
        result.extend(plans)
    delta = (start - y * sy) / sy if spec.bottom_anchor else 0
    return MetadataLayout(tuple(result), delta)


def _measure_field(
    painter: Artwork,
    spec: MetadataArtwork,
    field: HeaderField,
    content: _FieldContent,
    top_mm: float,
) -> _MeasuredField:
    sx, _ = painter.scale
    value_style = text_style(painter.definition, field.value_style)
    label_style = text_style(painter.definition, field.label_style)
    guidance_style = text_style(painter.definition, spec.guidance_style)
    width_mm = field.width * sx
    value_width_mm = width_mm - 2 * field.padding
    if field.placement == "beside":
        value_width_mm -= field.label_width + field.label_gap
    fit = fit_text_to_width(
        painter.surface,
        content.value,
        value_style,
        max_width_mm=value_width_mm,
        policy=TextFitPolicy.WRAP,
        line_height_multiplier=field.line_height,
    )
    label_height_mm = field.label_height
    if field.placement == "above" and label_height_mm == 0:
        label_height_mm = max(
            painter.surface.line_height(label_style, multiplier=1),
            painter.surface.text_ink_metrics(content.label, label_style).height_mm,
        )
    guidance_height_mm = 0
    if content.guidance:
        guidance_height_mm = (
            fit_text_to_width(
                painter.surface,
                content.guidance,
                guidance_style,
                max_width_mm=value_width_mm,
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.1,
            ).height_mm
            + 1
        )
    value_offset_mm = field.top_padding + (
        label_height_mm + field.label_gap if field.placement == "above" else 0
    )
    height_mm = max(
        field.minimum_height,
        value_offset_mm + guidance_height_mm + fit.height_mm + field.bottom_padding,
    )
    left_mm = field.x * sx
    label_rect = None
    if field.placement in ("above", "beside"):
        label_rect = PdfRect(
            left_mm + field.padding,
            top_mm + field.top_padding,
            field.label_width if field.placement == "beside" else value_width_mm,
            label_height_mm if label_height_mm else max(3.1, height_mm),
        )
    value_x_mm = (
        left_mm
        + field.padding
        + (field.label_width + field.label_gap if field.placement == "beside" else 0)
    )
    value_y_mm = top_mm + value_offset_mm
    guidance_rect = None
    if content.guidance:
        guidance_rect = PdfRect(value_x_mm, value_y_mm, value_width_mm, guidance_height_mm - 1)
        value_y_mm += guidance_height_mm
    return _MeasuredField(
        field=field,
        content=content,
        bounds=PdfRect(left_mm, top_mm, width_mm, height_mm),
        label_rect=label_rect,
        guidance_rect=guidance_rect,
        value_rect=PdfRect(
            value_x_mm, value_y_mm, value_width_mm, height_mm - (value_y_mm - top_mm)
        ),
        label_style=label_style,
        guidance_style=guidance_style,
        value_style=value_style,
    )


def _field_plans(
    painter: Artwork, measured: _MeasuredField, prefix: str, index: int
) -> list[PaintPlan]:
    field, content = measured.field, measured.content
    result: list[PaintPlan] = []
    if field.stroke or field.fill:
        result.append(
            Panel(
                f"{prefix}-box-{index}",
                color(field.stroke),
                color(field.fill),
                field.line_width,
            ).plan(painter.surface, measured.bounds)
        )
    if measured.label_rect is not None:
        result.append(
            TextBox(
                f"{prefix}-label-{index}",
                content.label,
                measured.label_style,
                policy=TextFitPolicy.SHRINK,
                min_size_pt=6,
                align=TextAlign(field.align),
                line_height_multiplier=field.label_line_height,
            ).plan(painter.surface, measured.label_rect)
        )
    if measured.guidance_rect is not None:
        result.append(
            TextBox(
                f"{prefix}-guidance-{index}",
                content.guidance,
                measured.guidance_style,
                policy=TextFitPolicy.WRAP,
                align=TextAlign(field.align),
                line_height_multiplier=1.1,
            ).plan(painter.surface, measured.guidance_rect)
        )
    result.append(
        TextBox(
            f"{prefix}-value-{index}",
            content.value,
            measured.value_style,
            policy=TextFitPolicy.WRAP,
            align=TextAlign(field.align),
            line_height_multiplier=field.line_height,
            text_metadata=content.text_metadata,
        ).plan(painter.surface, measured.value_rect)
    )
    return result


def _field_content(
    field: HeaderField, fields: RecoveryFields, values: Mapping[str, str | int]
) -> _FieldContent | None:
    recovery = {
        "passphrase": fields.passphrase,
        "quorum": fields.quorum,
        "signing_public_key": fields.signing_key,
    }.get(field.name)
    guidance = ""
    text_meta = None
    if recovery:
        if not recovery.visible:
            return None
        label = (
            recovery.label if field.name != "signing_public_key" else field.label.format_map(values)
        )
        text = "\n".join(recovery.value_lines)
        if field.name != "passphrase" and field.placement in ("prefix", "beside"):
            text = " ".join(recovery.value_lines)
        guidance = recovery.guidance
        text_meta = recovery.text_metadata
    else:
        text = str(values[field.name])
        label = field.label.format_map(values)
        if field.placement == "value":
            text = text.upper()
    if field.placement == "prefix":
        value_prefix = label + ": "
        text = value_prefix + text
        if text_meta:
            text_meta = replace(text_meta, value_prefix=value_prefix)
    if field.uppercase:
        label = label.upper()
    return _FieldContent(label, text, guidance, text_meta)
