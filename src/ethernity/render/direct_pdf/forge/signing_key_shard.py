"""Forge signing-key shard rendering through direct PDF primitives."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.encoding.zbase32 import ZBASE32_ALPHABET
from ethernity.qr.codec import QrConfig
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import ImageBox, Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackEntry as _FallbackEntry,
    FallbackLineEntry as _FallbackLineEntry,
    FallbackSectionLines as _FallbackSectionLines,
    FallbackTitleEntry as _FallbackTitleEntry,
    build_fallback_proof_from_entry_groups,
    fallback_entries,
    fallback_sections,
)
from ethernity.render.direct_pdf.forge.common import (
    FORGE_SLATE_50,
    FORGE_SLATE_300,
    FORGE_SLATE_700,
    FORGE_SLATE_800,
    FORGE_SLATE_900,
    FORGE_WHITE,
    ForgePageLayout,
    ForgeShellContext,
    build_forge_content_constraints,
    build_forge_footer_plans,
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
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderResult,
)

_COMPONENT_BASE = "forge-signing-key-shard"
_FALLBACK_GROUP_SIZE = 4
_FALLBACK_ROW_HEIGHT_MM = 3.0
_FALLBACK_DENSE_ROW_HEIGHT_MM = 2.65
_FALLBACK_COLUMN_GAP_MM = 4.0
_QR_IMAGE_SIZE_MM = 54.0
_QR_FRAME_SIZE_MM = 64.0
_INTRO_HEIGHT_MM = 64.0
_INTRO_PAYLOAD_GAP_MM = 6.0
_PAYLOAD_INTACT_GAP_MM = 1.5
_INTACT_HEIGHT_MM = 3.0
_HEADER_BODY_CLEARANCE_MM = 3.0
_FALLBACK_LABEL_HEIGHT_MM = 3.0
_FALLBACK_STATIC_LABEL = "SHARD PAYLOAD"
_ICON_SHIELD_LOCK = chr(0xF686)
_FORGE_SLATE_400 = PdfColor(148, 163, 184)
_FORGE_BLUE = PdfColor(25, 118, 210)
_FALLBACK_LAYOUT_PROFILES = forge_shard_fallback_profiles(
    standard_row_height_mm=_FALLBACK_ROW_HEIGHT_MM,
    dense_row_height_mm=_FALLBACK_DENSE_ROW_HEIGHT_MM,
)


@dataclass(frozen=True)
class ForgeSigningKeyShardDirectPlan:
    """Measured pages and proofs for one direct Forge signing-key shard render."""

    page_plans: tuple[DirectPdfPagePlan, ...]
    fallback_proof: RenderFallbackProof
    artifact_proof: RenderArtifactProof


@dataclass(frozen=True)
class _ForgeSigningKeyShardGeometry:
    layout: ForgePageLayout
    horizontal_offset_mm: float
    upper_vertical_offset_mm: float

    def with_actual_header_bottom(self, header_bottom_mm: float) -> _ForgeSigningKeyShardGeometry:
        """Resolve the single-page content stack from measured shell boundaries."""

        nominal_intro_top_mm = self.layout.regions.body.y_mm + 10.0
        upper_offset_mm = max(
            0.0,
            header_bottom_mm + _HEADER_BODY_CLEARANCE_MM - nominal_intro_top_mm,
        )

        resolved = _ForgeSigningKeyShardGeometry(
            layout=self.layout,
            horizontal_offset_mm=self.horizontal_offset_mm,
            upper_vertical_offset_mm=upper_offset_mm,
        )
        minimum_payload_height_mm = 7.0 + 33 * _FALLBACK_ROW_HEIGHT_MM
        if resolved.payload_panel_rect.height_mm + 0.01 < minimum_payload_height_mm:
            raise ValueError(
                "Forge signing-key shard page is too short for the maximum single-page payload"
            )
        return resolved

    @property
    def content_x_mm(self) -> float:
        return 15.0 + self.horizontal_offset_mm

    @property
    def intro_top_mm(self) -> float:
        return self.layout.regions.body.y_mm + 10.0 + self.upper_vertical_offset_mm

    @property
    def qr_frame_rect(self) -> PdfRect:
        return PdfRect(
            self.content_x_mm,
            self.intro_top_mm,
            _QR_FRAME_SIZE_MM,
            _QR_FRAME_SIZE_MM,
        )

    @property
    def payload_panel_rect(self) -> PdfRect:
        top_mm = self.intro_top_mm + _INTRO_HEIGHT_MM + _INTRO_PAYLOAD_GAP_MM
        intact_top_mm = self.layout.regions.body.bottom_mm - _INTACT_HEIGHT_MM
        bottom_mm = intact_top_mm - _PAYLOAD_INTACT_GAP_MM
        safe = self.layout.regions.safe
        return PdfRect(safe.x_mm, top_mm, safe.width_mm, bottom_mm - top_mm)

    @property
    def intact_notice_rect(self) -> PdfRect:
        return PdfRect(
            self.content_x_mm + 25.0,
            self.layout.regions.body.bottom_mm - _INTACT_HEIGHT_MM,
            130.0,
            _INTACT_HEIGHT_MM,
        )

    @property
    def payload_text_area(self) -> PdfRect:
        panel = self.payload_panel_rect
        return PdfRect(
            panel.x_mm + 4.0,
            panel.y_mm + 7.0 + _FALLBACK_LABEL_HEIGHT_MM,
            panel.width_mm - 8.0,
            panel.height_mm - 9.0 - _FALLBACK_LABEL_HEIGHT_MM,
        )

    @property
    def payload_label_rect(self) -> PdfRect:
        panel = self.payload_panel_rect
        return PdfRect(
            panel.x_mm + 4.0,
            panel.y_mm + 7.0,
            panel.width_mm - 8.0,
            _FALLBACK_LABEL_HEIGHT_MM,
        )


@dataclass(frozen=True)
class _FallbackPage:
    page_number: int
    profile: _FallbackLayoutProfile
    entries: tuple[_FallbackPageEntry, ...]


def _forge_signing_key_shard_geometry(inputs: RenderInputs) -> _ForgeSigningKeyShardGeometry:
    layout = build_forge_page_layout(resolve_page_geometry(inputs))
    horizontal_offset_mm = (layout.regions.safe.width_mm - 180.0) / 2.0
    return _ForgeSigningKeyShardGeometry(
        layout=layout,
        horizontal_offset_mm=horizontal_offset_mm,
        upper_vertical_offset_mm=0.0,
    )


def render_forge_signing_key_shard_direct_pdf(inputs: RenderInputs) -> RenderResult:
    """Render a Forge signing-key shard document directly to PDF."""

    page = resolve_page_geometry(inputs)
    surface = FpdfSurface(page_width_mm=page.width_mm, page_height_mm=page.height_mm)
    creation_date = explicit_creation_date(inputs)
    if creation_date is not None:
        surface.set_creation_date(creation_date)
    packaged_direct_pdf_assets().register_fonts(surface)
    plan = build_forge_signing_key_shard_direct_plan(surface, inputs)
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


def build_forge_signing_key_shard_direct_plan(
    surface: PdfSurface,
    inputs: RenderInputs,
) -> ForgeSigningKeyShardDirectPlan:
    """Build measured direct-PDF plans and proofs for Forge signing-key shard inputs."""

    _validate_inputs(inputs)
    geometry = _forge_signing_key_shard_geometry(inputs)
    payload = resolved_single_qr_payload(inputs)
    qr_image_bytes = qr_image(payload, config=inputs.qr_config or QrConfig())
    context = build_forge_shell_context(inputs, doc_type=DOC_TYPE_SIGNING_KEY_SHARD)
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
            total_pages=len(fallback_pages),
        )
        for fallback_page in fallback_pages
    )
    fallback_proof = build_fallback_proof_from_entry_groups(
        inputs,
        sections,
        (fallback_entries(sections),),
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
    return ForgeSigningKeyShardDirectPlan(
        page_plans=page_plans,
        fallback_proof=fallback_proof,
        artifact_proof=artifact_proof,
    )


def _validate_inputs(inputs: RenderInputs) -> None:
    normalized_doc_type = inputs.doc_type.strip().lower()
    if normalized_doc_type != DOC_TYPE_SIGNING_KEY_SHARD:
        raise ValueError("direct Forge signing-key shard renderer only supports signing-key shards")
    if not inputs.render_qr:
        raise ValueError("direct Forge signing-key shard renderer requires QR rendering")
    if not inputs.render_fallback:
        raise ValueError("direct Forge signing-key shard renderer requires fallback rendering")
    validate_single_shard_fallback_contract(
        inputs,
        renderer_label="direct Forge signing-key shard renderer",
    )

    resolve_page_geometry(inputs)

    qr_config = inputs.qr_config or QrConfig()
    qr_kind = str(qr_config.kind or "png").strip().lower()
    if qr_kind != "png":
        raise ValueError("direct Forge signing-key shard renderer supports PNG QR images only")


def _responsive_fallback_layout(
    surface: PdfSurface,
    sections: Sequence[FallbackSection],
    *,
    geometry: _ForgeSigningKeyShardGeometry,
) -> tuple[tuple[_FallbackSectionLines, ...], tuple[_FallbackPage, ...]]:
    """Use the widest measured payload column that fits the single-page panel."""

    resolved_sections, entries, profile = _fallback_layout_for_area(
        surface,
        sections,
        area=geometry.payload_text_area,
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
    """Resolve the least-dense measured profile that fits the supplied text area."""

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
            reserved_height_mm=0.0,
        )
        if len(entries) <= capacity:
            return resolved_sections, entries, profile

    raise ValueError(
        "Forge signing-key shard fallback exceeds the single-page capacity "
        "at the readable font floor"
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
        horizontal_padding_mm=0.0,
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
    return resolved_sections, _fallback_entries(resolved_sections)


def _fallback_payload_style(*, font_size_pt: float) -> TextStyle:
    return FORGE_THEME.mono_style(size_pt=font_size_pt, color=FORGE_SLATE_900)


def _fallback_entries(sections: Sequence[_FallbackSectionLines]) -> tuple[_FallbackEntry, ...]:
    entries: list[_FallbackEntry] = []
    for section in sections:
        if section.title and " ".join(section.title.casefold().split()) != (
            _FALLBACK_STATIC_LABEL.casefold()
        ):
            entries.append(
                _FallbackTitleEntry(section_index=section.section_index, title=section.title)
            )
        for line_number, line in enumerate(section.lines, start=1):
            entries.append(
                _FallbackLineEntry(
                    section_index=section.section_index,
                    line_number=line_number,
                    text=line,
                )
            )
    return tuple(entries)


def _paginate_fallback_entries(
    entries: Sequence[_FallbackEntry],
    *,
    geometry: _ForgeSigningKeyShardGeometry,
    profile: _FallbackLayoutProfile,
) -> tuple[_FallbackPage, ...]:
    placed = place_forge_shard_fallback_entries(
        entries,
        area=geometry.payload_text_area,
        profile=profile,
        reserved_height_mm=0.0,
        renderer_label="Forge signing-key shard fallback",
    )
    return (
        _FallbackPage(
            page_number=1,
            profile=profile,
            entries=placed,
        ),
    )


def _build_page(
    surface: PdfSurface,
    context: ForgeShellContext,
    fallback_page: _FallbackPage,
    *,
    geometry: _ForgeSigningKeyShardGeometry,
    qr_image: bytes,
    total_pages: int,
) -> DirectPdfPagePlan:
    page_label = f"PAGE {fallback_page.page_number} / {total_pages}"
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    header_plans = build_forge_header_plans(
        surface,
        context,
        page_label=page_label,
        page_number=fallback_page.page_number,
        component_base=_COMPONENT_BASE,
        classification_default="Restricted Access",
        kicker_text="",
        icon_text="",
        page_rect=geometry.layout.page.rect,
    )
    header_rule = next(
        plan for plan in header_plans if plan.component_id == f"{prefix}-header-rule"
    )
    placed_geometry = geometry.with_actual_header_bottom(header_rule.proof.rect.bottom_mm)

    plans: list[PaintPlan] = list(header_plans)
    plans.extend(
        _warning_plans(
            surface,
            context,
            fallback_page.page_number,
            geometry=placed_geometry,
        )
    )
    plans.extend(
        _key_material_plans(
            surface,
            context,
            fallback_page,
            geometry=placed_geometry,
            qr_image=qr_image,
        )
    )
    plans.extend(
        _reference_and_specs_plans(
            surface,
            context,
            fallback_page.page_number,
            geometry=placed_geometry,
        )
    )
    plans.extend(
        _intact_notice_plans(
            surface,
            fallback_page.page_number,
            geometry=placed_geometry,
        )
    )
    plans.extend(
        build_forge_footer_plans(
            surface,
            context,
            page_label=page_label,
            page_number=fallback_page.page_number,
            component_base=_COMPONENT_BASE,
            page_rect=geometry.layout.page.rect,
        )
    )
    constraints = list(
        build_forge_content_constraints(
            component_base=_COMPONENT_BASE,
            page_number=fallback_page.page_number,
            layout=geometry.layout,
            content_component_ids=(
                f"{prefix}-warning-panel-bg",
                f"{prefix}-qr-paper",
                f"{prefix}-payload-panel",
                f"{prefix}-reference-panel",
                f"{prefix}-specs-table",
                f"{prefix}-intact-notice",
            ),
        )
    )
    constraints.extend(
        (
            SeparationConstraint(
                constraint_id=f"{prefix}-warning-after-actual-header",
                first=ComponentGroup(
                    group_id=f"{prefix}-actual-header-rule",
                    component_ids=(f"{prefix}-header-rule",),
                ),
                second=ComponentGroup(
                    group_id=f"{prefix}-warning-panel",
                    component_ids=(
                        f"{prefix}-warning-panel-bg",
                        f"{prefix}-qr-paper",
                    ),
                ),
                minimum_clearance_mm=_HEADER_BODY_CLEARANCE_MM,
            ),
            SeparationConstraint(
                constraint_id=f"{prefix}-payload-after-warning",
                first=ComponentGroup(
                    group_id=f"{prefix}-intro-content",
                    component_ids=(
                        f"{prefix}-warning-panel-bg",
                        f"{prefix}-qr-paper",
                        f"{prefix}-reference-panel",
                        f"{prefix}-specs-table",
                    ),
                ),
                second=ComponentGroup(
                    group_id=f"{prefix}-payload-content",
                    component_ids=(f"{prefix}-payload-panel",),
                ),
                minimum_clearance_mm=_INTRO_PAYLOAD_GAP_MM,
            ),
            SeparationConstraint(
                constraint_id=f"{prefix}-intact-after-payload",
                first=ComponentGroup(
                    group_id=f"{prefix}-payload-content-for-intact",
                    component_ids=(f"{prefix}-payload-panel",),
                ),
                second=ComponentGroup(
                    group_id=f"{prefix}-intact-notice-content",
                    component_ids=(f"{prefix}-intact-notice",),
                ),
                minimum_clearance_mm=_PAYLOAD_INTACT_GAP_MM,
            ),
        )
    )
    return build_page_plan(
        page_number=fallback_page.page_number,
        rect=geometry.layout.page.rect,
        plans=plans,
        separation_constraints=constraints,
    )


def _warning_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    page_number: int,
    *,
    geometry: _ForgeSigningKeyShardGeometry,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    qr_rect = geometry.qr_frame_rect
    rect = PdfRect(
        qr_rect.right_mm + 8.0,
        geometry.intro_top_mm,
        geometry.content_x_mm + 180.0 - qr_rect.right_mm - 8.0,
        31.0,
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-warning-panel-bg",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, rect),
    ]
    plans.extend(_dashed_border_plans(surface, f"{prefix}-warning-dash", rect, _FORGE_SLATE_400))
    plans.extend(
        [
            TextBox(
                component_id=f"{prefix}-warning-icon",
                text=_ICON_SHIELD_LOCK,
                style=FORGE_THEME.symbol_style(size_pt=10.0, color=_FORGE_BLUE),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(rect.x_mm + 4.0, rect.y_mm + 4.0, 7.0, 6.0)),
            TextBox(
                component_id=f"{prefix}-warning-title",
                text=str(context.copy.get("warning_title") or "Critical Security Notice").upper(),
                style=FORGE_THEME.sans_style(size_pt=8.0, bold=True, color=FORGE_SLATE_900),
                policy=TextFitPolicy.SHRINK,
                min_size_pt=6.0,
            ).plan(surface, PdfRect(rect.x_mm + 13.0, rect.y_mm + 3.5, rect.width_mm - 17.0, 4.5)),
            TextBox(
                component_id=f"{prefix}-warning-body",
                text=str(context.copy.get("warning_body") or ""),
                style=FORGE_THEME.sans_style(size_pt=7.0, color=FORGE_SLATE_800),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.12,
            ).plan(surface, PdfRect(rect.x_mm + 4.0, rect.y_mm + 11.0, rect.width_mm - 8.0, 11.0)),
            TextBox(
                component_id=f"{prefix}-warning-instructions",
                text=" | ".join(context.instruction_lines),
                style=FORGE_THEME.sans_style(size_pt=6.2, color=FORGE_SLATE_700),
                policy=TextFitPolicy.WRAP,
                line_height_multiplier=1.05,
            ).plan(
                surface,
                PdfRect(rect.x_mm + 4.0, rect.y_mm + 22.5, rect.width_mm - 8.0, 7.5),
            ),
        ]
    )
    return plans


def _key_material_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    fallback_page: _FallbackPage,
    *,
    geometry: _ForgeSigningKeyShardGeometry,
    qr_image: bytes,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    panel_rect = geometry.payload_panel_rect
    qr_rect = geometry.qr_frame_rect
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-payload-panel",
            stroke=FORGE_SLATE_900,
            fill=FORGE_WHITE,
            line_width_mm=0.5,
        ).plan(surface, panel_rect),
        Panel(
            component_id=f"{prefix}-qr-paper",
            stroke=FORGE_SLATE_900,
            fill=FORGE_WHITE,
            line_width_mm=0.5,
        ).plan(surface, qr_rect),
        ImageBox(
            component_id=f"{prefix}-qr-image",
            image=qr_image,
            image_type="png",
        ).plan(
            surface,
            PdfRect(
                qr_rect.x_mm + 5.0,
                qr_rect.y_mm + 5.0,
                _QR_IMAGE_SIZE_MM,
                _QR_IMAGE_SIZE_MM,
            ),
        ),
        TextBox(
            component_id=f"{prefix}-key-section-title",
            text=(
                f"01. {str(context.copy.get('key_material_label') or 'Key Material Payload')}"
            ).upper(),
            style=FORGE_THEME.sans_style(size_pt=7.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(panel_rect.x_mm + 4.0, panel_rect.y_mm + 2.0, 92.0, 4.0)),
        TextBox(
            component_id=f"{prefix}-payload-shard-meta",
            text=(
                f"SHARD {_context_int(context, 'shard_index')} / "
                f"{_context_int(context, 'shard_total')} // QR + TEXT"
            ),
            style=FORGE_THEME.mono_style(size_pt=6.0, bold=True, color=FORGE_SLATE_700),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.RIGHT,
        ).plan(surface, PdfRect(panel_rect.right_mm - 78.0, panel_rect.y_mm + 2.0, 74.0, 4.0)),
    ]
    plans.extend(_payload_corner_plans(surface, prefix, panel_rect))
    plans.extend(_payload_fallback_plans(surface, fallback_page, geometry=geometry))
    return plans


def _payload_fallback_plans(
    surface: PdfSurface,
    fallback_page: _FallbackPage,
    *,
    geometry: _ForgeSigningKeyShardGeometry,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, fallback_page.page_number)
    payload_text_area = geometry.payload_text_area
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-payload-static-label",
            text=_FALLBACK_STATIC_LABEL,
            style=FORGE_THEME.sans_style(size_pt=6.0, bold=True, color=FORGE_SLATE_800),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, geometry.payload_label_rect),
    ]
    column_width_mm = forge_shard_fallback_column_width(
        payload_text_area,
        column_count=fallback_page.profile.column_count,
        horizontal_padding_mm=0.0,
        column_gap_mm=_FALLBACK_COLUMN_GAP_MM,
    )
    for index, page_entry in enumerate(fallback_page.entries):
        y = payload_text_area.y_mm + page_entry.row_index * fallback_page.profile.row_height_mm
        x = payload_text_area.x_mm + page_entry.column_index * (
            column_width_mm + _FALLBACK_COLUMN_GAP_MM
        )
        entry = page_entry.entry
        if isinstance(entry, _FallbackTitleEntry):
            plans.append(
                TextBox(
                    component_id=f"{prefix}-payload-title-{index}",
                    text=entry.title,
                    style=FORGE_THEME.sans_style(
                        size_pt=fallback_page.profile.font_size_pt,
                        bold=True,
                        color=FORGE_SLATE_800,
                    ),
                    policy=TextFitPolicy.FAIL,
                ).plan(
                    surface,
                    PdfRect(x, y, column_width_mm, fallback_page.profile.row_height_mm),
                )
            )
            continue
        plans.append(
            TextBox(
                component_id=f"{prefix}-payload-line-{index}",
                text=entry.text,
                style=_fallback_payload_style(
                    font_size_pt=fallback_page.profile.font_size_pt,
                ),
                policy=TextFitPolicy.FAIL,
            ).plan(
                surface,
                PdfRect(x, y, column_width_mm, fallback_page.profile.row_height_mm),
            )
        )
    return plans


def _reference_and_specs_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    page_number: int,
    *,
    geometry: _ForgeSigningKeyShardGeometry,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    qr_rect = geometry.qr_frame_rect
    top_mm = geometry.intro_top_mm + 35.0
    x_mm = qr_rect.right_mm + 8.0
    available_width_mm = geometry.content_x_mm + 180.0 - x_mm
    gap_mm = 4.0
    panel_width_mm = (available_width_mm - gap_mm) / 2.0
    reference_rect = PdfRect(x_mm, top_mm, panel_width_mm, 29.0)
    specs_rect = PdfRect(x_mm + panel_width_mm + gap_mm, top_mm, panel_width_mm, 29.0)
    return [
        Panel(
            component_id=f"{prefix}-reference-panel",
            stroke=FORGE_SLATE_300,
            fill=FORGE_SLATE_50,
            line_width_mm=0.2,
        ).plan(surface, reference_rect),
        TextBox(
            component_id=f"{prefix}-reference-title",
            text="02. PUBLIC REFERENCE",
            style=FORGE_THEME.sans_style(size_pt=6.2, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(
            surface,
            PdfRect(
                reference_rect.x_mm + 3.0, reference_rect.y_mm + 3.0, panel_width_mm - 6.0, 3.2
            ),
        ),
        TextBox(
            component_id=f"{prefix}-fingerprint-value",
            text=context.doc_id,
            style=FORGE_THEME.mono_style(size_pt=7.0, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                reference_rect.x_mm + 3.0, reference_rect.y_mm + 10.0, panel_width_mm - 6.0, 4.0
            ),
        ),
        TextBox(
            component_id=f"{prefix}-fingerprint-helper",
            text="Use this value to verify shard set integrity.",
            style=FORGE_THEME.sans_style(size_pt=6.0, color=FORGE_SLATE_700),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.05,
        ).plan(
            surface,
            PdfRect(
                reference_rect.x_mm + 3.0, reference_rect.y_mm + 17.0, panel_width_mm - 6.0, 8.0
            ),
        ),
        Panel(
            component_id=f"{prefix}-specs-table",
            stroke=FORGE_SLATE_300,
            fill=FORGE_WHITE,
            line_width_mm=0.2,
        ).plan(surface, specs_rect),
        TextBox(
            component_id=f"{prefix}-specs-title",
            text="03. SPECIFICATIONS",
            style=FORGE_THEME.sans_style(size_pt=6.2, bold=True, color=FORGE_SLATE_900),
            policy=TextFitPolicy.FAIL,
        ).plan(
            surface,
            PdfRect(specs_rect.x_mm + 3.0, specs_rect.y_mm + 3.0, panel_width_mm - 6.0, 3.2),
        ),
        TextBox(
            component_id=f"{prefix}-specs-summary",
            text=(
                f"SCHEMA: SHAMIR\nTHRESHOLD: {_context_int(context, 'shard_threshold')} OF "
                f"{_context_int(context, 'shard_total')}\nENCODING: QR + Z-BASE-32"
            ),
            style=FORGE_THEME.mono_style(size_pt=6.0, color=FORGE_SLATE_800),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.08,
        ).plan(
            surface,
            PdfRect(specs_rect.x_mm + 3.0, specs_rect.y_mm + 9.0, panel_width_mm - 6.0, 16.0),
        ),
    ]


def _intact_notice_plans(
    surface: PdfSurface,
    page_number: int,
    *,
    geometry: _ForgeSigningKeyShardGeometry,
) -> list[PaintPlan]:
    prefix = component_prefix(_COMPONENT_BASE, page_number)
    return [
        TextBox(
            component_id=f"{prefix}-intact-notice",
            text="Valid only if physically intact. Verify checksums before restoration.",
            style=FORGE_THEME.sans_style(size_pt=6.0, color=FORGE_SLATE_700),
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, geometry.intact_notice_rect),
    ]


def _payload_corner_plans(
    surface: PdfSurface,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    size = 3.2
    return [
        Panel(
            component_id=f"{prefix}-payload-corner-tl",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(rect.x_mm, rect.y_mm, size, size)),
        Panel(
            component_id=f"{prefix}-payload-corner-tr",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(rect.right_mm - size, rect.y_mm, size, size)),
        Panel(
            component_id=f"{prefix}-payload-corner-bl",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(rect.x_mm, rect.bottom_mm - size, size, size)),
        Panel(
            component_id=f"{prefix}-payload-corner-br",
            stroke=FORGE_SLATE_900,
            fill=FORGE_SLATE_900,
            line_width_mm=0.2,
        ).plan(surface, PdfRect(rect.right_mm - size, rect.bottom_mm - size, size, size)),
    ]


def _dashed_border_plans(
    surface: PdfSurface,
    prefix: str,
    rect: PdfRect,
    color: PdfColor,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = []
    dash = 1.8
    gap = 1.4
    thickness = 0.25

    x = rect.x_mm
    index = 0
    while x < rect.right_mm:
        width = min(dash, rect.right_mm - x)
        plans.append(
            Rule(
                component_id=f"{prefix}-top-{index}",
                color=color,
            ).plan(surface, PdfRect(x, rect.y_mm, width, thickness))
        )
        plans.append(
            Rule(
                component_id=f"{prefix}-bottom-{index}",
                color=color,
            ).plan(surface, PdfRect(x, rect.bottom_mm - thickness, width, thickness))
        )
        x += dash + gap
        index += 1

    y = rect.y_mm
    index = 0
    while y < rect.bottom_mm:
        height = min(dash, rect.bottom_mm - y)
        plans.append(
            Rule(
                component_id=f"{prefix}-left-{index}",
                color=color,
            ).plan(surface, PdfRect(rect.x_mm, y, thickness, height))
        )
        plans.append(
            Rule(
                component_id=f"{prefix}-right-{index}",
                color=color,
            ).plan(surface, PdfRect(rect.right_mm - thickness, y, thickness, height))
        )
        y += dash + gap
        index += 1
    return plans


def _context_int(context: ForgeShellContext, key: str) -> int:
    value = context.values.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


__all__ = [
    "ForgeSigningKeyShardDirectPlan",
    "build_forge_signing_key_shard_direct_plan",
    "render_forge_signing_key_shard_direct_pdf",
]
