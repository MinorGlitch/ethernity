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

"""Proof validation for rendered CLI artifacts."""

from __future__ import annotations

from ethernity.render.proofs import (
    RenderProofError,
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_render_layout_proof,
    validate_text_in_pdf,
)
from ethernity.render.types import RenderInputs, RenderResult


def validate_rendered_fallback_artifact(
    *,
    inputs: RenderInputs,
    result: RenderResult,
    artifact_label: str,
) -> None:
    """Validate an emitted fallback PDF in its established proof-check order."""

    fallback_sections = tuple(inputs.fallback_sections or ())
    validate_render_artifact_proof(
        artifact_label=artifact_label,
        inputs=inputs,
        artifact_proof=result.artifact_proof,
    )
    reader = validate_pdf_has_pages(inputs.output_path, artifact_label=artifact_label)
    validate_render_layout_proof(
        artifact_label=artifact_label,
        layout_proof=result.layout_proof,
        expected_page_count=len(reader.pages),
    )
    fallback_proof = (
        result.artifact_proof.fallback_proof if result.artifact_proof is not None else None
    ) or result.fallback_proof
    validate_fallback_render_proof(
        artifact_label=artifact_label,
        frames=tuple(section.frame for section in fallback_sections),
        fallback_proof=fallback_proof,
    )
    validate_fallback_text_in_pdf(
        artifact_label=artifact_label,
        reader=reader,
        fallback_sections=fallback_sections,
        fallback_proof=fallback_proof,
    )


def validate_rendered_pdf_artifact(
    *,
    inputs: RenderInputs,
    result: object,
    artifact_label: str,
    expected_text: tuple[str, ...] = (),
) -> None:
    """Validate a renderer result, its proof metadata, and its emitted PDF."""

    if not isinstance(result, RenderResult):
        raise RenderProofError(
            f"{artifact_label} renderer did not return RenderResult",
            details={"result_type": type(result).__name__},
        )
    artifact_proof = result.artifact_proof
    if artifact_proof is None:
        raise RenderProofError(f"{artifact_label} is missing render artifact proof")
    validate_render_artifact_proof(
        artifact_label=artifact_label,
        inputs=inputs,
        artifact_proof=artifact_proof,
    )
    reader = validate_pdf_has_pages(inputs.output_path, artifact_label=artifact_label)
    if inputs.render_fallback:
        fallback_sections = tuple(inputs.fallback_sections or ())
        fallback_proof = artifact_proof.fallback_proof or result.fallback_proof
        validate_fallback_render_proof(
            artifact_label=artifact_label,
            frames=tuple(section.frame for section in fallback_sections),
            fallback_proof=fallback_proof,
        )
        validate_render_layout_proof(
            artifact_label=artifact_label,
            layout_proof=result.layout_proof,
            expected_page_count=len(reader.pages),
        )
        validate_fallback_text_in_pdf(
            artifact_label=artifact_label,
            reader=reader,
            fallback_sections=fallback_sections,
            fallback_proof=fallback_proof,
        )
    if expected_text:
        validate_text_in_pdf(
            artifact_label=artifact_label,
            reader=reader,
            expected_text=expected_text,
            details_key="missing_component_ids",
            missing_message=f"{artifact_label} is missing expected inventory rows",
        )


__all__ = ["validate_rendered_fallback_artifact", "validate_rendered_pdf_artifact"]
