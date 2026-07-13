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
from ethernity.render.proofs import (
    RenderProofError,
    build_render_artifact_proof,
    frame_digest,
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_render_layout_proof,
    validate_text_in_pdf,
)
from ethernity.render.service import RenderService
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderComponentLayoutProof,
    RenderFallbackProof,
    RenderInputs,
    RenderLayoutProof,
    RenderLineage,
    RenderPageLayoutProof,
    RenderRectProof,
    RenderResult,
)

__all__ = [
    "FallbackSection",
    "RenderArtifactProof",
    "RenderComponentLayoutProof",
    "RenderFallbackProof",
    "RenderInputs",
    "RenderLayoutProof",
    "RenderLineage",
    "RenderPageLayoutProof",
    "RenderProofError",
    "RenderRectProof",
    "RenderResult",
    "RenderService",
    "build_render_artifact_proof",
    "frame_digest",
    "render_frames_to_pdf",
    "validate_fallback_render_proof",
    "validate_fallback_text_in_pdf",
    "validate_pdf_has_pages",
    "validate_render_artifact_proof",
    "validate_render_layout_proof",
    "validate_text_in_pdf",
]
