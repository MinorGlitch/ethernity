"""Compatibility facade for render proof validation."""

from ethernity.render.validation import (
    validate_rendered_fallback_artifact,
    validate_rendered_pdf_artifact,
)

__all__ = ["validate_rendered_fallback_artifact", "validate_rendered_pdf_artifact"]
