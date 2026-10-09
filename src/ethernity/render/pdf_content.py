"""Check emitted PDF paint operations against the measured document layout."""

from __future__ import annotations

from pypdf import PdfReader, _cmap
from pypdf.generic import ByteStringObject, TextStringObject

from ethernity.render.checks import RenderValidationError
from ethernity.render.types import LayoutReport, RenderRect

_POINT_TO_MM = 25.4 / 72.0
_PAINT_TOLERANCE_MM = 0.02


def validate_painted_content(
    *, reader: PdfReader, layout_report: LayoutReport, document_label: str
) -> None:
    """Require planned text and images to be painted, not merely retained as resources."""

    for page, plan in zip(reader.pages, layout_report.pages, strict=True):
        collector = _PagePaintCollector(page, document_label)
        page.extract_text(visitor_operand_before=collector.visit)
        text_count = collector.text_count
        painted_lines = collector.painted_lines
        image_rects = collector.image_rects
        expected_text_count = sum(component.line_count or 0 for component in plan.components)
        expected_lines = tuple(
            (component, line)
            for component in plan.components
            for line in component.text_lines
            if line.text
        )
        for (component, line), (text, x_mm, baseline_y_mm) in zip(
            expected_lines, painted_lines, strict=False
        ):
            if (
                text != line.text
                or abs(x_mm - line.x_mm) > _PAINT_TOLERANCE_MM
                or abs(baseline_y_mm - line.baseline_y_mm) > _PAINT_TOLERANCE_MM
            ):
                metadata = component.text_metadata
                value_label = metadata.role.replace("_", " ") if metadata else "planned text"
                raise RenderValidationError(
                    f"{document_label} painted text has missing or incorrect {value_label} "
                    "at its planned placement",
                    details={
                        "page_number": plan.page_number,
                        "component_id": component.component_id,
                    },
                )
        if text_count != expected_text_count:
            raise RenderValidationError(
                f"{document_label} painted text does not match its layout report",
                details={
                    "page_number": plan.page_number,
                    "expected_text_line_count": expected_text_count,
                    "painted_text_line_count": text_count,
                },
            )
        if len(painted_lines) != len(expected_lines):
            raise RenderValidationError(
                f"{document_label} painted text does not match its layout report"
            )
        expected_rects = [
            component.rect for component in plan.components if component.component_type == "image"
        ]
        for painted in image_rects:
            match = next((rect for rect in expected_rects if _rects_match(painted, rect)), None)
            if match is None:
                raise RenderValidationError(
                    f"{document_label} painted images do not match its layout report"
                )
            expected_rects.remove(match)
        if expected_rects:
            raise RenderValidationError(
                f"{document_label} is missing planned image paint operations"
            )


def _decode_painted_string(value, encoding, character_map) -> str:
    """Decode glyph codes directly, preserving spaces that page text extraction infers or drops."""

    raw = value.original_bytes
    if isinstance(encoding, str):
        glyphs = raw.decode(encoding, "surrogatepass")
    else:
        glyphs = "".join(encoding[code] for code in raw)
    return "".join(character_map.get(glyph, glyph) for glyph in glyphs)


def _rects_match(first: RenderRect, second: RenderRect) -> bool:
    return all(
        abs(left - right) <= _PAINT_TOLERANCE_MM
        for left, right in zip(
            (first.x_mm, first.y_mm, first.width_mm, first.height_mm),
            (second.x_mm, second.y_mm, second.width_mm, second.height_mm),
            strict=True,
        )
    )


__all__ = ["validate_painted_content"]


class _PagePaintCollector:
    """Track emitted operations for one page with its own graphics state."""

    def __init__(self, page, document_label: str) -> None:
        self.document_label = document_label
        self.text_count = 0
        self.painted_lines: list[tuple[str, float, float]] = []
        self.image_rects: list[RenderRect] = []
        resources = page.get("/Resources", {})
        self.images = resources.get("/XObject", {})
        fonts = resources.get("/Font", {})
        self.font_name = None
        self.font_stack: list[object] = []
        self.encodings = {
            name: _cmap.get_encoding(font.get_object()) for name, font in fonts.items()
        }
        self.page_height_pt = float(page.mediabox.top)

    def visit(self, operator, operands, matrix, text_matrix) -> None:
        if operator in {b"W", b"W*"}:
            raise RenderValidationError(
                f"{self.document_label} has unexpected clipped paint operations"
            )
        if operator == b"q":
            self.font_stack.append(self.font_name)
        elif operator == b"Q":
            self.font_name = self.font_stack.pop()
        elif operator == b"Tf":
            self.font_name = operands[0]
        if operator in {b"Tj", b"TJ"}:
            self._record_text(operator, operands, matrix, text_matrix)
        self._record_image(operator, operands, matrix)

    def _record_text(self, operator, operands, matrix, text_matrix) -> None:
        self.text_count += 1
        if self.font_name not in self.encodings:
            raise RenderValidationError(f"{self.document_label} has text with an unknown font")
        encoding, character_map = self.encodings[self.font_name]
        strings = operands if operator == b"Tj" else operands[0]
        text = "".join(
            _decode_painted_string(value, encoding, character_map)
            for value in strings
            if isinstance(value, (ByteStringObject, TextStringObject))
        )
        if text:
            x_pt = text_matrix[4] * matrix[0] + text_matrix[5] * matrix[2] + matrix[4]
            y_pt = text_matrix[4] * matrix[1] + text_matrix[5] * matrix[3] + matrix[5]
            self.painted_lines.append(
                (text, x_pt * _POINT_TO_MM, (self.page_height_pt - y_pt) * _POINT_TO_MM)
            )

    def _record_image(self, operator, operands, matrix) -> None:
        if operator != b"Do":
            return
        image = self.images.get(operands[0])
        if image is None or image.get_object().get("/Subtype") != "/Image":
            return
        a, b, c, d, x, y = matrix
        xs = (x, x + a, x + c, x + a + c)
        ys = (y, y + b, y + d, y + b + d)
        self.image_rects.append(
            RenderRect(
                x_mm=min(xs) * _POINT_TO_MM,
                y_mm=(self.page_height_pt - max(ys)) * _POINT_TO_MM,
                width_mm=(max(xs) - min(xs)) * _POINT_TO_MM,
                height_mm=(max(ys) - min(ys)) * _POINT_TO_MM,
            )
        )
