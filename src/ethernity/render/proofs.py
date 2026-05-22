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

"""Shared render proof construction and validation helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ethernity.encoding.framing import Frame, encode_frame
from ethernity.render.types import RenderArtifactProof, RenderFallbackProof, RenderInputs


class RenderProofError(ValueError):
    """Raised when a rendered artifact does not match its proof contract."""

    def __init__(self, message: str, *, details: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


def frame_digest(frame: Frame) -> str:
    """Return the stable digest used by render proofs for a frame."""

    return hashlib.sha256(encode_frame(frame)).hexdigest()


def qr_payload_digest(payload: bytes | str) -> str:
    """Return the stable digest used by render proofs for an encoded QR payload."""

    digest = hashlib.sha256()
    if isinstance(payload, str):
        digest.update(b"str\x00")
        digest.update(payload.encode("utf-8"))
    else:
        digest.update(b"bytes\x00")
        digest.update(bytes(payload))
    return digest.hexdigest()


def build_render_artifact_proof(
    inputs: RenderInputs,
    *,
    qr_payloads: Sequence[bytes | str] | None = None,
    encoded_payload_count: int,
    physical_qr_count: int,
    physical_qr_payload_indexes: Sequence[int] | None = None,
    page_count: int = 0,
    fallback_proof: RenderFallbackProof | None,
) -> RenderArtifactProof:
    """Build the app-wide render proof for one PDF artifact."""

    if qr_payloads is not None:
        planned_payloads = tuple(qr_payloads)
    elif inputs.qr_payloads is not None:
        planned_payloads = tuple(inputs.qr_payloads)
    else:
        planned_payloads = tuple(encode_frame(frame) for frame in inputs.frames)
    qr_payload_digests = tuple(qr_payload_digest(payload) for payload in planned_payloads)
    physical_indexes = tuple(physical_qr_payload_indexes or ())
    if physical_indexes:
        _validate_physical_qr_indexes(
            physical_indexes,
            expected_encoded_payload_count=len(qr_payload_digests),
        )
    physical_payload_digests = tuple(qr_payload_digests[index] for index in physical_indexes)

    return RenderArtifactProof(
        output_path=str(inputs.output_path),
        doc_type=inputs.doc_type,
        frame_digests=tuple(frame_digest(frame) for frame in inputs.frames),
        encoded_payload_count=encoded_payload_count,
        physical_qr_count=physical_qr_count,
        page_count=page_count,
        fallback_proof=fallback_proof,
        qr_payload_digests=qr_payload_digests,
        physical_qr_payload_indexes=physical_indexes,
        physical_qr_payload_digests=physical_payload_digests,
    )


def validate_pdf_has_pages(path: str | Path, *, artifact_label: str | None = None) -> PdfReader:
    """Load a rendered PDF and require it to contain at least one page."""

    artifact_path = Path(path)
    label = artifact_label or artifact_path.name
    try:
        reader = PdfReader(str(artifact_path))
    except Exception as exc:
        raise RenderProofError(f"{label} is invalid: {exc}", details={"path": str(path)}) from exc
    if len(reader.pages) <= 0:
        raise RenderProofError(
            f"{label} must contain at least one page",
            details={"path": str(path)},
        )
    return reader


def validate_fallback_render_proof(
    *,
    artifact_label: str,
    frames: Sequence[Frame],
    fallback_proof: RenderFallbackProof | None,
) -> None:
    """Validate that fallback proof data matches the planned fallback frames."""

    if fallback_proof is None:
        raise RenderProofError(f"{artifact_label} is missing fallback render proof")
    expected_digests = tuple(frame_digest(frame) for frame in frames)
    if fallback_proof.section_frame_digests != expected_digests:
        raise RenderProofError(
            f"{artifact_label} fallback proof does not match the planned fallback frames"
        )
    if (
        fallback_proof.expected_section_count != len(frames)
        or fallback_proof.consumed_section_count != len(frames)
        or not fallback_proof.fully_consumed
        or fallback_proof.emitted_block_count <= 0
        or fallback_proof.emitted_line_count <= 0
        or fallback_proof.emitted_line_count != len(fallback_proof.emitted_fallback_lines)
    ):
        raise RenderProofError(
            f"{artifact_label} did not emit all fallback recovery sections",
            details={
                "expected_section_count": len(frames),
                "proof_expected_section_count": fallback_proof.expected_section_count,
                "consumed_section_count": fallback_proof.consumed_section_count,
                "emitted_block_count": fallback_proof.emitted_block_count,
                "emitted_line_count": fallback_proof.emitted_line_count,
                "emitted_fallback_line_count": len(fallback_proof.emitted_fallback_lines),
                "fully_consumed": fallback_proof.fully_consumed,
            },
        )


def validate_render_artifact_proof(
    *,
    artifact_label: str,
    inputs: RenderInputs,
    artifact_proof: RenderArtifactProof | None,
) -> None:
    """Validate that an artifact proof matches the render inputs that produced it."""

    if artifact_proof is None:
        raise RenderProofError(f"{artifact_label} is missing render artifact proof")
    if Path(artifact_proof.output_path) != Path(inputs.output_path):
        raise RenderProofError(
            f"{artifact_label} proof output path does not match render inputs",
            details={
                "expected_output_path": str(inputs.output_path),
                "proof_output_path": artifact_proof.output_path,
            },
        )
    if artifact_proof.doc_type != inputs.doc_type:
        raise RenderProofError(
            f"{artifact_label} proof doc_type does not match render inputs",
            details={
                "expected_doc_type": inputs.doc_type,
                "proof_doc_type": artifact_proof.doc_type,
            },
        )
    expected_frame_digests = tuple(frame_digest(frame) for frame in inputs.frames)
    if artifact_proof.frame_digests != expected_frame_digests:
        raise RenderProofError(
            f"{artifact_label} proof frame digests do not match render inputs",
            details={
                "expected_frame_count": len(expected_frame_digests),
                "proof_frame_count": len(artifact_proof.frame_digests),
            },
        )
    expected_encoded_payload_count = len(inputs.qr_payloads or inputs.frames)
    if artifact_proof.encoded_payload_count != expected_encoded_payload_count:
        raise RenderProofError(
            f"{artifact_label} proof encoded payload count does not match render inputs",
            details={
                "expected_encoded_payload_count": expected_encoded_payload_count,
                "proof_encoded_payload_count": artifact_proof.encoded_payload_count,
            },
        )
    expected_qr_payload_digests = _expected_qr_payload_digests(inputs)
    proof_qr_payload_digests = (
        artifact_proof.qr_payload_digests
        if artifact_proof.qr_payload_digests
        else expected_qr_payload_digests
    )
    if proof_qr_payload_digests != expected_qr_payload_digests:
        raise RenderProofError(
            f"{artifact_label} proof QR payload digests do not match render inputs",
            details={
                "expected_qr_payload_count": len(expected_qr_payload_digests),
                "proof_qr_payload_count": len(proof_qr_payload_digests),
            },
        )
    if not inputs.render_qr and artifact_proof.physical_qr_count != 0:
        raise RenderProofError(
            f"{artifact_label} proof physical QR count does not match render inputs",
            details={
                "expected_physical_qr_count": 0,
                "proof_physical_qr_count": artifact_proof.physical_qr_count,
            },
        )
    if not inputs.render_qr and (
        artifact_proof.physical_qr_payload_indexes or artifact_proof.physical_qr_payload_digests
    ):
        raise RenderProofError(
            f"{artifact_label} proof physical QR payloads do not match render inputs",
            details={
                "expected_physical_qr_count": 0,
                "proof_physical_qr_payload_count": len(artifact_proof.physical_qr_payload_digests),
            },
        )
    if inputs.render_qr and artifact_proof.physical_qr_count < expected_encoded_payload_count:
        raise RenderProofError(
            f"{artifact_label} proof physical QR count is below render inputs",
            details={
                "minimum_physical_qr_count": expected_encoded_payload_count,
                "proof_physical_qr_count": artifact_proof.physical_qr_count,
            },
        )
    if inputs.render_qr:
        _validate_physical_qr_indexes(
            artifact_proof.physical_qr_payload_indexes,
            expected_encoded_payload_count=expected_encoded_payload_count,
        )
        expected_physical_digests = tuple(
            expected_qr_payload_digests[index]
            for index in artifact_proof.physical_qr_payload_indexes
        )
        if artifact_proof.physical_qr_payload_digests != expected_physical_digests:
            raise RenderProofError(
                f"{artifact_label} proof physical QR payload digests do not match QR indexes",
                details={
                    "proof_physical_qr_count": artifact_proof.physical_qr_count,
                    "proof_physical_qr_payload_count": len(
                        artifact_proof.physical_qr_payload_digests
                    ),
                },
            )
        if (
            len(artifact_proof.physical_qr_payload_indexes) != artifact_proof.physical_qr_count
            or len(artifact_proof.physical_qr_payload_digests) != artifact_proof.physical_qr_count
        ):
            raise RenderProofError(
                f"{artifact_label} proof physical QR payload count does not match placements",
                details={
                    "proof_physical_qr_count": artifact_proof.physical_qr_count,
                    "proof_physical_qr_index_count": len(
                        artifact_proof.physical_qr_payload_indexes
                    ),
                    "proof_physical_qr_payload_count": len(
                        artifact_proof.physical_qr_payload_digests
                    ),
                },
            )
        if _first_physical_qr_occurrences(artifact_proof.physical_qr_payload_indexes) != tuple(
            range(expected_encoded_payload_count)
        ):
            raise RenderProofError(
                f"{artifact_label} proof physical QR placements omit or reorder payloads",
                details={
                    "expected_payload_indexes": tuple(range(expected_encoded_payload_count)),
                    "proof_first_payload_indexes": _first_physical_qr_occurrences(
                        artifact_proof.physical_qr_payload_indexes
                    ),
                },
            )


def _expected_qr_payload_digests(inputs: RenderInputs) -> tuple[str, ...]:
    payloads: Sequence[bytes | str]
    if inputs.qr_payloads is not None:
        payloads = inputs.qr_payloads
    else:
        payloads = tuple(encode_frame(frame) for frame in inputs.frames)
    return tuple(qr_payload_digest(payload) for payload in payloads)


def _validate_physical_qr_indexes(
    indexes: Sequence[int],
    *,
    expected_encoded_payload_count: int,
) -> None:
    for index in indexes:
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= expected_encoded_payload_count
        ):
            raise RenderProofError(
                "render proof contains an invalid physical QR payload index",
                details={
                    "invalid_index": index,
                    "expected_encoded_payload_count": expected_encoded_payload_count,
                },
            )


def _first_physical_qr_occurrences(indexes: Sequence[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    first_indexes: list[int] = []
    for index in indexes:
        if index in seen:
            continue
        seen.add(index)
        first_indexes.append(index)
    return tuple(first_indexes)


def validate_fallback_text_in_pdf(
    *,
    artifact_label: str,
    reader: PdfReader,
    fallback_proof: RenderFallbackProof | None,
) -> None:
    """Validate that emitted fallback titles and lines are present in extracted PDF text."""

    if fallback_proof is None:
        return
    raw_extracted_text = extract_pdf_text(reader)
    extracted_text = normalize_pdf_text(raw_extracted_text)
    compact_extracted_text = compact_fallback_text(raw_extracted_text)
    missing_titles = [
        title
        for title in fallback_proof.section_titles
        if title and normalize_pdf_text(title) not in extracted_text
    ]
    missing_lines = [
        line
        for line in fallback_proof.emitted_fallback_lines
        if line
        and not fallback_line_present(
            line,
            extracted_text=extracted_text,
            compact_extracted_text=compact_extracted_text,
        )
    ]
    if missing_titles or missing_lines:
        raise RenderProofError(
            f"{artifact_label} is missing fallback text from the PDF artifact",
            details={
                "missing_section_titles": missing_titles[:3],
                "missing_fallback_lines": missing_lines[:3],
                "missing_section_title_count": len(missing_titles),
                "missing_fallback_line_count": len(missing_lines),
            },
        )


def validate_text_in_pdf(
    *,
    artifact_label: str,
    reader: PdfReader,
    expected_text: Sequence[str],
    details_key: str = "missing_text",
    missing_message: str | None = None,
) -> None:
    """Validate that expected text fragments are present in extracted PDF text."""

    extracted_text = extract_pdf_text(reader)
    missing = [value for value in expected_text if value and value not in extracted_text]
    if missing:
        message = (
            f"{missing_message}: {', '.join(missing[:3])}"
            if missing_message is not None
            else f"{artifact_label} is missing expected text: {', '.join(missing[:3])}"
        )
        raise RenderProofError(
            message,
            details={details_key: missing[:3], f"{details_key}_count": len(missing)},
        )


def extract_pdf_text(reader: PdfReader) -> str:
    """Extract text from all pages in a PDF reader."""

    return "\n".join((page.extract_text() or "") for page in reader.pages)


def normalize_pdf_text(value: Any) -> str:
    """Normalize text for PDF proof comparisons."""

    return " ".join(str(value).lower().split())


def compact_fallback_text(value: Any) -> str:
    """Normalize fallback payload text for PDF extraction comparisons."""

    return "".join(ch for ch in str(value).lower() if not ch.isspace() and ch != "-")


def fallback_line_present(
    line: str,
    *,
    extracted_text: str,
    compact_extracted_text: str,
) -> bool:
    normalized = normalize_pdf_text(line)
    if normalized in extracted_text:
        return True
    compact = compact_fallback_text(line)
    return bool(compact and compact in compact_extracted_text)
