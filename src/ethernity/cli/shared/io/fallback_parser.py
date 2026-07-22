"""Compatibility facade for fallback-text parsing."""

from ethernity.encoding.fallback_text import (
    contains_fallback_markers,
    detect_fallback_section,
    filter_fallback_lines,
    format_fallback_error,
    parse_fallback_frame,
    split_fallback_sections,
)

__all__ = [
    "contains_fallback_markers",
    "detect_fallback_section",
    "filter_fallback_lines",
    "format_fallback_error",
    "parse_fallback_frame",
    "split_fallback_sections",
]
