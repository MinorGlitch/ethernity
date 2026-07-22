"""Shared Forge direct-PDF shell helpers.

These helpers centralize the Forge document chrome used by direct renderers: colors, page
constants, timestamp/doc-id normalization, copy lookup, and measured header/footer components.
Document-specific renderers own their content areas and proof construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from ethernity.render.copy_catalog import build_copy_bundle, build_instruction_copy
from ethernity.render.direct_pdf.components import Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.forge.theme import FORGE_THEME
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    LayoutRegion,
    PaintPlan,
    SeparationConstraint,
)
from ethernity.render.direct_pdf.page_geometry import PageGeometry, resolve_page_geometry
from ethernity.render.direct_pdf.responsive_layout import Insets, PageRegions, resolve_page_regions
from ethernity.render.direct_pdf.structured_common import (
    component_prefix,
    generator_label,
    lineage_payload,
    resolve_doc_id,
    timestamp_from_string,
)
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.doc_types import (
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_SHARD,
)
from ethernity.render.template_style import TemplateCapabilities, load_template_style
from ethernity.render.types import RenderInputs, RenderLineage
from ethernity.version import get_ethernity_version

FORGE_CONTENT_X_MM = FORGE_THEME.layout.content_x_mm
FORGE_CONTENT_WIDTH_MM = FORGE_THEME.layout.content_width_mm
FORGE_SERIF_FONT = FORGE_THEME.fonts.serif.pdf_family
FORGE_SANS_FONT = FORGE_THEME.fonts.sans.pdf_family
FORGE_MONO_FONT = FORGE_THEME.fonts.mono.pdf_family
FORGE_SYMBOLS_FONT = FORGE_THEME.fonts.symbols.pdf_family
FORGE_SLATE_50 = FORGE_THEME.palette.slate_50
FORGE_SLATE_100 = FORGE_THEME.palette.slate_100
FORGE_SLATE_200 = FORGE_THEME.palette.slate_200
FORGE_SLATE_300 = FORGE_THEME.palette.slate_300
FORGE_SLATE_500 = FORGE_THEME.palette.slate_500
FORGE_SLATE_600 = FORGE_THEME.palette.slate_600
FORGE_SLATE_700 = FORGE_THEME.palette.slate_700
FORGE_SLATE_800 = FORGE_THEME.palette.slate_800
FORGE_SLATE_900 = FORGE_THEME.palette.slate_900
FORGE_WHITE = FORGE_THEME.palette.white
FORGE_HEADER_KICKER = "The Forge // Secure Offline Storage"
FORGE_ICON_INVENTORY = chr(0xE1A1)
FORGE_ICON_TOKEN = chr(0xEA25)
_FORGE_SAFE_MARGIN_MM = 15.0
_FORGE_HEADER_HEIGHT_MM = 30.0
_FORGE_HEADER_BODY_GAP_MM = 2.0
_FORGE_FOOTER_HEIGHT_MM = 19.0
_FORGE_BODY_FOOTER_GAP_MM = 3.5
_FORGE_MINIMUM_CONTENT_WIDTH_MM = 180.0


@dataclass(frozen=True)
class ForgePageLayout:
    """Dimension-driven Forge shell regions for one portrait page.

    The page chrome keeps physical type and QR sizes stable.  Width changes are absorbed by the
    safe content region; height changes reduce or extend the body and therefore affect pagination,
    never a whole-page scale factor.
    """

    page: PageGeometry
    regions: PageRegions

    @property
    def content_rect(self) -> PdfRect:
        return PdfRect(
            self.regions.safe.x_mm,
            self.regions.body.y_mm,
            self.regions.safe.width_mm,
            self.regions.body.height_mm,
        )

    def centered_x(self, width_mm: float) -> float:
        """Center a fixed-physical-width component in the page safe region."""

        if width_mm <= 0 or width_mm > self.regions.safe.width_mm:
            raise ValueError(
                "Forge component width does not fit the page safe region: "
                f"{width_mm:.3f} > {self.regions.safe.width_mm:.3f} mm"
            )
        return self.regions.safe.x_mm + (self.regions.safe.width_mm - width_mm) / 2.0


@dataclass(frozen=True)
class ForgeHeaderPlan:
    """Measured Forge header chrome and its physical lower boundary."""

    plans: tuple[PaintPlan, ...]
    bottom_mm: float


def build_forge_page_layout(page: PageGeometry) -> ForgePageLayout:
    """Resolve Forge safe/header/body/footer regions from physical page dimensions."""

    regions = resolve_page_regions(
        page.rect,
        safe_insets=Insets.uniform(_FORGE_SAFE_MARGIN_MM),
        header_height_mm=_FORGE_HEADER_HEIGHT_MM,
        footer_height_mm=_FORGE_FOOTER_HEIGHT_MM,
        header_body_gap_mm=_FORGE_HEADER_BODY_GAP_MM,
        body_footer_gap_mm=_FORGE_BODY_FOOTER_GAP_MM,
    )
    if regions.safe.width_mm < _FORGE_MINIMUM_CONTENT_WIDTH_MM:
        raise ValueError(
            "Forge page is too narrow for legible content: "
            f"safe width {regions.safe.width_mm:.3f} mm; "
            f"minimum {_FORGE_MINIMUM_CONTENT_WIDTH_MM:.3f} mm"
        )
    return ForgePageLayout(page=page, regions=regions)


def build_forge_content_constraints(
    *,
    component_base: str,
    page_number: int,
    layout: ForgePageLayout,
    content_component_ids: tuple[str, ...],
    header_clearance_mm: float = 1.5,
    footer_clearance_mm: float = 3.0,
    header_bottom_mm: float | None = None,
) -> tuple[SeparationConstraint, ...]:
    """Prove that declared body components stay clear of Forge shell regions."""

    prefix = component_prefix(component_base, page_number)
    content = ComponentGroup(
        group_id=f"{prefix}-semantic-content",
        component_ids=content_component_ids,
    )
    header_region = layout.regions.header
    if header_bottom_mm is not None:
        if header_bottom_mm < header_region.y_mm:
            raise ValueError("Forge measured header bottom precedes the header region")
        header_region = PdfRect(
            header_region.x_mm,
            header_region.y_mm,
            header_region.width_mm,
            max(header_region.height_mm, header_bottom_mm - header_region.y_mm),
        )
    return (
        SeparationConstraint(
            constraint_id=f"{prefix}-content-after-header",
            first=content,
            second=LayoutRegion(
                region_id=f"{prefix}-header-safe-region",
                rect=header_region,
            ),
            minimum_clearance_mm=header_clearance_mm,
        ),
        SeparationConstraint(
            constraint_id=f"{prefix}-content-before-footer",
            first=content,
            second=LayoutRegion(
                region_id=f"{prefix}-footer-safe-region",
                rect=layout.regions.footer,
            ),
            minimum_clearance_mm=footer_clearance_mm,
        ),
    )


@dataclass(frozen=True)
class ForgeShellContext:
    """Shared copy and metadata used by Forge direct-PDF document shells."""

    doc_type: str
    doc_id: str
    created_timestamp_utc: str
    copy: dict[str, object]
    instructions_label: str
    instruction_lines: tuple[str, ...]
    footer_left: str
    footer_right: str
    lineage: RenderLineage
    values: dict[str, object]
    capabilities: TemplateCapabilities


def build_forge_shell_context(inputs: RenderInputs, *, doc_type: str) -> ForgeShellContext:
    """Build Forge shell context from existing render inputs and copy catalogs."""

    base_context = dict(inputs.context)
    created_timestamp_utc = resolve_created_timestamp(base_context)
    doc_id = resolve_doc_id(inputs, base_context)
    base_context["doc_id"] = doc_id
    base_context["lineage"] = lineage_payload(inputs.lineage)

    page = resolve_page_geometry(inputs)
    base_context["paper_size"] = page.paper_size
    copy = build_copy_bundle(doc_type=doc_type, context=base_context)
    instructions = build_instruction_copy(doc_type=doc_type, context=base_context)
    return ForgeShellContext(
        doc_type=doc_type,
        doc_id=doc_id,
        created_timestamp_utc=created_timestamp_utc,
        copy=copy,
        instructions_label=instructions.label,
        instruction_lines=instructions.lines,
        footer_left=generator_label(get_ethernity_version()),
        footer_right=str(copy.get("footer_guidance") or ""),
        lineage=inputs.lineage,
        values=base_context,
        capabilities=load_template_style(inputs.design_name).capabilities,
    )


def resolve_created_timestamp(base_context: dict[str, object]) -> str:
    """Normalize created timestamp fields for direct Forge display."""

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


def build_forge_header_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_label: str,
    page_number: int,
    component_base: str,
    classification_default: str,
    kicker_text: str | None = None,
    icon_text: str | None = None,
    classification_override: str | None = None,
    title_default: str = "Document",
    subtitle_default: str = "",
    page_rect: PdfRect,
) -> list[PaintPlan]:
    """Build measured Forge header plans for a direct-PDF page."""

    prefix = component_prefix(component_base, page_number)
    title = str(context.copy.get("title") or title_default)
    subtitle = str(context.copy.get("subtitle") or subtitle_default)
    guidance = str(context.copy.get("header_guidance") or "")
    classification = str(
        classification_override
        if classification_override is not None
        else context.copy.get("lineage_badge") or classification_default
    )
    resolved_kicker = _forge_header_kicker_text(context) if kicker_text is None else kicker_text
    resolved_icon = _forge_header_icon_text(context) if icon_text is None else icon_text
    has_kicker = bool(resolved_kicker.strip())
    has_icon = bool(resolved_icon.strip())
    content_width_mm = page_rect.width_mm - 2 * FORGE_CONTENT_X_MM
    content_right_mm = page_rect.right_mm - FORGE_CONTENT_X_MM
    classification_x_mm = content_right_mm - 50.0
    meta_x_mm = content_right_mm - 72.0

    title_y = 20.5 if has_kicker else 15.0
    minimum_rule_y = 50.4 if has_kicker else 43.8

    plans: list[PaintPlan] = []
    if has_kicker:
        plans.append(
            TextBox(
                component_id=f"{prefix}-header-kicker",
                text=resolved_kicker.upper(),
                style=FORGE_THEME.sans_style(size_pt=7.2, bold=True, color=FORGE_SLATE_500),
                policy=TextFitPolicy.FAIL,
            ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, 15.2, 100.0, 4.6))
        )

    text_column_width_mm = 106.0
    title_plan = TextBox(
        component_id=f"{prefix}-header-title",
        text=title.upper(),
        style=FORGE_THEME.serif_style(
            size_pt=FORGE_THEME.text.header_title_pt,
            bold=True,
            color=FORGE_SLATE_900,
        ),
        policy=TextFitPolicy.SHRINK,
        min_size_pt=17.0,
    ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, title_y, text_column_width_mm, 23.5))
    plans.append(title_plan)

    subtitle_y = title_plan.proof.used_rect.bottom_mm + 2.1
    subtitle_plan = TextBox(
        component_id=f"{prefix}-header-subtitle",
        text=subtitle,
        style=FORGE_THEME.sans_style(
            size_pt=FORGE_THEME.text.header_subtitle_pt,
            color=FORGE_SLATE_600,
        ),
        policy=TextFitPolicy.SHRINK,
        min_size_pt=6.0,
    ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, subtitle_y, text_column_width_mm, 5.6))
    plans.append(subtitle_plan)

    content_bottom_y = subtitle_plan.proof.used_rect.bottom_mm
    if guidance.strip():
        guidance_y = content_bottom_y + 2.1
        guidance_plan = TextBox(
            component_id=f"{prefix}-header-guidance",
            text=guidance.upper(),
            style=FORGE_THEME.sans_style(size_pt=6.0, color=FORGE_SLATE_500),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, guidance_y, text_column_width_mm, 4.0))
        plans.append(guidance_plan)
        content_bottom_y = guidance_plan.proof.used_rect.bottom_mm

    rule_y = max(minimum_rule_y, content_bottom_y + 6.8)

    if has_icon:
        plans.extend(
            [
                Panel(
                    component_id=f"{prefix}-header-icon-box",
                    stroke=FORGE_SLATE_900,
                    fill=FORGE_SLATE_50,
                    line_width_mm=0.2,
                ).plan(surface, PdfRect(classification_x_mm - 14.5, 15.0, 10.6, 10.6)),
                TextBox(
                    component_id=f"{prefix}-header-icon",
                    text=resolved_icon,
                    style=FORGE_THEME.symbol_style(size_pt=14.0, color=FORGE_SLATE_900),
                    policy=TextFitPolicy.SHRINK,
                    align=TextAlign.CENTER,
                    min_size_pt=8.0,
                ).plan(surface, PdfRect(classification_x_mm - 14.5, 15.8, 10.6, 9.0)),
            ]
        )

    plans.extend(
        [
            Panel(
                component_id=f"{prefix}-classification-pill",
                stroke=FORGE_SLATE_900,
                fill=FORGE_WHITE,
                line_width_mm=0.2,
            ).plan(surface, PdfRect(classification_x_mm, 15.0, 50.0, 5.5)),
            TextBox(
                component_id=f"{prefix}-classification-text",
                text=classification.upper(),
                style=FORGE_THEME.mono_style(size_pt=6.0, bold=True, color=FORGE_SLATE_900),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.CENTER,
                min_size_pt=6.0,
            ).plan(surface, PdfRect(classification_x_mm + 1.0, 15.9, 48.0, 3.8)),
            TextBox(
                component_id=f"{prefix}-header-doc-id",
                text=f"DOC ID: {context.doc_id}",
                style=FORGE_THEME.mono_style(size_pt=6.2, color=FORGE_SLATE_600),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.RIGHT,
                min_size_pt=6.0,
            ).plan(surface, PdfRect(meta_x_mm, 22.3, 72.0, 4.6)),
            TextBox(
                component_id=f"{prefix}-header-generated",
                text=f"GENERATED (UTC): {context.created_timestamp_utc}",
                style=FORGE_THEME.mono_style(
                    size_pt=FORGE_THEME.text.header_meta_pt,
                    color=FORGE_SLATE_600,
                ),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.RIGHT,
                min_size_pt=6.0,
            ).plan(surface, PdfRect(meta_x_mm, 27.2, 72.0, 4.5)),
            TextBox(
                component_id=f"{prefix}-header-page-label",
                text=page_label,
                style=FORGE_THEME.mono_style(
                    size_pt=FORGE_THEME.text.header_meta_pt,
                    color=FORGE_SLATE_600,
                ),
                policy=TextFitPolicy.FAIL,
                align=TextAlign.RIGHT,
            ).plan(surface, PdfRect(classification_x_mm, 32.0, 50.0, 4.5)),
            Rule(
                component_id=f"{prefix}-header-rule",
                color=FORGE_SLATE_900,
            ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, rule_y, content_width_mm, 1.05)),
        ]
    )
    return plans


def build_forge_header_plan(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_label: str,
    page_number: int,
    component_base: str,
    classification_default: str,
    kicker_text: str | None = None,
    icon_text: str | None = None,
    classification_override: str | None = None,
    title_default: str = "Document",
    subtitle_default: str = "",
    page_rect: PdfRect,
) -> ForgeHeaderPlan:
    """Build Forge header plans together with their measured lower boundary."""

    plans = tuple(
        build_forge_header_plans(
            surface,
            context,
            page_label=page_label,
            page_number=page_number,
            component_base=component_base,
            classification_default=classification_default,
            kicker_text=kicker_text,
            icon_text=icon_text,
            classification_override=classification_override,
            title_default=title_default,
            subtitle_default=subtitle_default,
            page_rect=page_rect,
        )
    )
    prefix = component_prefix(component_base, page_number)
    header_rule = next(plan for plan in plans if plan.component_id == f"{prefix}-header-rule")
    return ForgeHeaderPlan(plans=plans, bottom_mm=header_rule.proof.rect.bottom_mm)


def build_forge_footer_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_label: str,
    page_number: int,
    component_base: str,
    page_rect: PdfRect,
) -> list[PaintPlan]:
    """Build measured Forge footer plans for a direct-PDF page."""

    prefix = component_prefix(component_base, page_number)
    mono_style = FORGE_THEME.mono_style(
        size_pt=FORGE_THEME.text.footer_pt,
        color=FORGE_SLATE_500,
    )
    content_width_mm = page_rect.width_mm - 2 * FORGE_CONTENT_X_MM
    footer_rule_y_mm = page_rect.height_mm - 34.0
    footer_text_y_mm = page_rect.height_mm - 28.0
    return [
        Rule(
            component_id=f"{prefix}-footer-rule",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, footer_rule_y_mm, content_width_mm, 0.35)),
        TextBox(
            component_id=f"{prefix}-footer-left",
            text=context.footer_left.upper(),
            style=mono_style,
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, footer_text_y_mm, 60.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-footer-page",
            text=page_label,
            style=mono_style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(
            surface,
            PdfRect((page_rect.width_mm - 46.0) / 2.0, footer_text_y_mm, 46.0, 5.5),
        ),
        TextBox(
            component_id=f"{prefix}-footer-right",
            text=context.footer_right.upper(),
            style=mono_style,
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(page_rect.right_mm - FORGE_CONTENT_X_MM - 65.0, footer_text_y_mm, 65.0, 5.5),
        ),
    ]


def _forge_header_kicker_text(context: ForgeShellContext) -> str:
    if context.doc_type in {DOC_TYPE_KIT_INDEX, DOC_TYPE_SHARD}:
        return FORGE_HEADER_KICKER
    return ""


def _forge_header_icon_text(context: ForgeShellContext) -> str:
    if context.doc_type == DOC_TYPE_KIT_INDEX:
        return FORGE_ICON_INVENTORY
    return ""


__all__ = [
    "FORGE_CONTENT_WIDTH_MM",
    "FORGE_CONTENT_X_MM",
    "FORGE_HEADER_KICKER",
    "FORGE_ICON_INVENTORY",
    "FORGE_ICON_TOKEN",
    "FORGE_MONO_FONT",
    "FORGE_SANS_FONT",
    "FORGE_SERIF_FONT",
    "FORGE_SLATE_100",
    "FORGE_SLATE_200",
    "FORGE_SLATE_300",
    "FORGE_SLATE_50",
    "FORGE_SLATE_500",
    "FORGE_SLATE_600",
    "FORGE_SLATE_700",
    "FORGE_SLATE_800",
    "FORGE_SLATE_900",
    "FORGE_SYMBOLS_FONT",
    "FORGE_WHITE",
    "ForgePageLayout",
    "ForgeHeaderPlan",
    "ForgeShellContext",
    "build_forge_content_constraints",
    "build_forge_footer_plans",
    "build_forge_header_plans",
    "build_forge_header_plan",
    "build_forge_page_layout",
    "build_forge_shell_context",
    "explicit_creation_date",
    "resolve_created_timestamp",
]
