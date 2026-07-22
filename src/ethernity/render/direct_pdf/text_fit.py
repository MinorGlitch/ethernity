"""Measured text fitting for direct PDF layout components."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Sequence

from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.types import TextStyle

_SHRINK_STEP_PT = 0.25
_DEFAULT_MIN_SIZE_RATIO = 0.75
_DEFAULT_MIN_SIZE_PT = 4.0


class TextFitPolicy(str, Enum):
    """Explicit choices for handling text that may exceed a layout box."""

    FAIL = "fail"
    WRAP = "wrap"
    SHRINK = "shrink"
    SPLIT = "split"


class TextFitError(ValueError):
    """Raised when text cannot fit under the requested policy."""


@dataclass(frozen=True)
class TextFitResult:
    """Measured text placement result."""

    lines: tuple[str, ...]
    style: TextStyle
    policy: TextFitPolicy
    line_height_mm: float
    width_mm: float
    height_mm: float
    overflow_lines: tuple[str, ...] = ()

    @property
    def split(self) -> bool:
        return bool(self.overflow_lines)


def fit_text_to_width(
    surface: PdfSurface,
    text: str,
    style: TextStyle,
    *,
    max_width_mm: float,
    max_lines: int | None = None,
    policy: TextFitPolicy = TextFitPolicy.WRAP,
    min_size_pt: float | None = None,
    line_height_multiplier: float = 1.2,
) -> TextFitResult:
    """Measure text against a width and return lines that can be painted safely."""

    if max_width_mm <= 0:
        raise ValueError("max_width_mm must be positive")
    if max_lines is not None and max_lines <= 0:
        raise ValueError("max_lines must be positive")

    if policy == TextFitPolicy.FAIL:
        return _fit_without_wrapping(
            surface,
            text,
            style,
            max_width_mm=max_width_mm,
            max_lines=max_lines,
            line_height_multiplier=line_height_multiplier,
        )
    if policy == TextFitPolicy.SHRINK:
        return _fit_with_shrink(
            surface,
            text,
            style,
            max_width_mm=max_width_mm,
            max_lines=max_lines,
            min_size_pt=min_size_pt,
            line_height_multiplier=line_height_multiplier,
        )

    lines = _wrap_text(surface, text, style, max_width_mm=max_width_mm)
    if policy == TextFitPolicy.SPLIT and max_lines is not None and len(lines) > max_lines:
        return _build_result(
            surface,
            lines[:max_lines],
            style,
            policy=policy,
            overflow_lines=lines[max_lines:],
            line_height_multiplier=line_height_multiplier,
        )
    if max_lines is not None and len(lines) > max_lines:
        raise TextFitError(
            "wrapped text exceeds max_lines",
            {
                "line_count": len(lines),
                "max_lines": max_lines,
                "policy": policy.value,
            },
        )
    return _build_result(
        surface,
        lines,
        style,
        policy=policy,
        line_height_multiplier=line_height_multiplier,
    )


def _fit_without_wrapping(
    surface: PdfSurface,
    text: str,
    style: TextStyle,
    *,
    max_width_mm: float,
    max_lines: int | None,
    line_height_multiplier: float,
) -> TextFitResult:
    lines = tuple(_source_lines(text))
    if max_lines is not None and len(lines) > max_lines:
        raise TextFitError(
            "text exceeds max_lines",
            {"line_count": len(lines), "max_lines": max_lines, "policy": TextFitPolicy.FAIL},
        )
    too_wide = [line for line in lines if surface.measure_text_width(line, style) > max_width_mm]
    if too_wide:
        raise TextFitError(
            "text exceeds max_width_mm",
            {"max_width_mm": max_width_mm, "line": too_wide[0]},
        )
    return _build_result(
        surface,
        lines,
        style,
        policy=TextFitPolicy.FAIL,
        line_height_multiplier=line_height_multiplier,
    )


def _fit_with_shrink(
    surface: PdfSurface,
    text: str,
    style: TextStyle,
    *,
    max_width_mm: float,
    max_lines: int | None,
    min_size_pt: float | None,
    line_height_multiplier: float,
) -> TextFitResult:
    resolved_min_size = _resolve_min_size(style, min_size_pt)
    current_size = style.size_pt
    while True:
        candidate_style = replace(style, size_pt=current_size)
        lines = _wrap_text(surface, text, candidate_style, max_width_mm=max_width_mm)
        if max_lines is None or len(lines) <= max_lines:
            return _build_result(
                surface,
                lines,
                candidate_style,
                policy=TextFitPolicy.SHRINK,
                line_height_multiplier=line_height_multiplier,
            )
        if current_size == resolved_min_size:
            break
        current_size = max(
            resolved_min_size,
            round(current_size - _SHRINK_STEP_PT, 2),
        )
    raise TextFitError(
        "text cannot shrink enough to fit",
        {
            "size_pt": style.size_pt,
            "min_size_pt": resolved_min_size,
            "max_lines": max_lines,
        },
    )


def _resolve_min_size(style: TextStyle, min_size_pt: float | None) -> float:
    resolved = (
        min_size_pt
        if min_size_pt is not None
        else max(_DEFAULT_MIN_SIZE_PT, style.size_pt * _DEFAULT_MIN_SIZE_RATIO)
    )
    if resolved <= 0:
        raise ValueError("min_size_pt must be positive")
    if resolved > style.size_pt:
        raise ValueError("min_size_pt cannot exceed the starting text size")
    return resolved


def _wrap_text(
    surface: PdfSurface,
    text: str,
    style: TextStyle,
    *,
    max_width_mm: float,
) -> tuple[str, ...]:
    wrapped: list[str] = []
    for line in _source_lines(text):
        wrapped.extend(_wrap_source_line(surface, line, style, max_width_mm=max_width_mm))
    return tuple(wrapped)


def _source_lines(text: str) -> tuple[str, ...]:
    if text == "":
        return ("",)
    return tuple(text.splitlines() or ("",))


def _wrap_source_line(
    surface: PdfSurface,
    line: str,
    style: TextStyle,
    *,
    max_width_mm: float,
) -> tuple[str, ...]:
    if line == "":
        return ("",)

    wrapped: list[str] = []
    current = ""
    for word in line.split(" "):
        candidate = word if not current else f"{current} {word}"
        if surface.measure_text_width(candidate, style) <= max_width_mm:
            current = candidate
            continue
        if current:
            wrapped.append(current)
            current = ""
        if surface.measure_text_width(word, style) <= max_width_mm:
            current = word
            continue
        pieces = _break_long_word(surface, word, style, max_width_mm=max_width_mm)
        wrapped.extend(pieces[:-1])
        current = pieces[-1] if pieces else ""

    if current:
        wrapped.append(current)
    return tuple(wrapped)


def _break_long_word(
    surface: PdfSurface,
    word: str,
    style: TextStyle,
    *,
    max_width_mm: float,
) -> tuple[str, ...]:
    pieces: list[str] = []
    current = ""
    for character in word:
        if surface.measure_text_width(character, style) > max_width_mm:
            raise TextFitError(
                "single character exceeds max_width_mm",
                {"max_width_mm": max_width_mm, "character": character},
            )
        candidate = f"{current}{character}"
        if current and surface.measure_text_width(candidate, style) > max_width_mm:
            pieces.append(current)
            current = character
        else:
            current = candidate
    if current:
        pieces.append(current)
    return tuple(pieces)


def _build_result(
    surface: PdfSurface,
    lines: Sequence[str],
    style: TextStyle,
    *,
    policy: TextFitPolicy,
    line_height_multiplier: float,
    overflow_lines: Sequence[str] = (),
) -> TextFitResult:
    line_tuple = tuple(lines)
    line_height = surface.line_height(style, multiplier=line_height_multiplier)
    widths = [surface.measure_text_width(line, style) for line in line_tuple]
    return TextFitResult(
        lines=line_tuple,
        style=style,
        policy=policy,
        line_height_mm=line_height,
        width_mm=max(widths, default=0.0),
        height_mm=len(line_tuple) * line_height,
        overflow_lines=tuple(overflow_lines),
    )


__all__ = [
    "TextFitError",
    "TextFitPolicy",
    "TextFitResult",
    "fit_text_to_width",
]
