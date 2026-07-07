"""Shared Sentinel direct-PDF shell helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from ethernity.render.copy_catalog import build_copy_bundle
from ethernity.render.direct_pdf.components import Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.page import PaintPlan
from ethernity.render.direct_pdf.sentinel_theme import SENTINEL_THEME
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitError, TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect
from ethernity.render.spec import document_spec
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


def build_sentinel_surface() -> FpdfSurface:
    """Create a PDF surface with Sentinel's page geometry."""

    layout = SENTINEL_THEME.layout
    return FpdfSurface(
        page_width_mm=layout.page_width_mm,
        page_height_mm=layout.page_height_mm,
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

    spec = document_spec(doc_type, "A4", base_context)
    copy = build_copy_bundle(doc_type=doc_type, context=base_context)
    return SentinelShellContext(
        doc_type=doc_type,
        doc_id=doc_id,
        created_timestamp_utc=created_timestamp_utc,
        created_date=created_date,
        copy=copy,
        instructions_label=spec.instructions.label or "Instructions",
        instruction_lines=tuple(spec.instructions.lines),
        footer_left=generator_label(get_ethernity_version()),
        footer_right=str(copy.get("footer_guidance") or ""),
        lineage=inputs.lineage,
        values=base_context,
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

    prefix = sentinel_component_prefix(component_base, page_number)
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

    prefix = sentinel_component_prefix(component_base, page_number)
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
            min_size_pt=4.0,
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


def sentinel_component_prefix(component_base: str, page_number: int) -> str:
    """Return a stable component id prefix for Sentinel page components."""

    return f"{component_base}-p{page_number}"


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
        created_timestamp_utc, created_dt = _timestamp_from_string(created_value)

    if created_timestamp_utc is None:
        created_dt = created_dt or datetime.now(timezone.utc)
        created_timestamp_utc = created_dt.strftime("%Y-%m-%d %H:%M UTC")

    base_context["created_timestamp_utc"] = created_timestamp_utc
    if created_dt is not None:
        base_context["created_date"] = created_dt.date().isoformat()
    return created_timestamp_utc


def resolve_doc_id(inputs: RenderInputs, base_context: dict[str, object]) -> str:
    """Resolve the document id shown in Sentinel headers."""

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
    "build_sentinel_corner_mark_plans",
    "build_sentinel_footer_plans",
    "build_sentinel_header_plans",
    "build_sentinel_shell_context",
    "build_sentinel_surface",
    "sentinel_component_prefix",
]
