# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from ethernity.render.backend_dispatch import render_frames_to_pdf
from ethernity.render.checks import (
    RenderValidationError,
    build_rendered_document_summary,
    frame_digest,
    validate_fallback_summary,
    validate_fallback_text_in_pdf,
    validate_layout_report,
    validate_pdf_has_pages,
    validate_rendered_document_summary,
    validate_text_in_pdf,
)
from ethernity.render.service import RenderService
from ethernity.render.types import (
    ComponentLayout,
    DocumentOrigin,
    FallbackSection,
    FallbackSummary,
    LayoutReport,
    PageLayout,
    RenderedDocumentSummary,
    RenderInputs,
    RenderRect,
    RenderResult,
)

__all__ = [
    "FallbackSection",
    "RenderedDocumentSummary",
    "ComponentLayout",
    "FallbackSummary",
    "RenderInputs",
    "LayoutReport",
    "DocumentOrigin",
    "PageLayout",
    "RenderValidationError",
    "RenderRect",
    "RenderResult",
    "RenderService",
    "build_rendered_document_summary",
    "frame_digest",
    "render_frames_to_pdf",
    "validate_fallback_summary",
    "validate_fallback_text_in_pdf",
    "validate_pdf_has_pages",
    "validate_rendered_document_summary",
    "validate_layout_report",
    "validate_text_in_pdf",
]
