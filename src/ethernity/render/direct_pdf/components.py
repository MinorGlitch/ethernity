"""Measured direct-PDF layout components."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.text_fit import (
    TextFitError,
    TextFitPolicy,
    TextFitResult,
    fit_text_to_width,
)
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle

_POINT_TO_MM = 25.4 / 72.0
MINIMUM_TEXT_SIZE_PT = 6.0


class TextAlign(str, Enum):
    """Horizontal text alignment inside a measured text box."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class PdfComponent(Protocol):
    """A direct-PDF component that can plan and paint itself."""

    component_id: str

    def plan(self, surface: PdfSurface, rect: PdfRect) -> object:
        """Measure the component inside a rectangle and return a plan."""


@dataclass(frozen=True)
class BoxPlacementProof:
    """Geometry proof for a non-text component."""

    component_id: str
    component_type: str
    rect: PdfRect
    overflow: bool = False


@dataclass(frozen=True)
class PanelPlan:
    """Measured plan for a rectangular panel."""

    component_id: str
    rect: PdfRect
    stroke: PdfColor | None
    fill: PdfColor | None
    line_width_mm: float
    corner_radius_mm: float
    proof: BoxPlacementProof

    def paint(self, surface: PdfSurface) -> None:
        """Paint the planned panel."""

        if self.corner_radius_mm > 0:
            surface.draw_rounded_rect(
                self.rect,
                corner_radius_mm=self.corner_radius_mm,
                stroke=self.stroke,
                fill=self.fill,
                line_width_mm=self.line_width_mm,
            )
            return
        surface.draw_rect(
            self.rect,
            stroke=self.stroke,
            fill=self.fill,
            line_width_mm=self.line_width_mm,
        )


@dataclass(frozen=True)
class Panel:
    """A stroked and/or filled rectangle."""

    component_id: str
    stroke: PdfColor | None = None
    fill: PdfColor | None = None
    line_width_mm: float = 0.2
    corner_radius_mm: float = 0.0

    def __post_init__(self) -> None:
        _validate_component_id(self.component_id)
        if self.stroke is None and self.fill is None:
            raise ValueError("stroke or fill is required")
        if self.line_width_mm <= 0:
            raise ValueError("line_width_mm must be positive")
        if self.corner_radius_mm < 0:
            raise ValueError("corner_radius_mm must be non-negative")

    def plan(self, surface: PdfSurface, rect: PdfRect) -> PanelPlan:
        """Validate panel geometry before painting."""

        _ = surface
        _require_positive_rect(rect, component_id=self.component_id)
        if self.corner_radius_mm > min(rect.width_mm, rect.height_mm) / 2.0:
            raise ValueError(f"{self.component_id} corner radius is too large")
        return PanelPlan(
            component_id=self.component_id,
            rect=rect,
            stroke=self.stroke,
            fill=self.fill,
            line_width_mm=self.line_width_mm,
            corner_radius_mm=self.corner_radius_mm,
            proof=BoxPlacementProof(
                component_id=self.component_id,
                component_type="panel",
                rect=rect,
            ),
        )


@dataclass(frozen=True)
class EllipsePlan:
    """Measured plan for an elliptical panel."""

    component_id: str
    rect: PdfRect
    stroke: PdfColor | None
    fill: PdfColor | None
    line_width_mm: float
    proof: BoxPlacementProof

    def paint(self, surface: PdfSurface) -> None:
        """Paint the planned ellipse."""

        surface.draw_ellipse(
            self.rect,
            stroke=self.stroke,
            fill=self.fill,
            line_width_mm=self.line_width_mm,
        )


@dataclass(frozen=True)
class Ellipse:
    """A stroked and/or filled ellipse."""

    component_id: str
    stroke: PdfColor | None = None
    fill: PdfColor | None = None
    line_width_mm: float = 0.2

    def __post_init__(self) -> None:
        _validate_component_id(self.component_id)
        if self.stroke is None and self.fill is None:
            raise ValueError("stroke or fill is required")
        if self.line_width_mm <= 0:
            raise ValueError("line_width_mm must be positive")

    def plan(self, surface: PdfSurface, rect: PdfRect) -> EllipsePlan:
        """Validate ellipse geometry before painting."""

        _ = surface
        _require_positive_rect(rect, component_id=self.component_id)
        return EllipsePlan(
            component_id=self.component_id,
            rect=rect,
            stroke=self.stroke,
            fill=self.fill,
            line_width_mm=self.line_width_mm,
            proof=BoxPlacementProof(
                component_id=self.component_id,
                component_type="ellipse",
                rect=rect,
            ),
        )


@dataclass(frozen=True)
class RulePlan:
    """Measured plan for a filled rule."""

    component_id: str
    rect: PdfRect
    color: PdfColor
    proof: BoxPlacementProof

    def paint(self, surface: PdfSurface) -> None:
        """Paint the planned rule."""

        surface.draw_rect(self.rect, fill=self.color)


@dataclass(frozen=True)
class Rule:
    """A thin filled rectangle used for dividers and page rules."""

    component_id: str
    color: PdfColor

    def __post_init__(self) -> None:
        _validate_component_id(self.component_id)

    def plan(self, surface: PdfSurface, rect: PdfRect) -> RulePlan:
        """Validate rule geometry before painting."""

        _ = surface
        _require_positive_rect(rect, component_id=self.component_id)
        return RulePlan(
            component_id=self.component_id,
            rect=rect,
            color=self.color,
            proof=BoxPlacementProof(
                component_id=self.component_id,
                component_type="rule",
                rect=rect,
            ),
        )


@dataclass(frozen=True)
class LinePlan:
    """Measured plan for a straight line segment."""

    component_id: str
    start_x_mm: float
    start_y_mm: float
    end_x_mm: float
    end_y_mm: float
    color: PdfColor
    line_width_mm: float
    proof: BoxPlacementProof

    def paint(self, surface: PdfSurface) -> None:
        """Paint the planned line segment."""

        surface.draw_line(
            self.start_x_mm,
            self.start_y_mm,
            self.end_x_mm,
            self.end_y_mm,
            color=self.color,
            line_width_mm=self.line_width_mm,
        )


@dataclass(frozen=True)
class Line:
    """A straight line segment with bounded geometry proof."""

    component_id: str
    color: PdfColor
    line_width_mm: float = 0.2

    def __post_init__(self) -> None:
        _validate_component_id(self.component_id)
        if self.line_width_mm <= 0:
            raise ValueError("line_width_mm must be positive")

    def plan(
        self,
        surface: PdfSurface,
        *,
        start_x_mm: float,
        start_y_mm: float,
        end_x_mm: float,
        end_y_mm: float,
    ) -> LinePlan:
        """Validate line geometry before painting."""

        _ = surface
        if start_x_mm == end_x_mm and start_y_mm == end_y_mm:
            raise ValueError(f"{self.component_id} line must have non-zero length")
        rect = _line_bounds(start_x_mm, start_y_mm, end_x_mm, end_y_mm, self.line_width_mm)
        return LinePlan(
            component_id=self.component_id,
            start_x_mm=start_x_mm,
            start_y_mm=start_y_mm,
            end_x_mm=end_x_mm,
            end_y_mm=end_y_mm,
            color=self.color,
            line_width_mm=self.line_width_mm,
            proof=BoxPlacementProof(
                component_id=self.component_id,
                component_type="line",
                rect=rect,
            ),
        )


@dataclass(frozen=True)
class ImageBoxPlan:
    """Measured plan for an image box."""

    component_id: str
    rect: PdfRect
    image: bytes
    image_type: str
    proof: BoxPlacementProof

    def paint(self, surface: PdfSurface) -> None:
        """Paint the planned image."""

        surface.draw_image_bytes(self.image, self.rect, image_type=self.image_type)


@dataclass(frozen=True)
class ImageBox:
    """An image constrained to a measured rectangle."""

    component_id: str
    image: bytes
    image_type: str = ""

    def __post_init__(self) -> None:
        _validate_component_id(self.component_id)
        if not self.image:
            raise ValueError("image must be non-empty")

    def plan(self, surface: PdfSurface, rect: PdfRect) -> ImageBoxPlan:
        """Validate image geometry before painting."""

        _ = surface
        _require_positive_rect(rect, component_id=self.component_id)
        return ImageBoxPlan(
            component_id=self.component_id,
            rect=rect,
            image=self.image,
            image_type=self.image_type,
            proof=BoxPlacementProof(
                component_id=self.component_id,
                component_type="image",
                rect=rect,
            ),
        )


@dataclass(frozen=True)
class TextLinePlacement:
    """A measured text line and the PDF baseline where it will be drawn."""

    text: str
    x_mm: float
    baseline_y_mm: float
    width_mm: float


@dataclass(frozen=True)
class TextPlacementProof:
    """Geometry and fit proof for a planned text box."""

    component_id: str
    rect: PdfRect
    used_rect: PdfRect
    policy: TextFitPolicy
    line_count: int
    overflow_line_count: int
    font_size_pt: float
    overflow: bool
    component_type: str = "text"


@dataclass(frozen=True)
class TextBoxPlan:
    """Measured plan for a text box."""

    component_id: str
    rect: PdfRect
    fit: TextFitResult
    lines: tuple[TextLinePlacement, ...]
    proof: TextPlacementProof

    def paint(self, surface: PdfSurface) -> None:
        """Paint planned lines to a PDF surface."""

        for line in self.lines:
            surface.draw_text(
                line.x_mm,
                line.baseline_y_mm,
                line.text,
                self.fit.style,
            )


@dataclass(frozen=True)
class TextBox:
    """A measured text component with explicit overflow behavior."""

    component_id: str
    text: str
    style: TextStyle
    policy: TextFitPolicy = TextFitPolicy.WRAP
    align: TextAlign = TextAlign.LEFT
    min_size_pt: float | None = None
    line_height_multiplier: float = 1.2

    def __post_init__(self) -> None:
        _validate_component_id(self.component_id)
        if self.line_height_multiplier <= 0:
            raise ValueError("line_height_multiplier must be positive")
        if self.style.size_pt < MINIMUM_TEXT_SIZE_PT:
            raise ValueError(
                f"style size must be at least {MINIMUM_TEXT_SIZE_PT:.1f} points: "
                f"{self.component_id} uses {self.style.size_pt:.2f} points"
            )
        if self.min_size_pt is not None and self.min_size_pt < MINIMUM_TEXT_SIZE_PT:
            raise ValueError(
                f"minimum size must be at least {MINIMUM_TEXT_SIZE_PT:.1f} points: "
                f"{self.component_id} uses {self.min_size_pt:.2f} points"
            )

    def plan(self, surface: PdfSurface, rect: PdfRect) -> TextBoxPlan:
        """Measure text into the provided rectangle before painting."""

        if rect.width_mm <= 0:
            raise ValueError("text box width must be positive")
        if rect.height_mm <= 0:
            raise ValueError("text box height must be positive")

        max_lines = _max_lines_for_rect(
            surface,
            self.style,
            rect,
            line_height_multiplier=self.line_height_multiplier,
        )
        try:
            fit = fit_text_to_width(
                surface,
                self.text,
                self.style,
                max_width_mm=rect.width_mm,
                max_lines=max_lines,
                policy=self.policy,
                min_size_pt=(
                    self.min_size_pt if self.min_size_pt is not None else MINIMUM_TEXT_SIZE_PT
                ),
                line_height_multiplier=self.line_height_multiplier,
            )
        except TextFitError as exc:
            raise _component_text_fit_error(self.component_id, exc) from exc
        if fit.height_mm > rect.height_mm:
            raise TextFitError(
                "text height exceeds box height",
                {
                    "component_id": self.component_id,
                    "height_mm": fit.height_mm,
                    "box_height_mm": rect.height_mm,
                },
            )
        if fit.style.size_pt < MINIMUM_TEXT_SIZE_PT:
            raise TextFitError(
                "planned text is below the minimum readable size",
                {
                    "component_id": self.component_id,
                    "font_size_pt": fit.style.size_pt,
                    "minimum_font_size_pt": MINIMUM_TEXT_SIZE_PT,
                },
            )

        lines = _place_lines(surface, rect, fit, align=self.align)
        used_x_mm = min((line.x_mm for line in lines), default=rect.x_mm)
        used_right_mm = max(
            (line.x_mm + line.width_mm for line in lines),
            default=used_x_mm,
        )
        used_rect = PdfRect(
            used_x_mm,
            rect.y_mm,
            used_right_mm - used_x_mm,
            fit.height_mm,
        )
        proof = TextPlacementProof(
            component_id=self.component_id,
            rect=rect,
            used_rect=used_rect,
            policy=fit.policy,
            line_count=len(fit.lines),
            overflow_line_count=len(fit.overflow_lines),
            font_size_pt=fit.style.size_pt,
            overflow=fit.split,
        )
        return TextBoxPlan(
            component_id=self.component_id,
            rect=rect,
            fit=fit,
            lines=lines,
            proof=proof,
        )


def _component_text_fit_error(component_id: str, exc: TextFitError) -> TextFitError:
    message = str(exc)
    details: dict[str, object] = {}
    if len(exc.args) >= 1:
        message = str(exc.args[0])
    if len(exc.args) >= 2 and isinstance(exc.args[1], dict):
        details = dict(exc.args[1])
    details["component_id"] = component_id
    return TextFitError(message, details)


def _max_lines_for_rect(
    surface: PdfSurface,
    style: TextStyle,
    rect: PdfRect,
    *,
    line_height_multiplier: float,
) -> int:
    line_height = surface.line_height(style, multiplier=line_height_multiplier)
    max_lines = math.floor(rect.height_mm / line_height)
    if max_lines <= 0:
        raise TextFitError(
            "text box height cannot fit one line",
            {"height_mm": rect.height_mm, "line_height_mm": line_height},
        )
    return max_lines


def _place_lines(
    surface: PdfSurface,
    rect: PdfRect,
    fit: TextFitResult,
    *,
    align: TextAlign,
) -> tuple[TextLinePlacement, ...]:
    placements: list[TextLinePlacement] = []
    font_height = fit.style.size_pt * _POINT_TO_MM
    leading = max(0.0, fit.line_height_mm - font_height)
    first_baseline_y = rect.y_mm + (leading / 2.0) + font_height
    for index, line in enumerate(fit.lines):
        width = surface.measure_text_width(line, fit.style)
        placements.append(
            TextLinePlacement(
                text=line,
                x_mm=_line_x(rect, width, align=align),
                baseline_y_mm=first_baseline_y + index * fit.line_height_mm,
                width_mm=width,
            )
        )
    return tuple(placements)


def _line_x(rect: PdfRect, width_mm: float, *, align: TextAlign) -> float:
    if align == TextAlign.CENTER:
        return rect.x_mm + max(0.0, (rect.width_mm - width_mm) / 2.0)
    if align == TextAlign.RIGHT:
        return rect.right_mm - width_mm
    return rect.x_mm


def _validate_component_id(component_id: str) -> None:
    if not component_id.strip():
        raise ValueError("component_id must be non-empty")


def _require_positive_rect(rect: PdfRect, *, component_id: str) -> None:
    if rect.width_mm <= 0:
        raise ValueError(f"{component_id} width must be positive")
    if rect.height_mm <= 0:
        raise ValueError(f"{component_id} height must be positive")


def _line_bounds(
    start_x_mm: float,
    start_y_mm: float,
    end_x_mm: float,
    end_y_mm: float,
    line_width_mm: float,
) -> PdfRect:
    x_mm = min(start_x_mm, end_x_mm)
    y_mm = min(start_y_mm, end_y_mm)
    width_mm = max(abs(end_x_mm - start_x_mm), line_width_mm)
    height_mm = max(abs(end_y_mm - start_y_mm), line_width_mm)
    return PdfRect(x_mm, y_mm, width_mm, height_mm)


__all__ = [
    "BoxPlacementProof",
    "Ellipse",
    "EllipsePlan",
    "ImageBox",
    "ImageBoxPlan",
    "Line",
    "LinePlan",
    "MINIMUM_TEXT_SIZE_PT",
    "Panel",
    "PanelPlan",
    "PdfComponent",
    "Rule",
    "RulePlan",
    "TextAlign",
    "TextBox",
    "TextBoxPlan",
    "TextLinePlacement",
    "TextPlacementProof",
]
