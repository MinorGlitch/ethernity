"""Shared recovery-kit instruction page for the classic PDF designs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ethernity.render.direct_pdf import classic_layout, document_inputs
from ethernity.render.direct_pdf.components import Panel, Rule, TextAlign, TextBox
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan, build_page_plan
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect


@dataclass(frozen=True)
class ClassicKitInstructionStyle:
    """Design colors used by the shared instruction insert."""

    instructions: classic_layout.ClassicInstructionStyle
    paper: PdfColor
    surface: PdfColor
    note: PdfColor
    muted_ink: PdfColor


def build_classic_kit_instruction_page(
    surface: PdfSurface,
    context: document_inputs.DocumentRenderContext,
    *,
    layout: classic_layout.ClassicLayout,
    component_base: str,
    renderer_label: str,
    style: ClassicKitInstructionStyle,
    page_number: int,
    total_pages: int,
) -> DirectPdfPagePlan:
    """Build the common insert and constrain its explicit body and footer groups."""

    prefix = document_inputs.component_prefix(component_base, page_number)
    rect = layout.safe_rect
    shell_plans = [
        Panel(
            component_id=f"{prefix}-insert-shell",
            stroke=style.instructions.strong_rule,
            fill=style.surface,
            line_width_mm=0.45,
        ).plan(surface, rect),
        Panel(
            component_id=f"{prefix}-insert-inner-rule",
            stroke=style.instructions.strong_rule,
            fill=None,
            line_width_mm=0.35,
        ).plan(
            surface,
            PdfRect(rect.x_mm + 1.5, rect.y_mm + 1.5, rect.width_mm - 3.0, rect.height_mm - 3.0),
        ),
    ]
    body_plans = _instruction_body_plans(
        surface,
        style=style,
        renderer_label=renderer_label,
        prefix=prefix,
        rect=rect,
    )
    footer_plans = _instruction_insert_footer(
        surface,
        context,
        style=style,
        prefix=prefix,
        rect=rect,
        page_label=f"Page {page_number} / {total_pages}",
    )
    return build_page_plan(
        page_number=page_number,
        rect=layout.page.rect,
        plans=(
            *classic_layout.build_page_background(
                surface, layout=layout, prefix=prefix, fill=style.paper
            ),
            *shell_plans,
            *body_plans,
            *footer_plans,
        ),
        separation_constraints=(
            classic_layout.build_group_clearance_constraint(
                prefix=prefix,
                first_group_id="insert-body",
                first_plans=body_plans,
                second_group_id="insert-footer",
                second_plans=footer_plans,
                clearance_mm=3.0,
            ),
        ),
    )


def _instruction_body_plans(
    surface: PdfSurface,
    *,
    style: ClassicKitInstructionStyle,
    renderer_label: str,
    prefix: str,
    rect: PdfRect,
) -> list[PaintPlan]:
    inner_x = rect.x_mm + 8.0
    inner_right = rect.right_mm - 8.0
    inner_width = inner_right - inner_x
    right_width = 58.0
    right_x = inner_right - right_width - 6.0
    left_width = right_x - inner_x - 8.0
    footer_rule_y = rect.bottom_mm - 17.0
    checklist_y = rect.y_mm + 155.0
    checklist_height = min(56.0, footer_rule_y - 8.0 - checklist_y)
    if left_width < 80.0 or checklist_height < 44.0:
        raise ValueError(f"{renderer_label} recovery-kit insert has no usable two-column body")
    plans: list[PaintPlan] = [
        TextBox(
            component_id=f"{prefix}-insert-stamp",
            text="INSTRUCTION INSERT",
            style=classic_layout.title_text_style(
                size_pt=7.0, color=style.instructions.section_accent, char_spacing_pt=0.35
            ),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(inner_right - 41.0, rect.y_mm + 4.0, 39.0, 5.4)),
        TextBox(
            component_id=f"{prefix}-insert-title",
            text="HOW TO REBUILD THE RECOVERY KIT",
            style=classic_layout.title_text_style(
                size_pt=15.0, color=style.instructions.ink, char_spacing_pt=0.26
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=11.0,
        ).plan(surface, PdfRect(inner_x, rect.y_mm + 9.0, inner_width - 25.0, 8.0)),
        TextBox(
            component_id=f"{prefix}-insert-subtitle",
            text="Use this page after scanning the QR pages. Keep everything offline.",
            style=classic_layout.body_text_style(
                size_pt=9.0, color=style.muted_ink, char_spacing_pt=0.08
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=7.0,
        ).plan(surface, PdfRect(inner_x, rect.y_mm + 20.0, inner_width - 21.0, 4.5)),
        Rule(component_id=f"{prefix}-insert-hero-rule", color=style.instructions.strong_rule).plan(
            surface,
            PdfRect(inner_x, rect.y_mm + 28.2, inner_width, 0.55),
        ),
    ]
    plans.extend(
        classic_layout.build_instruction_steps_section(
            surface,
            prefix=prefix,
            title="Scan + Assemble",
            lines=(
                "Scan every QR code left to right, top to bottom.",
                "Save each decoded chunk in order. Do not insert spaces or blank lines.",
                "Concatenate the chunks into one continuous file.",
                "Name the file exactly: recovery_kit.bundle.html",
            ),
            rect=PdfRect(inner_x, rect.y_mm + 37.0, left_width, 64.0),
            index=1,
            style=style.instructions,
        )
    )
    plans.extend(
        classic_layout.build_instruction_steps_section(
            surface,
            prefix=prefix,
            title="Open the Kit",
            lines=(
                "Open recovery_kit.bundle.html in a browser while offline.",
                "If the file is large, wait for it to finish loading.",
                "Follow the on-screen prompts to recover your payload.",
            ),
            rect=PdfRect(inner_x, rect.y_mm + 90.0, left_width, 52.0),
            index=2,
            style=style.instructions,
        )
    )
    plans.extend(
        classic_layout.build_instruction_bullets_section(
            surface,
            prefix=prefix,
            title="Troubleshooting",
            lines=(
                "If the kit does not load, re-check chunk order and re-save the file.",
                "Try another browser if rendering stalls.",
                "Confirm the file size matches the sum of all QR chunks.",
            ),
            rect=PdfRect(inner_x, rect.y_mm + 137.0, left_width, 44.0),
            index=3,
            style=style.instructions,
        )
    )
    plans.extend(
        _instruction_callout_plans(
            surface,
            style=style,
            prefix=prefix,
            rect=PdfRect(right_x, rect.y_mm + 37.0, right_width, 33.0),
            title="Verify",
            lines=(
                "Confirm the kit loads and shows the Recovery Kit home screen.",
                "If it fails to open, re-check the order and re-save the file.",
            ),
            index=1,
        )
    )
    plans.extend(
        _instruction_callout_plans(
            surface,
            style=style,
            prefix=prefix,
            rect=PdfRect(right_x, rect.y_mm + 77.0, right_width, 33.0),
            title="Storage",
            lines=(
                "Keep the QR pages and the bundle file in separate locations.",
                "Store the bundle on a write-protected drive if possible.",
            ),
            index=2,
        )
    )
    plans.extend(
        _instruction_callout_plans(
            surface,
            style=style,
            prefix=prefix,
            rect=PdfRect(right_x, rect.y_mm + 117.0, right_width, 30.0),
            title="Security",
            lines=(
                "Work offline and on a trusted machine.",
                "Delete temporary files after recovery.",
            ),
            index=3,
        )
    )
    plans.extend(
        classic_layout.build_instruction_checklist(
            surface,
            prefix=prefix,
            rect=PdfRect(right_x, checklist_y, right_width, checklist_height),
            style=style.instructions,
        )
    )
    return plans


def _instruction_callout_plans(
    surface: PdfSurface,
    *,
    style: ClassicKitInstructionStyle,
    prefix: str,
    rect: PdfRect,
    title: str,
    lines: Sequence[str],
    index: int,
) -> list[PaintPlan]:
    plans: list[PaintPlan] = [
        Panel(
            component_id=f"{prefix}-callout-{index}",
            stroke=style.instructions.rule,
            fill=style.note,
            line_width_mm=0.35,
        ).plan(surface, rect),
        TextBox(
            component_id=f"{prefix}-callout-title-{index}",
            text=title.upper(),
            style=classic_layout.title_text_style(
                size_pt=8.0, color=style.instructions.section_accent, char_spacing_pt=0.24
            ),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, rect.y_mm + 3.0, rect.width_mm - 6.0, 3.5)),
    ]
    y_mm = rect.y_mm + 10.0
    for line_index, line in enumerate(lines):
        text_plan = TextBox(
            component_id=f"{prefix}-callout-line-{index}-{line_index}",
            text=line,
            style=classic_layout.body_text_style(size_pt=8.4, color=style.instructions.ink),
            policy=TextFitPolicy.WRAP,
            line_height_multiplier=1.2,
        ).plan(surface, PdfRect(rect.x_mm + 3.0, y_mm, rect.width_mm - 6.0, 10.0))
        plans.append(text_plan)
        y_mm += max(7.2, text_plan.layout.used_rect.height_mm + 1.6)
    return plans


def _instruction_insert_footer(
    surface: PdfSurface,
    context: document_inputs.DocumentRenderContext,
    *,
    style: ClassicKitInstructionStyle,
    prefix: str,
    rect: PdfRect,
    page_label: str,
) -> list[PaintPlan]:
    inner_x = rect.x_mm + 8.0
    inner_width = rect.width_mm - 16.0
    rule_y = rect.bottom_mm - 17.0
    text_y = rule_y + 5.2
    kind_width = inner_width * 0.42
    page_width = 28.0
    doc_x = inner_x + kind_width + page_width
    doc_width = inner_width - kind_width - page_width
    return [
        Rule(
            component_id=f"{prefix}-insert-footer-rule", color=style.instructions.strong_rule
        ).plan(
            surface,
            PdfRect(inner_x, rule_y, inner_width, 0.55),
        ),
        TextBox(
            component_id=f"{prefix}-insert-footer-kind",
            text="RECOVERY KIT: OFFLINE HTML BUNDLE",
            style=classic_layout.body_text_style(
                size_pt=8.0, color=style.muted_ink, char_spacing_pt=0.2
            ),
            policy=TextFitPolicy.SHRINK,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(inner_x, text_y, kind_width, 4.2)),
        TextBox(
            component_id=f"{prefix}-insert-footer-page",
            text=page_label,
            style=classic_layout.monospace_text_style(
                size_pt=7.0,
                bold=True,
                color=style.instructions.section_accent,
                char_spacing_pt=0.06,
            ),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.CENTER,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(inner_x + kind_width, text_y, page_width, 4.2)),
        TextBox(
            component_id=f"{prefix}-insert-footer-doc",
            text=f"Document ID: {context.doc_id}",
            style=classic_layout.monospace_text_style(
                size_pt=7.0,
                color=style.instructions.ink,
                char_spacing_pt=0.06,
            ),
            policy=TextFitPolicy.SHRINK,
            align=TextAlign.RIGHT,
            min_size_pt=6.0,
        ).plan(surface, PdfRect(doc_x, text_y, doc_width, 4.2)),
    ]


__all__ = ["ClassicKitInstructionStyle", "build_classic_kit_instruction_page"]
