"""Shared Sentinel direct-PDF shell helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone

from ethernity.render.copy_catalog import build_copy_bundle, build_instruction_copy
from ethernity.render.direct_pdf.components import (
    BoxPlacementProof,
    EllipsePlan,
    ImageBoxPlan,
    LinePlan,
    Panel,
    PanelPlan,
    Rule,
    RulePlan,
    TextAlign,
    TextBox,
    TextBoxPlan,
    TextLinePlacement,
    TextPlacementProof,
)
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    DirectPdfPagePlan,
    LayoutRegion,
    PaintPlan,
    SeparationConstraint,
    build_page_plan,
)
from ethernity.render.direct_pdf.page_geometry import PageGeometry, resolve_page_geometry
from ethernity.render.direct_pdf.responsive_layout import Insets, PageRegions, resolve_page_regions
from ethernity.render.direct_pdf.sentinel.theme import SENTINEL_THEME
from ethernity.render.direct_pdf.structured_common import (
    component_prefix,
    generator_label,
    lineage_payload,
    resolve_doc_id,
    timestamp_from_string,
)
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitError, TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect
from ethernity.render.template_style import TemplateCapabilities, load_template_style
from ethernity.render.types import RenderInputs, RenderLineage
from ethernity.version import get_ethernity_version

SENTINEL_PAGE_RECT = PdfRect(
    0.0,
    0.0,
    SENTINEL_THEME.layout.page_width_mm,
    SENTINEL_THEME.layout.page_height_mm,
)
SENTINEL_CONTENT_X_MM = SENTINEL_THEME.layout.content_x_mm
SENTINEL_CONTENT_WIDTH_MM = SENTINEL_THEME.layout.content_width_mm
SENTINEL_ORANGE = SENTINEL_THEME.palette.primary
SENTINEL_BACKGROUND = SENTINEL_THEME.palette.background
SENTINEL_BORDER = SENTINEL_THEME.palette.border
SENTINEL_TEXT = SENTINEL_THEME.palette.text_main
SENTINEL_MUTED = SENTINEL_THEME.palette.text_secondary
SENTINEL_BLACK = SENTINEL_THEME.palette.black
SENTINEL_WHITE = SENTINEL_THEME.palette.white
SENTINEL_WARNING_FILL = SENTINEL_THEME.palette.warning_fill
SENTINEL_LINE_FILL = SENTINEL_THEME.palette.line_fill
SENTINEL_GRID_LINE = SENTINEL_THEME.palette.grid_line

_CONTENT_REFLOW_TOP_MM = 28.0
_FOOTER_BOTTOM_OFFSET_MM = SENTINEL_THEME.layout.page_height_mm - (
    SENTINEL_THEME.layout.footer_rule_y_mm
)
_MIN_PAGE_WIDTH_MM = 200.0
_MIN_CONTENT_REFLOW_RATIO = 0.9
_BODY_FOOTER_CLEARANCE_MM = 1.0
_QR_FOOTER_CLEARANCE_MM = 2.0
_QR_CAPTION_CLEARANCE_MM = 2.0
_CORNER_MARK_SUFFIXES = (
    "corner-top-left-x",
    "corner-top-left-y",
    "corner-top-right-x",
    "corner-top-right-y",
    "corner-bottom-left-x",
    "corner-bottom-left-y",
    "corner-bottom-right-x",
    "corner-bottom-right-y",
)


@dataclass(frozen=True)
class SentinelPageLayout:
    """Dimension-driven Sentinel safe area and canonical-design reflow anchors."""

    geometry: PageGeometry
    horizontal_offset_mm: float
    footer_rule_y_mm: float
    content_reflow_ratio: float
    regions: PageRegions
    safe_rect: PdfRect

    @property
    def page_rect(self) -> PdfRect:
        return self.geometry.rect

    def map_x(self, value_mm: float) -> float:
        """Center a canonical Sentinel x coordinate on the configured page."""

        return value_mm + self.horizontal_offset_mm

    def reference_x(self, value_mm: float) -> float:
        """Convert a measured page x coordinate to the Sentinel reference space."""

        return value_mm - self.horizontal_offset_mm

    def map_y(self, value_mm: float) -> float:
        """Reflow vertical whitespace while keeping header and footer anchored."""

        base_footer_y = SENTINEL_THEME.layout.footer_rule_y_mm
        if value_mm <= _CONTENT_REFLOW_TOP_MM:
            return value_mm
        if value_mm >= base_footer_y:
            return value_mm + (self.geometry.height_mm - SENTINEL_THEME.layout.page_height_mm)
        return _CONTENT_REFLOW_TOP_MM + (
            (value_mm - _CONTENT_REFLOW_TOP_MM) * self.content_reflow_ratio
        )

    def reference_y(self, value_mm: float) -> float:
        """Convert a measured page y coordinate to the Sentinel reference space."""

        if value_mm <= _CONTENT_REFLOW_TOP_MM:
            return value_mm
        if value_mm >= self.footer_rule_y_mm:
            return value_mm - (self.geometry.height_mm - SENTINEL_THEME.layout.page_height_mm)
        return _CONTENT_REFLOW_TOP_MM + (
            (value_mm - _CONTENT_REFLOW_TOP_MM) / self.content_reflow_ratio
        )

    def map_rect(self, rect: PdfRect, *, preserve_height: bool = False) -> PdfRect:
        """Map a reference rectangle into the page safe area."""

        if _spans_reference_page_width(rect):
            x_mm = 0.0
            width_mm = self.geometry.width_mm
        else:
            x_mm = self.map_x(rect.x_mm)
            width_mm = rect.width_mm
        y_mm = self.map_y(rect.y_mm)
        if preserve_height:
            height_mm = rect.height_mm
        else:
            height_mm = max(0.0, self.map_y(rect.bottom_mm) - y_mm)
        return PdfRect(x_mm, y_mm, width_mm, height_mm)

    def reference_rect(self, rect: PdfRect) -> PdfRect:
        """Convert a measured page rectangle to canonical planning coordinates."""

        y_mm = self.reference_y(rect.y_mm)
        return PdfRect(
            self.reference_x(rect.x_mm),
            y_mm,
            rect.width_mm,
            self.reference_y(rect.bottom_mm) - y_mm,
        )


@dataclass(frozen=True)
class SentinelQrCompound:
    """QR frame, image, markers, and optional caption reflowed as one rigid unit."""

    anchor_component_id: str
    member_component_ids: tuple[str, ...]
    image_component_id: str
    marker_component_ids: tuple[str, ...]
    minimum_marker_clearance_mm: float
    caption_component_id: str | None = None
    minimum_caption_clearance_mm: float = _QR_CAPTION_CLEARANCE_MM

    def __post_init__(self) -> None:
        identifiers = (
            self.anchor_component_id,
            self.image_component_id,
            *self.member_component_ids,
            *self.marker_component_ids,
        )
        if self.caption_component_id is not None:
            identifiers = (*identifiers, self.caption_component_id)
        if any(not identifier.strip() for identifier in identifiers):
            raise ValueError("Sentinel QR compound component ids must be non-empty")
        if len(set(self.member_component_ids)) != len(self.member_component_ids):
            raise ValueError("Sentinel QR compound member ids must be unique")
        member_ids = set(self.member_component_ids)
        required_ids = {
            self.anchor_component_id,
            self.image_component_id,
            *self.marker_component_ids,
        }
        if self.caption_component_id is not None:
            required_ids.add(self.caption_component_id)
        if not required_ids.issubset(member_ids):
            raise ValueError("Sentinel QR compound members must include all semantic components")
        for field_name, value in (
            ("minimum_marker_clearance_mm", self.minimum_marker_clearance_mm),
            ("minimum_caption_clearance_mm", self.minimum_caption_clearance_mm),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field_name} must be finite and non-negative")


def build_sentinel_page_layout(inputs: RenderInputs) -> SentinelPageLayout:
    """Resolve and validate the responsive page geometry for Sentinel output."""

    geometry = resolve_page_geometry(inputs)
    base_layout = SENTINEL_THEME.layout
    if geometry.width_mm < _MIN_PAGE_WIDTH_MM:
        raise ValueError(
            f"direct Sentinel renderer requires page width >= {_MIN_PAGE_WIDTH_MM:.1f} mm"
        )
    horizontal_offset = (geometry.width_mm - base_layout.page_width_mm) / 2.0
    safe_side_inset = (geometry.width_mm - base_layout.content_width_mm) / 2.0
    regions = resolve_page_regions(
        geometry.rect,
        safe_insets=Insets(
            top_mm=0.0,
            right_mm=safe_side_inset,
            bottom_mm=0.0,
            left_mm=safe_side_inset,
        ),
        header_height_mm=_CONTENT_REFLOW_TOP_MM,
        footer_height_mm=_FOOTER_BOTTOM_OFFSET_MM,
    )
    footer_rule_y = regions.footer.y_mm
    content_reflow_ratio = (footer_rule_y - _CONTENT_REFLOW_TOP_MM) / (
        base_layout.footer_rule_y_mm - _CONTENT_REFLOW_TOP_MM
    )
    if content_reflow_ratio < _MIN_CONTENT_REFLOW_RATIO:
        raise ValueError(
            "direct Sentinel renderer requires enough page height to preserve readable text "
            "and QR dimensions"
        )
    return SentinelPageLayout(
        geometry=geometry,
        horizontal_offset_mm=horizontal_offset,
        footer_rule_y_mm=footer_rule_y,
        content_reflow_ratio=content_reflow_ratio,
        regions=regions,
        safe_rect=regions.body,
    )


def build_sentinel_surface(inputs: RenderInputs | None = None) -> FpdfSurface:
    """Create a PDF surface with Sentinel's page geometry."""

    if inputs is None:
        width_mm = SENTINEL_THEME.layout.page_width_mm
        height_mm = SENTINEL_THEME.layout.page_height_mm
    else:
        geometry = resolve_page_geometry(inputs)
        width_mm = geometry.width_mm
        height_mm = geometry.height_mm
    return FpdfSurface(
        page_width_mm=width_mm,
        page_height_mm=height_mm,
    )


@dataclass(frozen=True)
class SentinelShellContext:
    """Shared copy and metadata used by Sentinel direct-PDF document shells."""

    doc_type: str
    doc_id: str
    created_timestamp_utc: str
    created_date: str
    copy: dict[str, object]
    instructions_label: str
    instruction_lines: tuple[str, ...]
    footer_left: str
    footer_right: str
    lineage: RenderLineage
    values: dict[str, object]
    page_layout: SentinelPageLayout
    capabilities: TemplateCapabilities


def build_sentinel_shell_context(
    inputs: RenderInputs,
    *,
    doc_type: str,
) -> SentinelShellContext:
    """Build Sentinel shell context from existing render inputs and copy catalogs."""

    base_context = dict(inputs.context)
    created_timestamp_utc = resolve_created_timestamp(base_context)
    created_date = str(base_context.get("created_date") or "")
    doc_id = resolve_doc_id(inputs, base_context)
    base_context["doc_id"] = doc_id
    base_context["lineage"] = lineage_payload(inputs.lineage)

    page_layout = build_sentinel_page_layout(inputs)
    base_context["paper_size"] = page_layout.geometry.paper_size
    copy = build_copy_bundle(doc_type=doc_type, context=base_context)
    instructions = build_instruction_copy(doc_type=doc_type, context=base_context)
    return SentinelShellContext(
        doc_type=doc_type,
        doc_id=doc_id,
        created_timestamp_utc=created_timestamp_utc,
        created_date=created_date,
        copy=copy,
        instructions_label=instructions.label,
        instruction_lines=instructions.lines,
        footer_left=generator_label(get_ethernity_version()),
        footer_right=str(copy.get("footer_guidance") or ""),
        lineage=inputs.lineage,
        values=base_context,
        page_layout=page_layout,
        capabilities=load_template_style(inputs.design_name).capabilities,
    )


def build_sentinel_page_plan(
    *,
    page_number: int,
    page_layout: SentinelPageLayout,
    plans: list[PaintPlan],
    qr_compounds: Sequence[SentinelQrCompound] = (),
    physical_component_ids: Sequence[str] = (),
) -> DirectPdfPagePlan:
    """Reflow canonical Sentinel placements and build a geometry-checked page."""

    reference_plans = tuple(plans)
    compounds = tuple(qr_compounds)
    physical_ids = tuple(physical_component_ids)
    if len(set(physical_ids)) != len(physical_ids):
        raise ValueError("Sentinel physical component ids must be unique")
    plan_ids = {plan.component_id for plan in reference_plans}
    missing_physical_ids = set(physical_ids).difference(plan_ids)
    if missing_physical_ids:
        raise ValueError(
            "Sentinel physical component references missing plan: "
            f"{sorted(missing_physical_ids)[0]}"
        )
    physical_id_set = set(physical_ids)
    responsive_plans = _anchor_qr_compounds(
        reference_plans,
        tuple(
            plan if plan.component_id in physical_id_set else _reflow_paint_plan(plan, page_layout)
            for plan in reference_plans
        ),
        compounds,
    )
    return build_page_plan(
        page_number=page_number,
        rect=page_layout.page_rect,
        plans=responsive_plans,
        separation_constraints=(
            *_footer_separation_constraints(
                responsive_plans,
                page_layout,
                page_number=page_number,
            ),
            *_qr_compound_separation_constraints(compounds, page_number=page_number),
        ),
    )


def build_sentinel_header_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    page_label: str,
    page_number: int,
    component_base: str,
    top_strip_text: str = "Emergency Recovery Material // Keep Offline // Never Photograph",
    title_default: str = "Document",
    subtitle_default: str = "",
) -> list[PaintPlan]:
    """Build measured Sentinel header plans for a direct-PDF page."""

    prefix = component_prefix(component_base, page_number)
    layout = SENTINEL_THEME.layout
    text = SENTINEL_THEME.text
    title = str(context.copy.get("title") or title_default).upper()
    subtitle = str(context.copy.get("subtitle") or subtitle_default).upper()
    title_box = TextBox(
        component_id=f"{prefix}-header-title",
        text=title,
        style=SENTINEL_THEME.sans_style(
            size_pt=text.header_title_pt,
            bold=True,
            color=SENTINEL_BLACK,
        ),
        policy=TextFitPolicy.SHRINK,
        min_size_pt=text.header_title_min_pt,
        line_height_multiplier=1.0,
    )
    title_rect = PdfRect(15.0, 11.0, 122.0, 9.0)
    try:
        title_plan = title_box.plan(surface, title_rect)
        subtitle_rect = PdfRect(15.0, 22.0, 115.0, 5.0)
    except TextFitError:
        title_plan = TextBox(
            component_id=f"{prefix}-header-title",
            text=title,
            style=SENTINEL_THEME.sans_style(
                size_pt=text.header_title_wrapped_pt,
                bold=True,
                color=SENTINEL_BLACK,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=text.header_title_wrapped_min_pt,
            line_height_multiplier=1.0,
        ).plan(surface, PdfRect(15.0, 10.7, 122.0, 11.2))
        subtitle_rect = PdfRect(15.0, 23.0, 115.0, 4.0)
    return [
        Panel(
            component_id=f"{prefix}-top-strip",
            stroke=None,
            fill=SENTINEL_ORANGE,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(0.0, 0.0, layout.page_width_mm, layout.top_strip_height_mm)),
        TextBox(
            component_id=f"{prefix}-top-strip-text",
            text=top_strip_text.upper(),
            style=SENTINEL_THEME.sans_style(
                size_pt=text.top_strip_pt,
                bold=True,
                color=SENTINEL_BLACK,
                char_spacing_mm=0.25,
            ),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=text.top_strip_min_pt,
        ).plan(surface, PdfRect(15.0, 2.2, 180.0, 3.8)),
        Rule(
            component_id=f"{prefix}-top-strip-rule",
            color=SENTINEL_BLACK,
        ).plan(
            surface,
            PdfRect(
                0.0,
                layout.top_strip_height_mm,
                layout.page_width_mm,
                layout.top_strip_rule_height_mm,
            ),
        ),
        title_plan,
        TextBox(
            component_id=f"{prefix}-header-subtitle",
            text=subtitle,
            style=SENTINEL_THEME.sans_style(
                size_pt=text.header_subtitle_pt,
                color=SENTINEL_MUTED,
                char_spacing_mm=0.26,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=text.header_subtitle_min_pt,
        ).plan(surface, subtitle_rect),
        TextBox(
            component_id=f"{prefix}-header-doc-id",
            text=f"DOC ID: {context.doc_id}",
            style=SENTINEL_THEME.mono_style(size_pt=text.header_meta_pt, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=text.header_meta_min_pt,
        ).plan(surface, PdfRect(136.0, 15.1, 59.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-header-generated",
            text=f"GENERATED (UTC): {context.created_timestamp_utc}",
            style=SENTINEL_THEME.mono_style(size_pt=text.header_meta_pt, color=SENTINEL_TEXT),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=text.header_meta_min_pt,
        ).plan(surface, PdfRect(124.0, 19.2, 71.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-header-page-label",
            text=page_label,
            style=SENTINEL_THEME.mono_style(size_pt=text.header_meta_pt, color=SENTINEL_TEXT),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(154.0, 23.3, 41.0, 4.0)),
        Rule(
            component_id=f"{prefix}-header-rule",
            color=SENTINEL_BLACK,
        ).plan(
            surface,
            PdfRect(
                0.0,
                layout.header_rule_y_mm,
                layout.page_width_mm,
                layout.header_rule_height_mm,
            ),
        ),
    ]


def build_sentinel_footer_plans(
    surface: PdfSurface,
    context: SentinelShellContext,
    *,
    page_label: str,
    page_number: int,
    component_base: str,
) -> list[PaintPlan]:
    """Build measured Sentinel footer plans for a direct-PDF page."""

    prefix = component_prefix(component_base, page_number)
    layout = SENTINEL_THEME.layout
    text = SENTINEL_THEME.text
    mono_style = SENTINEL_THEME.mono_style(size_pt=text.footer_pt, color=SENTINEL_TEXT)
    return [
        Rule(
            component_id=f"{prefix}-footer-rule",
            color=SENTINEL_BLACK,
        ).plan(
            surface,
            PdfRect(
                0.0,
                layout.footer_rule_y_mm,
                layout.page_width_mm,
                layout.footer_rule_height_mm,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-footer-left",
            text=context.footer_left.upper(),
            style=mono_style,
            policy=TextFitPolicy.SHRINK,
            min_size_pt=text.footer_min_pt,
        ).plan(surface, PdfRect(15.0, 290.0, 60.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-footer-page",
            text=page_label.upper(),
            style=mono_style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(81.0, 290.0, 48.0, 4.5)),
        TextBox(
            component_id=f"{prefix}-footer-right",
            text=context.footer_right.upper(),
            style=mono_style,
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(132.0, 288.5, 63.0, 8.0)),
    ]


def build_sentinel_corner_mark_plans(
    surface: PdfSurface,
    *,
    component_prefix: str,
    marker_name: str,
    rect: PdfRect,
    color: PdfColor,
    length_mm: float,
    width_mm: float,
) -> list[PaintPlan]:
    """Build L-shaped corner marker rules around a rectangle."""

    return [
        Rule(
            component_id=f"{component_prefix}-{marker_name}-corner-top-left-x",
            color=color,
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, length_mm, width_mm)),
        Rule(
            component_id=f"{component_prefix}-{marker_name}-corner-top-left-y",
            color=color,
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, width_mm, length_mm)),
        Rule(
            component_id=f"{component_prefix}-{marker_name}-corner-top-right-x",
            color=color,
        ).plan(surface, PdfRect(rect.right_mm - length_mm, rect.y_mm, length_mm, width_mm)),
        Rule(
            component_id=f"{component_prefix}-{marker_name}-corner-top-right-y",
            color=color,
        ).plan(surface, PdfRect(rect.right_mm - width_mm, rect.y_mm, width_mm, length_mm)),
        Rule(
            component_id=f"{component_prefix}-{marker_name}-corner-bottom-left-x",
            color=color,
        ).plan(surface, PdfRect(rect.x_mm, rect.bottom_mm - width_mm, length_mm, width_mm)),
        Rule(
            component_id=f"{component_prefix}-{marker_name}-corner-bottom-left-y",
            color=color,
        ).plan(surface, PdfRect(rect.x_mm, rect.bottom_mm - length_mm, width_mm, length_mm)),
        Rule(
            component_id=f"{component_prefix}-{marker_name}-corner-bottom-right-x",
            color=color,
        ).plan(
            surface,
            PdfRect(rect.right_mm - length_mm, rect.bottom_mm - width_mm, length_mm, width_mm),
        ),
        Rule(
            component_id=f"{component_prefix}-{marker_name}-corner-bottom-right-y",
            color=color,
        ).plan(
            surface,
            PdfRect(rect.right_mm - width_mm, rect.bottom_mm - length_mm, width_mm, length_mm),
        ),
    ]


def sentinel_corner_mark_component_ids(
    component_prefix: str,
    marker_name: str,
) -> tuple[str, ...]:
    """Return the stable component inventory for one Sentinel corner-marker set."""

    return tuple(f"{component_prefix}-{marker_name}-{suffix}" for suffix in _CORNER_MARK_SUFFIXES)


def resolve_created_timestamp(base_context: dict[str, object]) -> str:
    """Normalize created timestamp fields for direct Sentinel display."""

    created_value = base_context.get("created_timestamp_utc")
    if created_value is None:
        created_value = base_context.get("created_date")

    created_dt = None
    created_timestamp_utc = None
    if isinstance(created_value, datetime):
        if created_value.tzinfo is None:
            created_value = created_value.replace(tzinfo=timezone.utc)
        created_dt = created_value.astimezone(timezone.utc)
    elif isinstance(created_value, date):
        created_dt = datetime.combine(created_value, datetime.min.time(), tzinfo=timezone.utc)
    elif isinstance(created_value, str):
        created_timestamp_utc, created_dt = timestamp_from_string(created_value)

    if created_timestamp_utc is None:
        created_dt = created_dt or datetime.now(timezone.utc)
        created_timestamp_utc = created_dt.strftime("%Y-%m-%d %H:%M UTC")

    base_context["created_timestamp_utc"] = created_timestamp_utc
    if created_dt is not None:
        base_context["created_date"] = created_dt.date().isoformat()
    return created_timestamp_utc


def _reflow_paint_plan(plan: PaintPlan, layout: SentinelPageLayout) -> PaintPlan:
    if isinstance(plan, PanelPlan):
        preserve_height = "qr-frame" in plan.component_id or "qr-image-frame" in plan.component_id
        rect = layout.map_rect(plan.rect, preserve_height=preserve_height)
        return replace(plan, rect=rect, proof=_box_proof(plan.proof, rect))
    if isinstance(plan, RulePlan):
        rect = layout.map_rect(plan.rect)
        return replace(plan, rect=rect, proof=_box_proof(plan.proof, rect))
    if isinstance(plan, EllipsePlan):
        rect = layout.map_rect(plan.rect, preserve_height=True)
        return replace(plan, rect=rect, proof=_box_proof(plan.proof, rect))
    if isinstance(plan, ImageBoxPlan):
        rect = layout.map_rect(plan.rect, preserve_height=True)
        return replace(plan, rect=rect, proof=_box_proof(plan.proof, rect))
    if isinstance(plan, LinePlan):
        start_x, end_x = _mapped_line_x(plan, layout)
        start_y = layout.map_y(plan.start_y_mm)
        end_y = layout.map_y(plan.end_y_mm)
        proof_rect = layout.map_rect(plan.proof.rect)
        return replace(
            plan,
            start_x_mm=start_x,
            start_y_mm=start_y,
            end_x_mm=end_x,
            end_y_mm=end_y,
            proof=_box_proof(plan.proof, proof_rect),
        )
    if isinstance(plan, TextBoxPlan):
        return _reflow_text_plan(plan, layout)
    raise TypeError(f"unsupported Sentinel paint plan: {type(plan).__name__}")


def _reflow_text_plan(plan: TextBoxPlan, layout: SentinelPageLayout) -> TextBoxPlan:
    mapped_rect = layout.map_rect(plan.rect)
    mapped_used_rect = PdfRect(
        layout.map_x(plan.proof.used_rect.x_mm),
        layout.map_y(plan.proof.used_rect.y_mm),
        plan.proof.used_rect.width_mm,
        plan.proof.used_rect.height_mm,
    )
    required_height = max(mapped_rect.height_mm, mapped_used_rect.height_mm)
    rect = replace(mapped_rect, height_mm=required_height)
    y_delta = rect.y_mm - plan.rect.y_mm
    lines = tuple(
        TextLinePlacement(
            text=line.text,
            x_mm=layout.map_x(line.x_mm),
            baseline_y_mm=line.baseline_y_mm + y_delta,
            width_mm=line.width_mm,
        )
        for line in plan.lines
    )
    proof = TextPlacementProof(
        component_id=plan.proof.component_id,
        rect=rect,
        used_rect=mapped_used_rect,
        policy=plan.proof.policy,
        line_count=plan.proof.line_count,
        overflow_line_count=plan.proof.overflow_line_count,
        font_size_pt=plan.proof.font_size_pt,
        overflow=plan.proof.overflow,
    )
    return replace(plan, rect=rect, lines=lines, proof=proof)


def _anchor_qr_compounds(
    reference_plans: tuple[PaintPlan, ...],
    responsive_plans: tuple[PaintPlan, ...],
    compounds: tuple[SentinelQrCompound, ...],
) -> tuple[PaintPlan, ...]:
    """Rigidly translate every QR compound member from its responsive frame anchor."""

    if not compounds:
        return responsive_plans
    reference_by_id = {plan.component_id: plan for plan in reference_plans}
    responsive_by_id = {plan.component_id: plan for plan in responsive_plans}
    replacements: dict[str, PaintPlan] = {}
    claimed_member_ids: set[str] = set()
    for compound in compounds:
        duplicate_members = claimed_member_ids.intersection(compound.member_component_ids)
        if duplicate_members:
            raise ValueError(
                "Sentinel QR compound member belongs to multiple compounds: "
                f"{sorted(duplicate_members)[0]}"
            )
        claimed_member_ids.update(compound.member_component_ids)
        reference_anchor = reference_by_id.get(compound.anchor_component_id)
        responsive_anchor = responsive_by_id.get(compound.anchor_component_id)
        if reference_anchor is None or responsive_anchor is None:
            raise ValueError(
                f"Sentinel QR compound references missing anchor: {compound.anchor_component_id}"
            )
        x_delta_mm = responsive_anchor.proof.rect.x_mm - reference_anchor.proof.rect.x_mm
        y_delta_mm = responsive_anchor.proof.rect.y_mm - reference_anchor.proof.rect.y_mm
        for component_id in compound.member_component_ids:
            reference_plan = reference_by_id.get(component_id)
            if reference_plan is None:
                raise ValueError(f"Sentinel QR compound references missing member: {component_id}")
            replacements[component_id] = _translate_paint_plan(
                reference_plan,
                x_delta_mm=x_delta_mm,
                y_delta_mm=y_delta_mm,
            )
    return tuple(replacements.get(plan.component_id, plan) for plan in responsive_plans)


def _translate_paint_plan(
    plan: PaintPlan,
    *,
    x_delta_mm: float,
    y_delta_mm: float,
) -> PaintPlan:
    if isinstance(plan, (PanelPlan, RulePlan, EllipsePlan, ImageBoxPlan)):
        rect = _translated_rect(plan.rect, x_delta_mm=x_delta_mm, y_delta_mm=y_delta_mm)
        return replace(plan, rect=rect, proof=_box_proof(plan.proof, rect))
    if isinstance(plan, LinePlan):
        proof_rect = _translated_rect(
            plan.proof.rect,
            x_delta_mm=x_delta_mm,
            y_delta_mm=y_delta_mm,
        )
        return replace(
            plan,
            start_x_mm=plan.start_x_mm + x_delta_mm,
            start_y_mm=plan.start_y_mm + y_delta_mm,
            end_x_mm=plan.end_x_mm + x_delta_mm,
            end_y_mm=plan.end_y_mm + y_delta_mm,
            proof=_box_proof(plan.proof, proof_rect),
        )
    if isinstance(plan, TextBoxPlan):
        rect = _translated_rect(plan.rect, x_delta_mm=x_delta_mm, y_delta_mm=y_delta_mm)
        used_rect = _translated_rect(
            plan.proof.used_rect,
            x_delta_mm=x_delta_mm,
            y_delta_mm=y_delta_mm,
        )
        proof = replace(plan.proof, rect=rect, used_rect=used_rect)
        lines = tuple(
            replace(
                line,
                x_mm=line.x_mm + x_delta_mm,
                baseline_y_mm=line.baseline_y_mm + y_delta_mm,
            )
            for line in plan.lines
        )
        return replace(plan, rect=rect, proof=proof, lines=lines)
    raise TypeError(f"unsupported Sentinel QR compound plan: {type(plan).__name__}")


def _translated_rect(
    rect: PdfRect,
    *,
    x_delta_mm: float,
    y_delta_mm: float,
) -> PdfRect:
    return replace(
        rect,
        x_mm=rect.x_mm + x_delta_mm,
        y_mm=rect.y_mm + y_delta_mm,
    )


def _box_proof(proof: BoxPlacementProof, rect: PdfRect) -> BoxPlacementProof:
    return replace(proof, rect=rect)


def _mapped_line_x(plan: LinePlan, layout: SentinelPageLayout) -> tuple[float, float]:
    base_width = SENTINEL_THEME.layout.page_width_mm
    if abs(plan.start_x_mm) <= 0.01 and abs(plan.end_x_mm - base_width) <= 0.01:
        return 0.0, layout.geometry.width_mm
    if abs(plan.end_x_mm) <= 0.01 and abs(plan.start_x_mm - base_width) <= 0.01:
        return layout.geometry.width_mm, 0.0
    return layout.map_x(plan.start_x_mm), layout.map_x(plan.end_x_mm)


def _spans_reference_page_width(rect: PdfRect) -> bool:
    return (
        abs(rect.x_mm) <= 0.01 and abs(rect.right_mm - SENTINEL_THEME.layout.page_width_mm) <= 0.01
    )


def _footer_separation_constraints(
    plans: tuple[PaintPlan, ...],
    layout: SentinelPageLayout,
    *,
    page_number: int,
) -> tuple[SeparationConstraint, ...]:
    footer_region = LayoutRegion(
        region_id=f"sentinel-footer-region-p{page_number}",
        rect=PdfRect(
            0.0,
            layout.footer_rule_y_mm,
            layout.geometry.width_mm,
            layout.geometry.height_mm - layout.footer_rule_y_mm,
        ),
    )
    body_component_ids = tuple(
        plan.component_id for plan in plans if "-footer-" not in plan.component_id
    )
    constraints: list[SeparationConstraint] = []
    if body_component_ids:
        constraints.append(
            SeparationConstraint(
                constraint_id=f"sentinel-body-footer-p{page_number}",
                first=ComponentGroup(
                    group_id=f"sentinel-body-components-p{page_number}",
                    component_ids=body_component_ids,
                ),
                second=footer_region,
                minimum_clearance_mm=_BODY_FOOTER_CLEARANCE_MM,
            )
        )
    qr_component_ids = tuple(plan.component_id for plan in plans if "qr-image" in plan.component_id)
    if qr_component_ids:
        constraints.append(
            SeparationConstraint(
                constraint_id=f"sentinel-qr-footer-p{page_number}",
                first=ComponentGroup(
                    group_id=f"sentinel-qr-images-p{page_number}",
                    component_ids=qr_component_ids,
                ),
                second=footer_region,
                minimum_clearance_mm=_QR_FOOTER_CLEARANCE_MM,
            )
        )
    return tuple(constraints)


def _qr_compound_separation_constraints(
    compounds: tuple[SentinelQrCompound, ...],
    *,
    page_number: int,
) -> tuple[SeparationConstraint, ...]:
    constraints: list[SeparationConstraint] = []
    for index, compound in enumerate(compounds, start=1):
        constraints.append(
            SeparationConstraint(
                constraint_id=f"sentinel-qr-marker-clearance-p{page_number}-{index}",
                first=ComponentGroup(
                    group_id=f"sentinel-qr-image-p{page_number}-{index}",
                    component_ids=(compound.image_component_id,),
                ),
                second=ComponentGroup(
                    group_id=f"sentinel-qr-markers-p{page_number}-{index}",
                    component_ids=compound.marker_component_ids,
                ),
                minimum_clearance_mm=compound.minimum_marker_clearance_mm,
            )
        )
        if compound.caption_component_id is not None:
            constraints.append(
                SeparationConstraint(
                    constraint_id=f"sentinel-qr-caption-p{page_number}-{index}",
                    first=ComponentGroup(
                        group_id=f"sentinel-qr-frame-p{page_number}-{index}",
                        component_ids=(compound.anchor_component_id,),
                    ),
                    second=ComponentGroup(
                        group_id=f"sentinel-qr-caption-p{page_number}-{index}",
                        component_ids=(compound.caption_component_id,),
                    ),
                    minimum_clearance_mm=compound.minimum_caption_clearance_mm,
                )
            )
    return tuple(constraints)


__all__ = [
    "SENTINEL_BACKGROUND",
    "SENTINEL_BLACK",
    "SENTINEL_BORDER",
    "SENTINEL_CONTENT_WIDTH_MM",
    "SENTINEL_CONTENT_X_MM",
    "SENTINEL_GRID_LINE",
    "SENTINEL_LINE_FILL",
    "SENTINEL_MUTED",
    "SENTINEL_ORANGE",
    "SENTINEL_PAGE_RECT",
    "SENTINEL_TEXT",
    "SENTINEL_WARNING_FILL",
    "SENTINEL_WHITE",
    "SentinelShellContext",
    "SentinelPageLayout",
    "SentinelQrCompound",
    "build_sentinel_corner_mark_plans",
    "build_sentinel_footer_plans",
    "build_sentinel_header_plans",
    "build_sentinel_page_layout",
    "build_sentinel_page_plan",
    "build_sentinel_shell_context",
    "build_sentinel_surface",
    "sentinel_corner_mark_component_ids",
]
