"""Shared Forge direct-PDF shell helpers.

These helpers centralize the Forge document chrome used by direct renderers: colors, page
constants, timestamp/doc-id normalization, copy lookup, and measured header/footer components.
Document-specific renderers own their content areas and proof construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from ethernity.render.copy_catalog import build_copy_bundle
from ethernity.render.direct_pdf.components import Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.forge_preview import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.forge_theme import FORGE_THEME
from ethernity.render.direct_pdf.page import PaintPlan
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.doc_types import (
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_SHARD,
)
from ethernity.render.spec import document_spec
from ethernity.render.types import RenderInputs, RenderLineage
from ethernity.version import get_ethernity_version

FORGE_PAGE_RECT = PdfRect(0.0, 0.0, A4_WIDTH_MM, A4_HEIGHT_MM)
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


def build_forge_shell_context(inputs: RenderInputs, *, doc_type: str) -> ForgeShellContext:
    """Build Forge shell context from existing render inputs and copy catalogs."""

    base_context = dict(inputs.context)
    created_timestamp_utc = resolve_created_timestamp(base_context)
    doc_id = resolve_doc_id(inputs, base_context)
    base_context["doc_id"] = doc_id
    base_context["lineage"] = lineage_payload(inputs.lineage)

    spec = document_spec(doc_type, "A4", base_context)
    copy = build_copy_bundle(doc_type=doc_type, context=base_context)
    return ForgeShellContext(
        doc_type=doc_type,
        doc_id=doc_id,
        created_timestamp_utc=created_timestamp_utc,
        copy=copy,
        instructions_label=spec.instructions.label or "Instructions",
        instruction_lines=tuple(spec.instructions.lines),
        footer_left=generator_label(get_ethernity_version()),
        footer_right=str(copy.get("footer_guidance") or ""),
        lineage=inputs.lineage,
        values=base_context,
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
        created_timestamp_utc, created_dt = _timestamp_from_string(created_value)

    if created_timestamp_utc is None:
        created_dt = created_dt or datetime.now(timezone.utc)
        created_timestamp_utc = created_dt.strftime("%Y-%m-%d %H:%M UTC")

    base_context["created_timestamp_utc"] = created_timestamp_utc
    if created_dt is not None:
        base_context["created_date"] = created_dt.date().isoformat()
    return created_timestamp_utc


def resolve_doc_id(inputs: RenderInputs, base_context: dict[str, object]) -> str:
    """Resolve the document id shown in Forge headers."""

    doc_id = base_context.get("doc_id")
    if isinstance(doc_id, str) and doc_id.strip():
        return doc_id.strip()
    if not inputs.frames:
        raise ValueError("doc_id context is required when rendering without frames")
    return inputs.frames[0].doc_id.hex()


def lineage_payload(lineage: RenderLineage) -> dict[str, object]:
    """Convert render lineage to the mapping expected by the copy catalog."""

    return {
        "kind": lineage.kind,
        "extension_index": lineage.extension_index,
    }


def generator_label(ethernity_version: str) -> str:
    """Build the generator label shown in rendered document metadata."""

    normalized = ethernity_version.strip()
    if normalized:
        return f"Ethernity v{normalized}"
    return "Ethernity"


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
) -> list[PaintPlan]:
    """Build measured Forge header plans for a direct-PDF page."""

    prefix = forge_component_prefix(component_base, page_number)
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
        min_size_pt=5.0,
    ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, subtitle_y, text_column_width_mm, 5.6))
    plans.append(subtitle_plan)

    content_bottom_y = subtitle_plan.proof.used_rect.bottom_mm
    if guidance.strip():
        guidance_y = content_bottom_y + 2.1
        guidance_plan = TextBox(
            component_id=f"{prefix}-header-guidance",
            text=guidance.upper(),
            style=FORGE_THEME.sans_style(size_pt=5.8, color=FORGE_SLATE_500),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=4.5,
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
                ).plan(surface, PdfRect(130.5, 15.0, 10.6, 10.6)),
                TextBox(
                    component_id=f"{prefix}-header-icon",
                    text=resolved_icon,
                    style=FORGE_THEME.symbol_style(size_pt=14.0, color=FORGE_SLATE_900),
                    policy=TextFitPolicy.SHRINK,
                    align=TextAlign.CENTER,
                    min_size_pt=8.0,
                ).plan(surface, PdfRect(130.5, 15.8, 10.6, 9.0)),
            ]
        )

    plans.extend(
        [
            Panel(
                component_id=f"{prefix}-classification-pill",
                stroke=FORGE_SLATE_900,
                fill=FORGE_WHITE,
                line_width_mm=0.2,
            ).plan(surface, PdfRect(145.0, 15.0, 50.0, 5.5)),
            TextBox(
                component_id=f"{prefix}-classification-text",
                text=classification.upper(),
                style=FORGE_THEME.mono_style(size_pt=5.8, bold=True, color=FORGE_SLATE_900),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.CENTER,
                min_size_pt=4.5,
            ).plan(surface, PdfRect(146.0, 15.9, 48.0, 3.8)),
            TextBox(
                component_id=f"{prefix}-header-doc-id",
                text=f"DOC ID: {context.doc_id}",
                style=FORGE_THEME.mono_style(size_pt=6.2, color=FORGE_SLATE_600),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.RIGHT,
                min_size_pt=4.8,
            ).plan(surface, PdfRect(123.0, 22.3, 72.0, 4.6)),
            TextBox(
                component_id=f"{prefix}-header-generated",
                text=f"GENERATED (UTC): {context.created_timestamp_utc}",
                style=FORGE_THEME.mono_style(
                    size_pt=FORGE_THEME.text.header_meta_pt,
                    color=FORGE_SLATE_600,
                ),
                policy=TextFitPolicy.SHRINK,
                align=TextAlign.RIGHT,
                min_size_pt=4.6,
            ).plan(surface, PdfRect(123.0, 27.2, 72.0, 4.5)),
            TextBox(
                component_id=f"{prefix}-header-page-label",
                text=page_label,
                style=FORGE_THEME.mono_style(
                    size_pt=FORGE_THEME.text.header_meta_pt,
                    color=FORGE_SLATE_600,
                ),
                policy=TextFitPolicy.FAIL,
                align=TextAlign.RIGHT,
            ).plan(surface, PdfRect(145.0, 32.0, 50.0, 4.5)),
            Rule(
                component_id=f"{prefix}-header-rule",
                color=FORGE_SLATE_900,
            ).plan(surface, PdfRect(FORGE_CONTENT_X_MM, rule_y, FORGE_CONTENT_WIDTH_MM, 1.05)),
        ]
    )
    return plans


def build_forge_footer_plans(
    surface: PdfSurface,
    context: ForgeShellContext,
    *,
    page_label: str,
    page_number: int,
    component_base: str,
) -> list[PaintPlan]:
    """Build measured Forge footer plans for a direct-PDF page."""

    prefix = forge_component_prefix(component_base, page_number)
    mono_style = FORGE_THEME.mono_style(
        size_pt=FORGE_THEME.text.footer_pt,
        color=FORGE_SLATE_500,
    )
    return [
        Rule(
            component_id=f"{prefix}-footer-rule",
            color=FORGE_SLATE_300,
        ).plan(surface, PdfRect(15.0, 263.0, 180.0, 0.35)),
        TextBox(
            component_id=f"{prefix}-footer-left",
            text=context.footer_left.upper(),
            style=mono_style,
            policy=TextFitPolicy.SHRINK,
            min_size_pt=4.4,
        ).plan(surface, PdfRect(15.0, 269.0, 60.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-footer-page",
            text=page_label,
            style=mono_style,
            policy=TextFitPolicy.FAIL,
            align=TextAlign.CENTER,
        ).plan(surface, PdfRect(82.0, 269.0, 46.0, 5.5)),
        TextBox(
            component_id=f"{prefix}-footer-right",
            text=context.footer_right.upper(),
            style=mono_style,
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=4.2,
        ).plan(surface, PdfRect(130.0, 269.0, 65.0, 5.5)),
    ]


def forge_component_prefix(component_base: str, page_number: int) -> str:
    """Return a stable component id prefix for Forge page components."""

    return f"{component_base}-p{page_number}"


def _forge_header_kicker_text(context: ForgeShellContext) -> str:
    if context.doc_type in {DOC_TYPE_KIT_INDEX, DOC_TYPE_SHARD}:
        return FORGE_HEADER_KICKER
    return ""


def _forge_header_icon_text(context: ForgeShellContext) -> str:
    if context.doc_type == DOC_TYPE_KIT_INDEX:
        return FORGE_ICON_INVENTORY
    return ""


def _timestamp_from_string(value: str) -> tuple[str | None, datetime | None]:
    created_value = value.strip()
    if not created_value:
        return None, None

    parsed_value = created_value
    if created_value.endswith(" UTC"):
        parsed_value = f"{created_value[:-4].strip()}+00:00"
    elif created_value.endswith("Z"):
        parsed_value = f"{created_value[:-1]}+00:00"
    try:
        parsed_dt = datetime.fromisoformat(parsed_value)
    except ValueError:
        parsed_dt = None
    if parsed_dt is not None:
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        return None, parsed_dt.astimezone(timezone.utc)
    if "UTC" in created_value or created_value.endswith("Z"):
        return created_value, None
    return f"{created_value} UTC", None


__all__ = [
    "FORGE_CONTENT_WIDTH_MM",
    "FORGE_CONTENT_X_MM",
    "FORGE_HEADER_KICKER",
    "FORGE_ICON_INVENTORY",
    "FORGE_ICON_TOKEN",
    "FORGE_MONO_FONT",
    "FORGE_PAGE_RECT",
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
    "ForgeShellContext",
    "build_forge_footer_plans",
    "build_forge_header_plans",
    "build_forge_shell_context",
    "forge_component_prefix",
    "generator_label",
    "lineage_payload",
    "resolve_created_timestamp",
    "resolve_doc_id",
]
