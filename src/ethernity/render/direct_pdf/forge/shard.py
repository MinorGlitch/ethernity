"""Forge shard document rendering through direct PDF primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ethernity.encoding.zbase32 import ZBASE32_ALPHABET
from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import ImageBox, Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackEntry as _FallbackEntry,
    FallbackSectionLines as _FallbackSectionLines,
    FallbackTitleEntry as _FallbackTitleEntry,
    build_fallback_proof_from_entry_groups,
    fallback_entries,
    fallback_sections,
)
from ethernity.render.direct_pdf.forge.common import (
    FORGE_SLATE_50,
    FORGE_SLATE_100,
    FORGE_SLATE_300,
    FORGE_SLATE_500,
    FORGE_SLATE_600,
    FORGE_SLATE_800,
    FORGE_SLATE_900,
    FORGE_WHITE,
    ForgePageLayout,
    ForgeShellContext,
    build_forge_content_constraints,
    build_forge_header_plans,
    build_forge_page_layout,
    build_forge_shell_context,
    explicit_creation_date,
)
from ethernity.render.direct_pdf.forge.shard_fallback import (
    ForgeShardFallbackLayoutProfile as _FallbackLayoutProfile,
    ForgeShardFallbackPageEntry as _FallbackPageEntry,
    forge_shard_fallback_capacity,
    forge_shard_fallback_column_width,
    forge_shard_fallback_profiles,
    place_forge_shard_fallback_entries,
)
from ethernity.render.direct_pdf.forge.theme import FORGE_THEME
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    DirectPdfPagePlan,
    PaintPlan,
    SeparationConstraint,
    build_page_plan,
)
from ethernity.render.direct_pdf.page_geometry import resolve_page_geometry
from ethernity.render.direct_pdf.shard_contract import validate_single_shard_fallback_contract
from ethernity.render.direct_pdf.structured_common import (
    component_prefix,
    qr_image,
    resolved_single_qr_payload,
)
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.text_measure import measured_grouped_line_length
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_SHARD
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderResult,
)

_COMPONENT_BASE = "forge-shard"
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_ROW_HEIGHT_MM = 3.25
_FALLBACK_DENSE_ROW_HEIGHT_MM = 2.65
_FALLBACK_HORIZONTAL_PADDING_MM = 4.0
_FALLBACK_COLUMN_GAP_MM = 4.0
_QR_IMAGE_SIZE_MM = 54.0
_QR_FRAME_SIZE_MM = 64.0
_ICON_WARNING = chr(0xE002)
_FALLBACK_LAYOUT_PROFILES = forge_shard_fallback_profiles(
    standard_row_height_mm=_FALLBACK_ROW_HEIGHT_MM,
    dense_row_height_mm=_FALLBACK_DENSE_ROW_HEIGHT_MM,
)


@dataclass(frozen=True)
class ForgeShardDirectPlan:
    """Measured pages and app-wide proofs for one direct Forge shard render."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    fallback_proof: RenderFallbackProof
    artifact_proof: RenderArtifactProof


@dataclass(frozen=True)
class _ForgeShardGeometry:
    layout: ForgePageLayout
    fallback_area: PdfRect
    primary_qr_frame: PdfRect


@dataclass(frozen=True)
class _FallbackPage:
    page_number: int
    area: PdfRect
    profile: _FallbackLayoutProfile
    entries: tuple[_FallbackPageEntry, ...]


def _forge_shard_geometry(inputs: RenderInputs) -> _ForgeShardGeometry:
    layout = build_forge_page_layout(resolve_page_geometry(inputs))
    primary_qr_top_mm = layout.regions.body.y_mm + 10.0
    primary_qr_frame = PdfRect(
        layout.regions.safe.x_mm,
        primary_qr_top_mm,
        _QR_FRAME_SIZE_MM,
        _QR_FRAME_SIZE_MM,
    )
    fallback_top_mm = primary_qr_frame.bottom_mm + 6.0
    fallback_height_mm = layout.regions.body.bottom_mm - fallback_top_mm
    minimum_fallback_height_mm = 7.0 + _FALLBACK_ROW_HEIGHT_MM
    if fallback_height_mm < minimum_fallback_height_mm:
        raise ValueError("Forge shard page body cannot fit legible fallback rows")
    return _ForgeShardGeometry(
        layout=layout,
        fallback_area=PdfRect(
            layout.regions.safe.x_mm,
            fallback_top_mm,
            layout.regions.safe.width_mm,
            fallback_height_mm,
        ),
        primary_qr_frame=primary_qr_frame,
    )


def render_forge_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge shard document directly to PDF and return validation proofs."""

    page = resolve_page_geometry(inputs)
    surface = FpdfSurface(page_width_mm=page.width_mm, page_height_mm=page.height_mm)
    creation_date = explicit_creation_date(inputs)
    if creation_date is not None:
        surface.set_creation_date(creation_date)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_forge_shard_direct_plan(surface, inputs)
    layout_proof = build_direct_layout_proof(plan.page_plans)
    write_direct_layout_debug_json(
        inputs=inputs,
        page_plans=plan.page_plans,
        style_name="forge",
        layout_proof=layout_proof,
    )
    for page_plan in plan.page_plans:
        page_plan.paint(surface)
    surface.output(inputs.output_path)
    return RenderResult(
        fallback_proof=plan.fallback_proof,
        artifact_proof=plan.artifact_proof,
        layout_proof=layout_proof,
    )


def build_forge_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ForgeShardDirectPlan:
    """Build measured direct-PDF plans and render proofs for Forge shard inputs."""

    _validate_inputs(inputs)
    geometry = _forge_shard_geometry(inputs)
    payload = resolved_single_qr_payload(inputs)
    qr_image_bytes = qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_forge_shell_context(inputs, doc_type=inputs.doc_type.strip().lower())
    sections, fallback_pages = _responsive_fallback_layout(
        surface,
        inputs.fallback_sections or (),
        geometry=geometry,
    )
    page_plans = tuple(
        _build_page(
            surface,
            context,
            fallback_page,
            geometry=geometry,
            qr_image=qr_image_bytes,
        )
        for fallback_page in fallback_pages
    )
    fallback_proof = build_fallback_proof_from_entry_groups(
        inputs,
        sections,
        tuple(tuple(page_entry.entry for page_entry in page.entries) for page in fallback_pages),
    )
    artifact_proof = build_render_artifact_proof(
        inputs,
        qr_payloads=(payload,),
        encoded_payload_count=1,
        physical_qr_count=len(page_plans),
        physical_qr_payload_indexes=tuple(0 for _ in page_plans),
        page_count=len(page_plans),
        fallback_proof=fallback_proof,
    )
    return ForgeShardDirectPlan(
        page_plans=page_plans,
        fallback_proof=fallback_proof,
        artifact_proof=artifact_proof,
    )


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_SHARD:
        raise ValueError("direct Forge shard renderer only supports shard documents")
    if not inputs.render_qr:
        raise ValueError("direct Forge shard renderer requires QR rendering")
    if not inputs.render_fallback:
        raise ValueError("direct Forge shard renderer requires fallback rendering")
    validate_single_shard_fallback_contract(
        inputs,
        renderer_label="direct Forge shard renderer",
    )

    resolve_page_geometry(inputs)

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Forge shard renderer currently supports PNG QR images only")


def _responsive_fallback_layout(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    geometry: _ForgeShardGeometry,
) -> tuple[tuple[_FallbackSectionLines, ...], tuple[_FallbackPage, ...]]:
    """Use the widest measured text column that keeps the fallback on one page."""

    resolved_sections, entries, profile = _fallback_layout_for_area(
        surface,
        sections,
        area=geometry.fallback_area,
    )
    return resolved_sections, _paginate_fallback_entries(
        entries,
        geometry=geometry,
        profile=profile,
    )


def _fallback_layout_for_area(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    area: PdfRect,
) -> tuple[
    tuple[_FallbackSectionLines, ...],
    tuple[_FallbackEntry, ...],
    _FallbackLayoutProfile,
]:
    """Resolve the least-dense measured profile that fits the supplied panel area."""

    for profile in _FALLBACK_LAYOUT_PROFILES:
        resolved_sections, entries = _fallback_candidate_for_profile(
            surface,
            sections,
            area=area,
            profile=profile,
        )
        capacity = forge_shard_fallback_capacity(
            area,
            profile=profile,
            reserved_height_mm=7.0,
        )
        if len(entries) <= capacity:
            return resolved_sections, entries, profile

    raise ValueError(
        "Forge shard fallback exceeds the single-page capacity at the readable font floor"
    )


def _fallback_candidate_for_profile(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    area: PdfRect,
    profile: _FallbackLayoutProfile,
) -> tuple[tuple[_FallbackSectionLines, ...], tuple[_FallbackEntry, ...]]:
    column_width_mm = forge_shard_fallback_column_width(
        area,
        column_count=profile.column_count,
        horizontal_padding_mm=_FALLBACK_HORIZONTAL_PADDING_MM,
        column_gap_mm=_FALLBACK_COLUMN_GAP_MM,
    )
    line_length = measured_grouped_line_length(
        surface,
        style=_fallback_payload_style(font_size_pt=profile.font_size_pt),
        alphabet=ZBASE32_ALPHABET,
        group_size=_FALLBACK_GROUP_SIZE,
        max_width_mm=column_width_mm,
    )
    resolved_sections = fallback_sections(
        sections,
        group_size=_FALLBACK_GROUP_SIZE,
        line_length=line_length,
    )
    return resolved_sections, fallback_entries(resolved_sections)


def _fallback_payload_style(*, font_size_pt: float) -> TextStyle:
    return TextStyle(family="Courier", size_pt=font_size_pt, color=FORGE_SLATE_900)


def _paginate_fallback_entries(
    entries: Sequence[_FallbackEntry],
    *,
    geometry: _ForgeShardGeometry,
    profile: _FallbackLayoutProfile,
) -> tuple[_FallbackPage, ...]:
    area = geometry.fallback_area
    page_entries = place_forge_shard_fallback_entries(
        entries,
        area=area,
        profile=profile,
        reserved_height_mm=7.0,
        renderer_label="Forge shard fallback",
    )
    return (
        _FallbackPage(
            page_number=1,
            area=area,
            profile=profile,
            entries=page_entries,
        ),
    )


def _build_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    fallback_page: _FallbackPage,
    *,
    geometry: _ForgeShardGeometry,
    qr_image: bytes,
) -> DirectPdfPagePlan:
    if fallback_page.page_number != 1:
        raise ValueError("Forge shard renderer only supports one fallback page")
    page_label = "PAGE 1 / 1"
    plans: list[PaintPlan] = []
    plans.extend(
        build_forge_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=fallback_page.page_number,
            component_base=_COMPONENT_BASE,
            classification_default=_classification_default(context),
            page_rect=geometry.layout.page.rect,
        )
    )
    plans.extend(_warning_plans(surface, context, layout=geometry.layout))
    plans.extend(_shard_stats_plans(surface, context, layout=geometry.layout))
    plans.extend(
        _primary_qr_plans(
            surface,
            frame_rect=geometry.primary_qr_frame,
            qr_image=qr_image,
        )
    )
    plans.extend(_signature_plans(surface, layout=geometry.layout))
    plans.extend(_fallback_plans(surface, fallback_page, context=context))
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    intro_id = f"{prefix}-qr-frame"
    content_ids = (
        intro_id,
        f"{prefix}-warning-panel",
        f"{prefix}-stats-rule",
        f"{prefix}-fallback-panel",
    )
    constraints = list(
        build_forge_content_constraints(
            component_base=_COMPONENT_BASE,
            page_number=fallback_page.page_number,
            layout=geometry.layout,
            content_component_ids=content_ids,
        )
    )
    constraints.append(
        SeparationConstraint(
            constraint_id=f"{prefix}-fallback-after-intro",
            first=ComponentGroup(
                group_id=f"{prefix}-intro-content",
                component_ids=(
                    intro_id,
                    f"{prefix}-warning-panel",
                    f"{prefix}-stats-rule",
                ),
            ),
            second=ComponentGroup(
                group_id=f"{prefix}-fallback-content",
                component_ids=(f"{prefix}-fallback-panel",),
            ),
            minimum_clearance_mm=5.5,
        )
    )
    constraints.extend(
        (
            SeparationConstraint(
                constraint_id=f"{prefix}-stats-after-warning",
                first=ComponentGroup(
                    group_id=f"{prefix}-warning-content",
                    component_ids=(f"{prefix}-warning-panel",),
                ),
                second=ComponentGroup(
                    group_id=f"{prefix}-stats-content",
                    component_ids=(
                        f"{prefix}-total-label",
                        f"{prefix}-total-value",
                        f"{prefix}-generated-label",
                        f"{prefix}-generated-value",
                        f"{prefix}-stats-rule",
                    ),
                ),
                minimum_clearance_mm=4.0,
            ),
            SeparationConstraint(
                constraint_id=f"{prefix}-qr-after-stats",
                first=ComponentGroup(
                    group_id=f"{prefix}-stats-for-qr",
                    component_ids=(f"{prefix}-stats-rule",),
                ),
                second=ComponentGroup(
                    group_id=f"{prefix}-primary-qr",
                    component_ids=(f"{prefix}-qr-frame",),
                ),
                minimum_clearance_mm=5.0,
            ),
        )
    )
    return build_page_plan(
        page_number=fallback_page.page_number,
        rect=geometry.layout.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _classification_default(context: ForgeShellContext) -> str:
    if context.copy.get("key_material_label"):
        return "Restricted Access"
    return "Confidential"


def _warning_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, 1)
    x_mm = layout.regions.safe.x_mm + _QR_FRAME_SIZE_MM + 8.0
    top_mm = layout.regions.body.y_mm + 10.0
    width_mm = layout.regions.safe.right_mm - x_mm
    return [
        Panel(
            component_id=f"{prefix}-warning-panel",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_100,
            line_width_mm=0.5,
        ).plan(surface, PdfRect(x_mm, top_mm, width_mm, 36.0)),
        Panel(
            component_id=f"{prefix}-warning-icon-box",
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(x_mm + 4.0, top_mm + 4.0, 9.0, 9.0)),
        TextBox(
            component_id=f"{prefix}-warning-icon",
            text=_ICON_WARNING,
            style=FORGE_THEME.symbol_style(size_pt=10.0, color=FORGE_WHITE),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=8.0,
        ).plan(surface, PdfRect(x_mm + 4.0, top_mm + 4.7, 9.0, 7.5)),
        TextBox(
            component_id=f"{prefix}-warning-title",
            text=str(context.copy.get("warning_title") or "Critical Security Notice").upper(),
            style=FORGE_THEME.sans_style(size_pt=9.5, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.0,
        ).plan(surface, PdfRect(x_mm + 17.0, top_mm + 4.5, width_mm - 21.0, 5.0)),
        TextBox(
            component_id=f"{prefix}-warning-body",
            text=str(context.copy.get("warning_body") or ""),
            style=FORGE_THEME.sans_style(size_pt=7.6, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.18,
        ).plan(surface, PdfRect(x_mm + 4.0, top_mm + 15.0, width_mm - 8.0, 16.0)),
    ]


def _shard_stats_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    layout: ForgePageLayout,
) -> list[PaintPlan]:
    shard_total = str(context.values.get("shard_total") or "")
    x_mm = layout.regions.safe.x_mm + _QR_FRAME_SIZE_MM + 8.0
    right_mm = layout.regions.safe.right_mm
    top_mm = layout.regions.body.y_mm + 51.0
    width_mm = right_mm - x_mm
    return [
        TextBox(
            component_id="forge-shard-p1-total-label",
            text="TOTAL SHARDS",
            style=FORGE_THEME.sans_style(size_pt=6.5, bold=True, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(x_mm, top_mm, width_mm * 0.35, 3.5)),
        TextBox(
            component_id="forge-shard-p1-total-value",
            text=shard_total,
            style=FORGE_THEME.mono_style(size_pt=9.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=8.0,
        ).plan(surface, PdfRect(x_mm, top_mm + 4.0, width_mm * 0.35, 5.0)),
        TextBox(
            component_id="forge-shard-p1-generated-label",
            text="GENERATED",
            style=FORGE_THEME.sans_style(size_pt=6.5, bold=True, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(x_mm + width_mm * 0.38, top_mm, width_mm * 0.62, 3.5)),
        TextBox(
            component_id="forge-shard-p1-generated-value",
            text=context.created_timestamp_utc,
            style=FORGE_THEME.mono_style(size_pt=7.2, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
            align=TextAlign.RIGHT,
        ).plan(
            surface,
            PdfRect(x_mm + width_mm * 0.34, top_mm + 4.0, width_mm * 0.66, 5.0),
        ),
        Rule(
            component_id="forge-shard-p1-stats-rule",
            color=FORGE_SLATE_900,
        ).plan(surface, PdfRect(x_mm, top_mm + 12.5, width_mm, 0.35)),
    ]


def _primary_qr_plans(
    surface: PdfSurface,
    *,
    frame_rect: PdfRect,
    qr_image: bytes,
) -> list[PaintPlan]:
    image_rect = PdfRect(
        frame_rect.x_mm + (_QR_FRAME_SIZE_MM - _QR_IMAGE_SIZE_MM) / 2.0,
        frame_rect.y_mm + (_QR_FRAME_SIZE_MM - _QR_IMAGE_SIZE_MM) / 2.0,
        _QR_IMAGE_SIZE_MM,
        _QR_IMAGE_SIZE_MM,
    )
    return [
        Panel(
            component_id="forge-shard-p1-qr-frame",
            stroke=FORGE_SLATE_900,
            fill=FORGE_WHITE,
            line_width_mm=0.9,
        ).plan(surface, frame_rect),
        ImageBox(
            component_id="forge-shard-p1-qr-image",
            image=qr_image,
            image_type="PNG",
        ).plan(surface, image_rect),
    ]


def _signature_plans(
    surface: PdfSurface,
    *,
    layout: ForgePageLayout,
) -> list[PaintPlan]:
    footer = layout.regions.footer
    return [
        Rule(
            component_id="forge-shard-p1-validator-line",
            color=FORGE_SLATE_900,
        ).plan(surface, PdfRect(footer.x_mm, footer.y_mm + 8.5, 80.0, 0.35)),
        Rule(
            component_id="forge-shard-p1-date-line",
            color=FORGE_SLATE_900,
        ).plan(surface, PdfRect(footer.right_mm - 53.0, footer.y_mm + 8.5, 53.0, 0.35)),
        TextBox(
            component_id="forge-shard-p1-date-placeholder",
            text="____ / ____ / ________",
            style=FORGE_THEME.mono_style(size_pt=7.2, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(footer.right_mm - 70.0, footer.y_mm + 3.0, 70.0, 4.0)),
        TextBox(
            component_id="forge-shard-p1-validator-label",
            text="VALIDATOR SIGNATURE",
            style=FORGE_THEME.sans_style(size_pt=6.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(footer.x_mm, footer.y_mm + 10.5, 70.0, 2.6)),
        TextBox(
            component_id="forge-shard-p1-date-label",
            text="DATE VERIFIED",
            style=FORGE_THEME.sans_style(size_pt=6.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(footer.right_mm - 65.0, footer.y_mm + 10.5, 65.0, 2.6)),
    ]


def _fallback_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPage,
    *,
    context: ForgeShellContext,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-fallback-panel",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, fallback_page.area),
        TextBox(
            component_id=f"{prefix}-fallback-label",
            text=str(
                context.copy.get("manual_transcription_label") or "Manual Transcription"
            ).upper(),
            style=TextStyle(family="Helvetica", size_pt=6.0, style="B", color=FORGE_SLATE_600),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                fallback_page.area.x_mm + 3.0,
                fallback_page.area.y_mm + 1.5,
                fallback_page.area.width_mm - 6.0,
                4.5,
            ),
        ),
    ]
    line_start_y = fallback_page.area.y_mm + 7.0
    column_width_mm = forge_shard_fallback_column_width(
        fallback_page.area,
        column_count=fallback_page.profile.column_count,
        horizontal_padding_mm=_FALLBACK_HORIZONTAL_PADDING_MM,
        column_gap_mm=_FALLBACK_COLUMN_GAP_MM,
    )
    for index, page_entry in enumerate(fallback_page.entries):
        row_y = line_start_y + page_entry.row_index * fallback_page.profile.row_height_mm
        column_x = (
            fallback_page.area.x_mm
            + _FALLBACK_HORIZONTAL_PADDING_MM
            + page_entry.column_index * (column_width_mm + _FALLBACK_COLUMN_GAP_MM)
        )
        if isinstance(page_entry.entry, _FallbackTitleEntry):
            plans.append(
                TextBox(
                    component_id=f"{prefix}-fallback-title-{index}",
                    text=page_entry.entry.title.upper(),
                    style=TextStyle(
                        family="Helvetica",
                        size_pt=fallback_page.profile.font_size_pt,
                        style="B",
                        color=FORGE_SLATE_500,
                    ),
                    policy=TextFitPolicy.FAIL,
                ).plan(
                    surface,
                    PdfRect(
                        column_x,
                        row_y,
                        column_width_mm,
                        fallback_page.profile.row_height_mm,
                    ),
                )
            )
            continue
        plans.append(
            TextBox(
                component_id=f"{prefix}-fallback-line-{index}",
                text=page_entry.entry.text,
                style=_fallback_payload_style(
                    font_size_pt=fallback_page.profile.font_size_pt,
                ),
                policy=TextFitPolicy.FAIL,
                min_size_pt=6.0,
            ).plan(
                surface,
                PdfRect(
                    column_x,
                    row_y,
                    column_width_mm,
                    fallback_page.profile.row_height_mm,
                ),
            )
        )
    return plans


__all__ = [
    "ForgeShardDirectPlan",
    "build_forge_shard_direct_plan",
    "render_forge_shard_direct_pdf",
]
