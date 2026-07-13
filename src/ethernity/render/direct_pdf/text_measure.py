"""Reusable text measurement primitives for direct PDF layout."""

from __future__ import annotations

import math

from ethernity.render.direct_pdf.surface import PdfSurface
from ethernity.render.direct_pdf.types import TextStyle


def measured_grouped_line_length(
    surface: PdfSurface,
    *,
    style: TextStyle,
    alphabet: str,
    group_size: int,
    max_width_mm: float,
    safety_mm: float = 0.0,
) -> int:
    """Return the longest worst-case grouped line that fits a measured width.

    The returned length includes the single spaces between groups, matching the
    ``line_length`` contract used by fallback text formatting.
    """

    if not isinstance(alphabet, str) or not alphabet:
        raise ValueError("alphabet must be a non-empty string")
    if any(character.isspace() for character in alphabet):
        raise ValueError("alphabet must not contain whitespace")
    if not isinstance(group_size, int) or isinstance(group_size, bool) or group_size <= 0:
        raise ValueError("group_size must be a positive integer")
    if not math.isfinite(max_width_mm) or max_width_mm <= 0:
        raise ValueError("max_width_mm must be finite and positive")
    if not math.isfinite(safety_mm) or safety_mm < 0:
        raise ValueError("safety_mm must be finite and non-negative")
    if safety_mm >= max_width_mm:
        raise ValueError("safety_mm must leave a positive usable width")

    glyph_widths = {
        character: _measured_width(surface, character, style=style) for character in alphabet
    }
    widest_character = max(alphabet, key=glyph_widths.__getitem__)
    if glyph_widths[widest_character] <= 0:
        raise ValueError("alphabet glyphs must have positive measured width")

    usable_width_mm = max_width_mm - safety_mm

    def candidate(group_count: int) -> str:
        return " ".join(widest_character * group_size for _ in range(group_count))

    if _measured_width(surface, candidate(1), style=style) > usable_width_mm:
        raise ValueError("grouped line cannot fit one encoded group")

    lower_group_count = 1
    upper_group_count = 2
    while _measured_width(surface, candidate(upper_group_count), style=style) <= usable_width_mm:
        lower_group_count = upper_group_count
        upper_group_count *= 2

    while upper_group_count - lower_group_count > 1:
        candidate_group_count = (lower_group_count + upper_group_count) // 2
        if (
            _measured_width(surface, candidate(candidate_group_count), style=style)
            <= usable_width_mm
        ):
            lower_group_count = candidate_group_count
        else:
            upper_group_count = candidate_group_count

    return len(candidate(lower_group_count))


def _measured_width(surface: PdfSurface, text: str, *, style: TextStyle) -> float:
    width_mm = surface.measure_text_width(text, style)
    if not math.isfinite(width_mm) or width_mm < 0:
        raise ValueError("surface returned an invalid measured text width")
    return width_mm


__all__ = ["measured_grouped_line_length"]
