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
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ethernity.core.bounds import (
    MAX_FALLBACK_LINES,
    MAX_FALLBACK_NORMALIZED_CHARS,
    MAX_RECOVERY_TEXT_BYTES,
)
from ethernity.encoding.chunking import fallback_lines_to_frame
from ethernity.encoding.framing import Frame, encode_frame
from ethernity.encoding.zbase32 import ZBASE32_ALPHABET, encode_zbase32
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderLayoutProof,
)

_NUMBERED_FALLBACK_PREFIX = re.compile(r"(?<!\d)\d{1,4}\.\s*")
_ZBASE32_CHARS = frozenset(ZBASE32_ALPHABET)
_UNNUMBERED_FALLBACK_ANCHORS = frozenset(
    {
        "manual transcription",
        "scan in offline kit",
        "shard payload",
    }
)
_CANONICAL_FALLBACK_TITLES = frozenset(
    {"auth frame", "key frame", "main frame", "shard frame", "shard payload"}
)
_MAX_EXTRACTED_PDF_LINES = MAX_FALLBACK_LINES * 4
_PDF_TEXT_LINE_BREAKS = frozenset(
    {"\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"}
)


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


def validate_render_layout_proof(
    *,
    artifact_label: str,
    layout_proof: RenderLayoutProof | None,
    expected_page_count: int,
) -> None:
    """Require complete, non-overflowing measured layout evidence for a rendered artifact."""

    if layout_proof is None:
        raise RenderProofError(f"{artifact_label} is missing render layout proof")
    if (
        layout_proof.page_count != expected_page_count
        or len(layout_proof.pages) != expected_page_count
    ):
        raise RenderProofError(
            f"{artifact_label} layout proof page count does not match the PDF artifact",
            details={
                "expected_page_count": expected_page_count,
                "proof_page_count": layout_proof.page_count,
                "proof_page_entry_count": len(layout_proof.pages),
            },
        )
    expected_page_numbers = tuple(range(1, expected_page_count + 1))
    proof_page_numbers = tuple(page.page_number for page in layout_proof.pages)
    if proof_page_numbers != expected_page_numbers:
        raise RenderProofError(
            f"{artifact_label} layout proof page order does not match the PDF artifact",
            details={
                "expected_page_numbers": expected_page_numbers,
                "proof_page_numbers": proof_page_numbers,
            },
        )
    if layout_proof.overflow:
        overflow_components = tuple(
            component_id
            for page in layout_proof.pages
            for component_id in (*page.overflow_component_ids, *page.out_of_bounds_component_ids)
        )
        raise RenderProofError(
            f"{artifact_label} layout proof reports clipped or out-of-bounds content",
            details={"overflow_component_ids": overflow_components[:10]},
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
    fallback_sections: Sequence[FallbackSection],
    fallback_proof: RenderFallbackProof | None = None,
) -> None:
    """Decode extracted fallback text and require exact, ordered frame equality."""

    sections = tuple(fallback_sections)
    if not sections:
        raise RenderProofError(f"{artifact_label} has no expected fallback sections")
    _validate_fallback_proof_titles(
        artifact_label=artifact_label,
        sections=sections,
        fallback_proof=fallback_proof,
    )
    extracted_lines = _bounded_extracted_pdf_lines(reader, artifact_label=artifact_label)
    regions = _fallback_section_regions(
        extracted_lines,
        sections=sections,
        artifact_label=artifact_label,
    )
    actual_frames: list[Frame] = []
    for index, (section, region) in enumerate(zip(sections, regions, strict=True)):
        expected_encoded_length = len(encode_zbase32(encode_frame(section.frame)))
        encoded = _extract_numbered_fallback_payload(
            region,
            expected_encoded_length=expected_encoded_length,
        )
        actual_frame = _try_decode_fallback_frame(encoded)
        if actual_frame is not None and _has_designated_unnumbered_payload(region):
            raise RenderProofError(
                f"{artifact_label} fallback section {index + 1} contains an extra payload region",
                details={"section_index": index, "section_label": section.label},
            )
        if actual_frame is None:
            encoded = _extract_unnumbered_fallback_payload(
                region,
                artifact_label=artifact_label,
                section_index=index,
                section_label=section.label,
            )
            actual_frame = _try_decode_fallback_frame(encoded)
        if actual_frame is None:
            raise RenderProofError(
                f"{artifact_label} fallback section {index + 1} is malformed or incomplete",
                details={"section_index": index, "section_label": section.label},
            )
        actual_frames.append(actual_frame)

    for index, (section, actual_frame) in enumerate(zip(sections, actual_frames, strict=True)):
        expected_frame = section.frame
        if actual_frame.frame_type != expected_frame.frame_type:
            reason = "frame role"
        elif actual_frame.doc_id != expected_frame.doc_id:
            reason = "document identity"
        elif encode_frame(actual_frame) != encode_frame(expected_frame):
            reason = "canonical frame bytes"
        else:
            continue
        raise RenderProofError(
            f"{artifact_label} fallback section {index + 1} does not match its expected {reason}",
            details={
                "section_index": index,
                "section_label": section.label,
                "expected_frame_type": int(expected_frame.frame_type),
                "actual_frame_type": int(actual_frame.frame_type),
                "expected_doc_id": expected_frame.doc_id.hex(),
                "actual_doc_id": actual_frame.doc_id.hex(),
            },
        )


def _validate_fallback_proof_titles(
    *,
    artifact_label: str,
    sections: Sequence[FallbackSection],
    fallback_proof: RenderFallbackProof | None,
) -> None:
    if fallback_proof is None:
        return
    expected_titles = tuple(
        section.label.strip() for section in sections if section.label and section.label.strip()
    )
    if tuple(fallback_proof.section_titles) != expected_titles:
        raise RenderProofError(
            f"{artifact_label} fallback proof section labels do not match render inputs",
            details={
                "expected_section_titles": expected_titles,
                "proof_section_titles": fallback_proof.section_titles,
            },
        )


def _bounded_extracted_pdf_lines(reader: PdfReader, *, artifact_label: str) -> tuple[str, ...]:
    extracted_parts: list[str] = []
    extracted_bytes = 0
    extracted_line_count = 0
    for page in reader.pages:
        page_text = page.extract_text() or ""
        page_bytes = len(page_text.encode("utf-8"))
        extracted_bytes += page_bytes
        if extracted_bytes > MAX_RECOVERY_TEXT_BYTES:
            raise RenderProofError(
                f"{artifact_label} extracted text exceeds MAX_RECOVERY_TEXT_BYTES "
                f"({MAX_RECOVERY_TEXT_BYTES})",
                details={"extracted_text_bytes": extracted_bytes},
            )
        extracted_line_count += _conservative_split_line_count(page_text)
        if extracted_line_count > _MAX_EXTRACTED_PDF_LINES:
            raise RenderProofError(
                f"{artifact_label} extracted text exceeds the operational PDF line limit "
                f"({_MAX_EXTRACTED_PDF_LINES})",
                details={"extracted_line_count": extracted_line_count},
            )
        page_lines = page_text.splitlines()
        extracted_parts.extend(page_lines)
    return tuple(extracted_parts)


def _conservative_split_line_count(value: str) -> int:
    """Bound splitlines allocation without charging metadata against fallback-line limits."""

    if not value:
        return 0
    line_count = 1
    index = 0
    while index < len(value):
        char = value[index]
        if char in _PDF_TEXT_LINE_BREAKS:
            line_count += 1
            if char == "\r" and index + 1 < len(value) and value[index + 1] == "\n":
                index += 1
        index += 1
    return line_count


def _fallback_section_regions(
    lines: Sequence[str],
    *,
    sections: Sequence[FallbackSection],
    artifact_label: str,
) -> tuple[tuple[str, ...], ...]:
    labels = tuple(section.label.strip() if section.label else None for section in sections)
    normalized_lines = tuple(_normalize_section_title(line) for line in lines)
    if not any(labels):
        if len(sections) != 1:
            raise RenderProofError(
                f"{artifact_label} has multiple unlabeled fallback sections",
            )
        unexpected_titles = sorted(
            {
                line
                for line in normalized_lines
                if line in _CANONICAL_FALLBACK_TITLES and line != "shard payload"
            }
        )
        if unexpected_titles:
            raise RenderProofError(
                f"{artifact_label} contains unexpected fallback section labels",
                details={"unexpected_section_titles": tuple(unexpected_titles)},
            )
        return (tuple(lines),)
    if any(label is None for label in labels):
        raise RenderProofError(f"{artifact_label} mixes labeled and unlabeled fallback sections")

    expected_normalized_labels = {_normalize_section_title(label) for label in labels if label}
    unexpected_titles = sorted(
        {
            line
            for line in normalized_lines
            if line in _CANONICAL_FALLBACK_TITLES and line not in expected_normalized_labels
        }
    )
    if unexpected_titles:
        raise RenderProofError(
            f"{artifact_label} contains unexpected fallback section labels",
            details={"unexpected_section_titles": tuple(unexpected_titles)},
        )
    positions: list[int] = []
    final_positions: list[int] = []
    section_label_groups: list[tuple[tuple[int, ...], ...]] = []
    for label in labels:
        assert label is not None
        normalized_label = _normalize_section_title(label)
        matches = [index for index, line in enumerate(normalized_lines) if line == normalized_label]
        match_groups = _consecutive_index_groups(matches)
        if not match_groups:
            raise RenderProofError(
                f"{artifact_label} is missing the {label!r} fallback section label",
                details={"section_label": label, "label_occurrences": 0},
            )
        if normalized_label in {"auth frame", "main frame"} and len(match_groups) != 1:
            raise RenderProofError(
                f"{artifact_label} contains a duplicate {label!r} fallback section label",
                details={"section_label": label, "label_group_count": len(match_groups)},
            )
        positions.append(match_groups[0][-1])
        final_positions.append(match_groups[-1][-1])
        section_label_groups.append(match_groups)
    if positions != sorted(positions) or any(
        final_positions[index] >= positions[index + 1] for index in range(len(positions) - 1)
    ):
        raise RenderProofError(
            f"{artifact_label} fallback section labels are reordered",
            details={"section_positions": tuple(positions)},
        )
    for section_index, match_groups in enumerate(section_label_groups):
        next_section_start = (
            positions[section_index + 1] if section_index + 1 < len(positions) else len(lines)
        )
        for group_index, group in enumerate(match_groups):
            region_end = (
                match_groups[group_index + 1][0]
                if group_index + 1 < len(match_groups)
                else next_section_start
            )
            continuation_region = lines[group[-1] + 1 : region_end]
            if not _region_contains_fallback_payload(continuation_region):
                label = labels[section_index]
                raise RenderProofError(
                    f"{artifact_label} contains an empty or duplicate {label!r} "
                    "fallback section label",
                    details={"section_label": label, "label_group_index": group_index},
                )
    return tuple(
        tuple(lines[start + 1 : positions[index + 1] if index + 1 < len(positions) else None])
        for index, start in enumerate(positions)
    )


def _normalize_section_title(value: str) -> str:
    if not value.isascii():
        return ""
    normalized = " ".join(value.casefold().split())
    return normalized.strip("=-: ")


def _consecutive_index_groups(indexes: Sequence[int]) -> tuple[tuple[int, ...], ...]:
    groups: list[list[int]] = []
    for index in indexes:
        if not groups or index != groups[-1][-1] + 1:
            groups.append([index])
        else:
            groups[-1].append(index)
    return tuple(tuple(group) for group in groups)


def _extract_numbered_fallback_payload(
    lines: Sequence[str],
    *,
    expected_encoded_length: int | None = None,
) -> str | None:
    numbered: list[str] = []
    encoded_length = 0
    complete = False
    for line in lines:
        matches = tuple(_NUMBERED_FALLBACK_PREFIX.finditer(line))
        line_has_payload = False
        for match_index, match in enumerate(matches):
            end = matches[match_index + 1].start() if match_index + 1 < len(matches) else len(line)
            payload = _normalize_extracted_payload(line[match.end() : end])
            if payload is None:
                continue
            line_has_payload = True
            if complete:
                return ""
            if len(numbered) >= MAX_FALLBACK_LINES:
                return ""
            numbered.append(payload)
            encoded_length += len(payload)
            if expected_encoded_length is not None:
                if encoded_length > expected_encoded_length:
                    return ""
                if encoded_length == expected_encoded_length:
                    complete = True
        if complete and not line_has_payload and line.strip():
            break
    if not numbered:
        return None
    encoded = "".join(numbered)
    if len(encoded) > MAX_FALLBACK_NORMALIZED_CHARS:
        return ""
    return encoded


def _region_contains_fallback_payload(lines: Sequence[str]) -> bool:
    if _extract_numbered_fallback_payload(lines) is not None:
        return True
    if _first_payload_run(lines):
        return True
    return _has_designated_unnumbered_payload(lines)


def _try_decode_fallback_frame(encoded: str | None) -> Frame | None:
    if not encoded:
        return None
    try:
        return fallback_lines_to_frame((encoded,))
    except ValueError:
        return None


def _extract_unnumbered_fallback_payload(
    lines: Sequence[str],
    *,
    artifact_label: str,
    section_index: int,
    section_label: str | None,
) -> str:
    normalized_section_label = (
        _normalize_section_title(section_label) if section_label is not None else None
    )
    anchor_indexes = [
        index
        for index, line in enumerate(lines)
        if _normalize_visual_heading(line) in _UNNUMBERED_FALLBACK_ANCHORS
        or (
            normalized_section_label is not None
            and _normalize_section_title(line) == normalized_section_label
        )
    ]
    payload_runs: list[tuple[str, ...]] = []
    if section_label is not None:
        initial_run = _first_payload_run(lines)
        if initial_run:
            payload_runs.append(initial_run)
    if anchor_indexes:
        for anchor_index in anchor_indexes:
            run = _consecutive_payload_lines(lines, start=anchor_index + 1)
            if run:
                payload_runs.append(run)
    if not payload_runs:
        raise RenderProofError(
            f"{artifact_label} fallback section {section_index + 1} has no designated "
            "extractable payload region",
            details={"section_index": section_index},
        )
    candidate_stream = "".join(payload for run in payload_runs for payload in run)
    payload_line_count = sum(len(run) for run in payload_runs)
    if payload_line_count > MAX_FALLBACK_LINES:
        raise RenderProofError(
            f"{artifact_label} fallback section {section_index + 1} exceeds "
            f"MAX_FALLBACK_LINES ({MAX_FALLBACK_LINES})",
        )
    if len(candidate_stream) > MAX_FALLBACK_NORMALIZED_CHARS:
        raise RenderProofError(
            f"{artifact_label} fallback section {section_index + 1} exceeds "
            f"MAX_FALLBACK_NORMALIZED_CHARS ({MAX_FALLBACK_NORMALIZED_CHARS})",
        )
    return candidate_stream


def _normalize_visual_heading(value: str) -> str:
    stripped = value.strip()
    while stripped and unicodedata.category(stripped[0]) in {"Cf", "Co"}:
        stripped = stripped[1:].lstrip()
    while stripped and unicodedata.category(stripped[-1]) in {"Cf", "Co"}:
        stripped = stripped[:-1].rstrip()
    if not stripped.isascii():
        return ""
    return " ".join(stripped.casefold().split())


def _has_designated_unnumbered_payload(lines: Sequence[str]) -> bool:
    for index, line in enumerate(lines):
        if _normalize_visual_heading(line) not in _UNNUMBERED_FALLBACK_ANCHORS:
            continue
        if _consecutive_payload_lines(lines, start=index + 1):
            return True
    return False


def _consecutive_payload_lines(lines: Sequence[str], *, start: int) -> tuple[str, ...]:
    payloads: list[str] = []
    for line in lines[start:]:
        payload = _normalize_extracted_unnumbered_payload(line)
        if payload is None:
            break
        payloads.append(payload)
    return tuple(payloads)


def _first_payload_run(lines: Sequence[str]) -> tuple[str, ...]:
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if _normalize_extracted_unnumbered_payload(line) is not None:
            return _consecutive_payload_lines(lines, start=index)
        return ()
    return ()


def _normalize_extracted_unnumbered_payload(value: str) -> str | None:
    stripped = value.strip()
    while stripped and unicodedata.category(stripped[-1]) in {"Cf", "Co"}:
        stripped = stripped[:-1].rstrip()
    if not stripped:
        return None
    tokens = stripped.replace("-", " ").split()
    if not tokens or any(len(token) != 4 for token in tokens[:-1]):
        return None
    if not 1 <= len(tokens[-1]) <= 4:
        return None
    if any(
        not char.isascii() or char.lower() not in _ZBASE32_CHARS
        for token in tokens
        for char in token
    ):
        return None
    return "".join(token.lower() for token in tokens)


def _normalize_extracted_payload(value: str) -> str | None:
    stripped = value.strip()
    while stripped and unicodedata.category(stripped[-1]) in {"Cf", "Co"}:
        stripped = stripped[:-1].rstrip()
    if not stripped:
        return None
    normalized: list[str] = []
    for char in stripped:
        if char.isspace() or char == "-":
            continue
        if not char.isascii():
            return None
        lowered = char.lower()
        if lowered not in _ZBASE32_CHARS:
            return None
        normalized.append(lowered)
    return "".join(normalized) or None


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
