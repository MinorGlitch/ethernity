"""Shared direct-PDF primitives for the Ledger and Maritime designs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.render.direct_pdf.components import Panel, TextBox
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    PaintPlan,
    SeparationConstraint,
)
from ethernity.render.direct_pdf.page_geometry import PageGeometry, resolve_page_geometry
from ethernity.render.direct_pdf.responsive_layout import (
    GridPolicy,
    Insets,
    PageRegions,
    ResolvedGrid,
    resolve_grid,
    resolve_page_regions,
)
from ethernity.render.direct_pdf.structured_common import (
    FallbackPage,
    FallbackPageEntry,
    FallbackTitleEntry,
)
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.types import RenderInputs


@dataclass(frozen=True)
class ClassicLayout:
    """Page geometry shared by the two classic direct-PDF designs."""

    page: PageGeometry
    regions: PageRegions

    @property
    def safe_rect(self) -> PdfRect:
        return self.regions.safe

    @property
    def content_rect(self) -> PdfRect:
        return self.regions.body


@dataclass(frozen=True)
class ClassicPageStyle:
    """Family-supplied page insets for a classic design."""

    margin_mm: float
    content_bottom_inset_mm: float


@dataclass(frozen=True)
class ClassicQrGridStyle:
    """Family-supplied dimensions for a classic QR card grid."""

    max_columns: int
    preferred_card_size_mm: float
    minimum_card_size_mm: float
    gap_mm: float


@dataclass(frozen=True)
class ClassicInstructionStyle:
    """Family-supplied palette for shared recovery-kit instruction blocks."""

    ink: PdfColor
    rule: PdfColor
    strong_rule: PdfColor
    tab: PdfColor
    white: PdfColor
    section_accent: PdfColor
    section_fill: PdfColor


def resolve_classic_layout(
    inputs: RenderInputs,
    *,
    style: ClassicPageStyle,
) -> ClassicLayout:
    """Resolve page and content geometry using classic design insets."""

    page = resolve_page_geometry(inputs)
    regions = resolve_page_regions(
        page.rect,
        safe_insets=Insets.uniform(style.margin_mm),
        header_height_mm=0.0,
        footer_height_mm=2.0,
        body_footer_gap_mm=style.content_bottom_inset_mm - 2.0,
    )
    return ClassicLayout(page=page, regions=regions)


def resolve_qr_grid(
    layout: ClassicLayout,
    *,
    top_mm: float,
    preferred_rows: int,
    style: ClassicQrGridStyle,
) -> ResolvedGrid:
    """Resolve a QR grid within a classic design's content rectangle."""

    container = PdfRect(
        layout.content_rect.x_mm,
        top_mm,
        layout.content_rect.width_mm,
        layout.content_rect.bottom_mm - top_mm,
    )
    return resolve_grid(
        container,
        GridPolicy(
            max_columns=style.max_columns,
            max_rows=preferred_rows,
            preferred_item_width_mm=style.preferred_card_size_mm,
            preferred_item_height_mm=style.preferred_card_size_mm,
            minimum_item_width_mm=style.minimum_card_size_mm,
            minimum_item_height_mm=style.minimum_card_size_mm,
            minimum_column_gap_mm=style.gap_mm,
            minimum_row_gap_mm=style.gap_mm,
            preserve_item_aspect_ratio=True,
            horizontal_distribution="center",
            vertical_distribution="start",
        ),
    )


def build_group_clearance_constraint(
    *,
    prefix: str,
    first_group_id: str,
    first_plans: Sequence[PaintPlan],
    second_group_id: str,
    second_plans: Sequence[PaintPlan],
    clearance_mm: float,
) -> SeparationConstraint:
    """Require clearance between two named component groups."""

    return SeparationConstraint(
        constraint_id=f"{prefix}-{first_group_id}-{second_group_id}-clearance",
        first=ComponentGroup(
            group_id=f"{prefix}-{first_group_id}",
            component_ids=tuple(plan.component_id for plan in first_plans),
        ),
        second=ComponentGroup(
            group_id=f"{prefix}-{second_group_id}",
            component_ids=tuple(plan.component_id for plan in second_plans),
        ),
        minimum_clearance_mm=clearance_mm,
    )


def build_page_background(
    surface: PdfSurface,
    *,
    layout: ClassicLayout,
    prefix: str,
    fill: PdfColor,
) -> list[PaintPlan]:
    """Build the full-page paper background for a classic design."""

    return [
        Panel(component_id=f"{prefix}-page-bg", fill=fill, line_width_mm=0.2).plan(
            surface,
            layout.page.rect,
        )
    ]


def group_fallback_visual_blocks(
    fallback_page: FallbackPage,
) -> tuple[tuple[FallbackPageEntry, ...], ...]:
    """Group fallback rows into visually indivisible title-led blocks."""

    blocks: list[list[FallbackPageEntry]] = []
    current: list[FallbackPageEntry] = []
    for page_entry in fallback_page.entries:
        if isinstance(page_entry.entry, FallbackTitleEntry) and current:
            blocks.append(current)
            current = []
        current.append(page_entry)
    if current:
        blocks.append(current)
    return tuple(tuple(block) for block in blocks)


def build_instruction_steps_section(
    surface: PdfSurface,
    *,
    prefix: str,
    title: str,
    lines: Sequence[str],
    rect: PdfRect,
    index: int,
    style: ClassicInstructionStyle,
) -> list[PaintPlan]:
    """Build a titled sequence of icon-led recovery-kit steps."""

    plans = _instruction_section_label(
        surface,
        prefix=prefix,
        title=title,
        rect=rect,
        index=index,
        style=style,
    )
    y_mm = rect.y_mm + 12.0
    for line_index, line in enumerate(lines):
        plans.append(
            Panel(
                component_id=f"{prefix}-step-icon-{index}-{line_index}",
                stroke=style.strong_rule,
                fill=style.tab,
                line_width_mm=0.35,
            ).plan(surface, PdfRect(rect.x_mm, y_mm + 0.6, 4.0, 4.0))
        )
        plans.append(
            Panel(
                component_id=f"{prefix}-step-icon-inner-{index}-{line_index}",
                stroke=style.rule,
                fill=None,
                line_width_mm=0.25,
            ).plan(surface, PdfRect(rect.x_mm + 0.7, y_mm + 1.3, 2.6, 2.6))
        )
        text_plan = TextBox(
            component_id=f"{prefix}-step-text-{index}-{line_index}",
            text=line,
            style=body_text_style(size_pt=8.8, color=style.ink),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.24,
        ).plan(surface, PdfRect(rect.x_mm + 8.0, y_mm - 0.3, rect.width_mm - 8.0, 13.0))
        plans.append(text_plan)
        y_mm += max(9.0, text_plan.proof.used_rect.height_mm + 2.0)
    return plans


def build_instruction_bullets_section(
    surface: PdfSurface,
    *,
    prefix: str,
    title: str,
    lines: Sequence[str],
    rect: PdfRect,
    index: int,
    style: ClassicInstructionStyle,
) -> list[PaintPlan]:
    """Build a titled sequence of bullet-led recovery-kit notes."""

    plans = _instruction_section_label(
        surface,
        prefix=prefix,
        title=title,
        rect=rect,
        index=index,
        style=style,
    )
    y_mm = rect.y_mm + 12.0
    for line_index, line in enumerate(lines):
        plans.append(
            Panel(
                component_id=f"{prefix}-bullet-marker-{index}-{line_index}",
                fill=style.ink,
                line_width_mm=0.2,
            ).plan(surface, PdfRect(rect.x_mm + 1.2, y_mm + 1.7, 0.8, 0.8))
        )
        text_plan = TextBox(
            component_id=f"{prefix}-bullet-text-{index}-{line_index}",
            text=line,
            style=body_text_style(size_pt=8.8, color=style.ink),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.25,
        ).plan(surface, PdfRect(rect.x_mm + 6.0, y_mm - 0.2, rect.width_mm - 6.0, 12.0))
        plans.append(text_plan)
        y_mm += max(8.4, text_plan.proof.used_rect.height_mm + 1.8)
    return plans


def build_instruction_checklist(
    surface: PdfSurface,
    *,
    prefix: str,
    rect: PdfRect,
    style: ClassicInstructionStyle,
) -> list[PaintPlan]:
    """Build the common recovery-kit verification checklist."""

    lines = (
        "All QR pages scanned in order.",
        "Bundle file saved with the correct name.",
        "Kit opens offline without errors.",
        "Recovery completed and data verified.",
    )
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-checklist",
            stroke=style.rule,
            fill=style.white,
            line_width_mm=0.35,
        ).plan(surface, rect)
    ]
    y_mm = rect.y_mm + 4.0
    for line_index, line in enumerate(lines):
        plans.append(
            Panel(
                component_id=f"{prefix}-check-box-{line_index}",
                stroke=style.strong_rule,
                fill=style.white,
                line_width_mm=0.35,
            ).plan(surface, PdfRect(rect.x_mm + 3.0, y_mm + 0.4, 3.4, 3.4))
        )
        text_plan = TextBox(
            component_id=f"{prefix}-check-text-{line_index}",
            text=line,
            style=body_text_style(size_pt=8.2, color=style.ink),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.18,
        ).plan(surface, PdfRect(rect.x_mm + 9.0, y_mm - 0.1, rect.width_mm - 12.0, 10.0))
        plans.append(text_plan)
        y_mm += max(10.0, text_plan.proof.used_rect.height_mm + 2.0)
    return plans


def title_text_style(
    *,
    size_pt: float,
    color: PdfColor,
    char_spacing_mm: float,
) -> TextStyle:
    """Build the serif title style shared by the classic designs."""

    return TextStyle(
        family="Times",
        size_pt=size_pt,
        style="B",
        color=color,
        char_spacing_mm=char_spacing_mm,
    )


def body_text_style(
    *,
    size_pt: float,
    color: PdfColor,
    bold: bool = False,
    char_spacing_mm: float = 0.0,
) -> TextStyle:
    """Build the sans-serif body style shared by the classic designs."""

    return TextStyle(
        family="Helvetica",
        size_pt=size_pt,
        style="B" if bold else "",
        color=color,
        char_spacing_mm=char_spacing_mm,
    )


def monospace_text_style(
    *,
    size_pt: float,
    color: PdfColor,
    bold: bool = False,
    char_spacing_mm: float = 0.0,
) -> TextStyle:
    """Build the monospace style shared by the classic designs."""

    return TextStyle(
        family="Courier",
        size_pt=size_pt,
        style="B" if bold else "",
        color=color,
        char_spacing_mm=char_spacing_mm,
    )


def _instruction_section_label(
    surface: PdfSurface,
    *,
    prefix: str,
    title: str,
    rect: PdfRect,
    index: int,
    style: ClassicInstructionStyle,
) -> list[PaintPlan]:
    label_rect = PdfRect(rect.x_mm, rect.y_mm, rect.width_mm, 6.0)
    return [
        Panel(
            component_id=f"{prefix}-section-label-box-{index}",
            stroke=style.section_accent,
            fill=style.section_fill,
            line_width_mm=0.35,
        ).plan(surface, label_rect),
        TextBox(
            component_id=f"{prefix}-section-label-{index}",
            text=title.upper(),
            style=title_text_style(
                size_pt=8.0,
                color=style.section_accent,
                char_spacing_mm=0.28,
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(
            surface,
            PdfRect(
                label_rect.x_mm + 1.4,
                label_rect.y_mm + 1.15,
                label_rect.width_mm - 2.8,
                3.8,
            ),
        ),
    ]


__all__ = [
    "ClassicInstructionStyle",
    "ClassicLayout",
    "ClassicPageStyle",
    "ClassicQrGridStyle",
    "body_text_style",
    "build_group_clearance_constraint",
    "build_instruction_bullets_section",
    "build_instruction_checklist",
    "build_instruction_steps_section",
    "build_page_background",
    "group_fallback_visual_blocks",
    "monospace_text_style",
    "resolve_classic_layout",
    "resolve_qr_grid",
    "title_text_style",
]
