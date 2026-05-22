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

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest import mock

from fpdf import FPDF

from ethernity.encoding.framing import encode_frame
from ethernity.render.proofs import build_render_artifact_proof
from ethernity.render.types import RenderFallbackProof, RenderInputs, RenderResult


def _fallback_proof_for_inputs(inputs: RenderInputs) -> RenderFallbackProof | None:
    sections = tuple(inputs.fallback_sections or ())
    if not sections:
        return None
    titles = tuple(
        section.label.strip()
        for section in sections
        if isinstance(section.label, str) and section.label.strip()
    )
    return RenderFallbackProof(
        section_frame_digests=tuple(
            hashlib.sha256(encode_frame(section.frame)).hexdigest() for section in sections
        ),
        section_titles=titles,
        expected_section_count=len(sections),
        emitted_block_count=len(sections),
        emitted_line_count=len(titles),
        consumed_section_count=len(sections),
        fully_consumed=True,
        emitted_fallback_lines=titles,
    )


def _write_test_render_pdf(
    inputs: RenderInputs, fallback_proof: RenderFallbackProof | None
) -> None:
    output_path = Path(inputs.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["Rendered test document"]
    if fallback_proof is not None:
        lines.extend(fallback_proof.section_titles)
        lines.extend(fallback_proof.emitted_fallback_lines)
    rows = inputs.context.get("inventory_rows")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                lines.append(str(row.get("component_id", "")))
                lines.append(str(row.get("detail", "")))
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(w=0, text="\n".join(lines))
    pdf.output(str(output_path))


def render_result_for_inputs(inputs: RenderInputs) -> RenderResult:
    fallback_proof = _fallback_proof_for_inputs(inputs)
    _write_test_render_pdf(inputs, fallback_proof)
    qr_payload_count = len(inputs.qr_payloads or inputs.frames)
    physical_qr_payload_indexes = tuple(range(qr_payload_count)) if inputs.render_qr else ()
    return RenderResult(
        artifact_proof=build_render_artifact_proof(
            inputs,
            encoded_payload_count=qr_payload_count,
            physical_qr_count=len(physical_qr_payload_indexes),
            physical_qr_payload_indexes=physical_qr_payload_indexes,
            page_count=1,
            fallback_proof=fallback_proof,
        ),
        fallback_proof=fallback_proof,
    )


def patch_render_frames_to_pdf(calls: list[object] | None = None):
    def _render(inputs: RenderInputs) -> RenderResult:
        if calls is not None:
            calls.append(inputs)
        return render_result_for_inputs(inputs)

    return mock.patch("ethernity.render.render_frames_to_pdf", side_effect=_render)
