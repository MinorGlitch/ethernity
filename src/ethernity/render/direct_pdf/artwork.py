"""Paint declared template components with current document values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import overload

from ethernity.render.direct_pdf import components, document_inputs
from ethernity.render.direct_pdf.page import PaintPlan
from ethernity.render.direct_pdf.responsive_layout import ResolvedGrid
from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.doc_types import DOC_TYPE_KIT
from ethernity.render.template import GridArtwork, LayoutElement, PageArtwork, Template
from ethernity.render.types import RenderTextMetadata


@overload
def color(value: str) -> PdfColor: ...


@overload
def color(value: None) -> None: ...


def color(value: str | None) -> PdfColor | None:
    if value is None:
        return None
    return PdfColor(*(int(value[index : index + 2], 16) for index in (1, 3, 5)))


def document_values(context: document_inputs.DocumentRenderContext) -> dict[str, str | int]:
    values: dict[str, str | int] = {
        "doc_id": context.doc_id,
        "is_kit": int(context.doc_type == DOC_TYPE_KIT),
        "extension": int(context.origin.kind == "extension"),
        "not_extension": int(context.origin.kind != "extension"),
        "document_id_label": context.document_id_label(),
        "short_id_label": context.document_id_label("DOC ID").upper(),
        "created_timestamp": context.created_timestamp_utc,
        "created_date": context.created_timestamp_utc[:10],
        "generator": context.footer_left,
    }
    for name in ("shard_index", "shard_total", "shard_threshold"):
        values[name] = document_inputs.non_negative_int(context.values.get(name), default=0)
    for name, value in context.copy.items():
        if isinstance(value, str):
            values["copy_" + name] = value
        elif isinstance(value, (tuple, list)):
            for index, item in enumerate(value):
                values[f"copy_{name}_{index}"] = str(item)
    values["instructions_label"] = context.instructions_label
    values["instructions_text"] = str(
        context.copy.get("scan_instructions") or "\n".join(context.instruction_lines)
    )
    values.setdefault("copy_document_id_label", values["document_id_label"])
    for index, value in enumerate(context.instruction_lines):
        values[f"instruction_{index}"] = value
    for name, value in tuple(values.items()):
        if isinstance(value, str):
            values[name + "_upper"] = value.upper()
    return values


def qr_values(item: document_inputs.QrPayloadItem, *, is_kit: bool) -> dict[str, str | int]:
    values: dict[str, str | int] = {"segment_number": item.label_index}
    if is_kit and item.payload_index < 2:
        values["copy_segment_prefix_upper"] = "START"
    return values


@dataclass(frozen=True)
class Artwork:
    surface: PdfSurface
    definition: Template
    page: PdfRect

    @property
    def scale(self) -> tuple[float, float]:
        width, height = self.definition.reference_size
        return self.page.width_mm / width, self.page.height_mm / height

    def paint_plans(
        self,
        artwork: PageArtwork,
        values: Mapping[str, str | int],
        *,
        prefix: str,
        items: Sequence[document_inputs.QrPayloadItem] = (),
    ) -> list[PaintPlan]:
        plans: list[PaintPlan] = []
        scale_x, scale_y = self.scale
        grid_plans: list[PaintPlan] = []
        original_slots: tuple[PdfRect, ...] = ()
        slots: tuple[PdfRect, ...] = ()
        if artwork.grid is not None:
            grid = artwork.grid
            layout = ResolvedGrid(
                PdfRect(*grid.box),
                grid.columns,
                grid.rows,
                *grid.card_size,
                *grid.gap,
                grid.horizontal,
                grid.vertical,
            )
            original_slots = layout.item_rects(artwork.qr_capacity)
            slots = layout.item_rects(len(items), reserve_all_rows=grid.reserve_rows)
            grid_plans = self._grid_background(grid, slots, prefix)
        preceding: dict[str, PdfRect] = {}
        for element in expanded_elements(self.definition, artwork.elements):
            if element.visible and not values.get(element.visible):
                continue
            item = None
            if element.qr_slot is not None:
                if element.qr_slot >= len(items):
                    continue
                item = items[element.qr_slot]
                if grid_plans:
                    plans.extend(grid_plans)
                    grid_plans.clear()
            content = dict(values)
            if item is not None:
                content.update(qr_values(item, is_kit=bool(values.get("is_kit"))))
            key = f"{prefix}-{element.key}"
            x, y, width, height = element.box
            if item is not None and artwork.grid is not None:
                assert element.qr_slot is not None
                old_slot, new_slot = original_slots[element.qr_slot], slots[element.qr_slot]
                x += new_slot.x_mm - old_slot.x_mm
                y += new_slot.y_mm - old_slot.y_mm
            rect = PdfRect(x * scale_x, y * scale_y, width * scale_x, height * scale_y)
            if element.after:
                previous = preceding[element.after]
                rect = PdfRect(
                    rect.x_mm,
                    max(rect.y_mm, previous.bottom_mm + element.gap_after),
                    rect.width_mm,
                    rect.height_mm,
                )
            plan = self._paint_element(element, rect, content, key, item)
            preceding[element.key] = getattr(plan.layout, "used_rect", rect)
            plans.append(plan)
        return plans

    def _grid_background(
        self, grid: GridArtwork, slots: Sequence[PdfRect], prefix: str
    ) -> list[PaintPlan]:
        if grid.background is None or not slots:
            return []
        scale_x, scale_y = self.scale
        result: list[PaintPlan] = []

        left = min(slot.x_mm for slot in slots) - grid.padding
        top = min(slot.y_mm for slot in slots) - grid.padding
        right = max(slot.right_mm for slot in slots) + grid.padding
        bottom = max(slot.bottom_mm for slot in slots) + grid.padding
        rect = PdfRect(
            left * scale_x,
            top * scale_y,
            (right - left) * scale_x,
            (bottom - top) * scale_y,
        )
        result.append(
            components.Panel(
                prefix + "-grid-background",
                color(grid.border),
                color(grid.background),
                grid.border_width,
            ).plan(self.surface, rect)
        )
        for axis, length in (("x", right - left), ("y", bottom - top)):
            position = grid.grid_step
            while position < length:
                rule_rect = (
                    PdfRect(
                        (left + position) * scale_x,
                        top * scale_y,
                        0.18 * scale_x,
                        (bottom - top) * scale_y,
                    )
                    if axis == "x"
                    else PdfRect(
                        left * scale_x,
                        (top + position) * scale_y,
                        (right - left) * scale_x,
                        0.18 * scale_y,
                    )
                )
                result.append(
                    components.Rule(
                        f"{prefix}-grid-{axis}-{position}",
                        color(grid.rule) or PdfColor(0, 0, 0),
                    ).plan(self.surface, rule_rect)
                )
                position += grid.grid_step
        return result

    def _paint_element(
        self,
        element: LayoutElement,
        rect: PdfRect,
        content: Mapping[str, str | int],
        key: str,
        item: document_inputs.QrPayloadItem | None,
    ) -> PaintPlan:
        scale_x, scale_y = self.scale
        height = element.box[3]
        if element.kind == "text":
            rect = PdfRect(
                rect.x_mm,
                rect.y_mm,
                rect.width_mm,
                rect.height_mm if element.scale_height else max(height, rect.height_mm),
            )
            style_data = self.definition.styles[element.style or ""]
            style = TextStyle(
                family=style_data.family,
                size_pt=element.font_size or style_data.size_pt,
                style=style_data.style,
                color=color(style_data.color) or PdfColor(0, 0, 0),
                char_spacing_pt=style_data.char_spacing_pt,
            )
            plan = components.TextBox(
                key,
                element.text.format_map(content),
                style,
                policy=TextFitPolicy(element.fit),
                max_lines=element.max_lines,
                min_size_pt=min(element.min_size, element.font_size or element.min_size),
                align=components.TextAlign(element.align),
                line_height_multiplier=element.line_height,
                text_metadata=RenderTextMetadata(
                    element.metadata,
                    str(content.get("print_mode"))
                    if element.metadata == "recovery_passphrase"
                    else None,
                    continuation_index=int(content["continuation_index"])
                    if "continuation_index" in content
                    else 0,
                    value_prefix=element.value_prefix,
                )
                if element.metadata
                else None,
            ).plan(self.surface, rect)
        elif element.kind == "image":
            if item is None:
                raise ValueError("QR image must declare a slot")
            size = min(rect.width_mm, rect.height_mm)
            rect = PdfRect(
                rect.x_mm + (rect.width_mm - size) / 2,
                rect.y_mm + (rect.height_mm - size) / 2,
                size,
                size,
            )
            plan = components.ImageBox(key, item.image).plan(self.surface, rect)
        elif element.kind == "line":
            assert element.line is not None
            sx, sy, ex, ey = element.line
            plan = components.Line(
                key, color(element.fill) or PdfColor(0, 0, 0), element.line_width
            ).plan(
                self.surface,
                start_x_mm=sx * scale_x,
                start_y_mm=sy * scale_y,
                end_x_mm=ex * scale_x,
                end_y_mm=ey * scale_y,
            )
        elif element.kind == "rule":
            plan = components.Rule(key, color(element.fill) or PdfColor(0, 0, 0)).plan(
                self.surface, rect
            )
        elif element.kind == "ellipse":
            plan = components.Ellipse(
                key, color(element.stroke), color(element.fill), element.line_width
            ).plan(self.surface, rect)
        else:
            plan = components.Panel(
                key,
                color(element.stroke),
                color(element.fill),
                element.line_width,
                element.radius,
            ).plan(self.surface, rect)
        return plan


def text_style(definition: Template, name: str) -> TextStyle:
    data = definition.styles[name]
    return TextStyle(
        data.family,
        data.size_pt,
        data.style,
        color(data.color) or PdfColor(0, 0, 0),
        data.char_spacing_pt,
    )


def expanded_elements(
    definition: Template, elements: tuple[LayoutElement, ...]
) -> tuple[LayoutElement, ...]:
    """Expand reusable artwork without introducing design-specific drawing code."""
    result: list[LayoutElement] = []
    for element in elements:
        for index in range(element.repeat):
            dx, dy = index * element.step[0], index * element.step[1]
            if element.kind == "group":
                children = expanded_elements(definition, definition.components[element.ref or ""])
                dx += element.box[0]
                dy += element.box[1]
            else:
                children = (element,)
            for child in children:
                x, y, width, height = child.box
                if element.kind == "group" and element.box[2] and child.stretch_x:
                    width = element.box[2] - x
                if element.kind == "group" and element.box[3] and child.stretch_y:
                    height = element.box[3] - y
                update = {
                    "box": (x + dx, y + dy, width, height),
                    "key": f"{element.key}-{index}-{child.key}"
                    if element.kind == "group" or element.repeat > 1
                    else child.key,
                    "repeat": 1,
                }
                if element.kind == "group" and child.after:
                    update["after"] = f"{element.key}-{index}-{child.after}"
                if element.qr_slot is not None:
                    update["qr_slot"] = element.qr_slot
                if child.line:
                    x1, y1, x2, y2 = child.line
                    update["line"] = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
                result.append(child.model_copy(update=update))
    return tuple(result)
