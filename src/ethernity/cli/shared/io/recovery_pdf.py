#!/usr/bin/env python3
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

"""PDF fallback extraction helpers shared across recovery/document flows."""

from __future__ import annotations

import re

from pypdf import PdfReader

from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.cli.shared.io.fallback_parser import detect_fallback_section, filter_fallback_lines

_PDF_FALLBACK_LINE_NUMBER = re.compile(r"^(\d+)\.\s*(.+)$")
_PDF_FALLBACK_LINE_NUMBER_ONLY = re.compile(r"^(\d+)\.$")
_PDF_FALLBACK_BARE_NUMBER_ONLY = re.compile(r"^(\d+)$")
_PDF_FALLBACK_INDEXED_ROW = re.compile(r"^(\d+)\s+(.+)$")
_FALLBACK_SECTION_LABELS = {
    "auth": AUTH_FALLBACK_LABEL,
    "main": MAIN_FALLBACK_LABEL,
    "key": "KEY FRAME",
}
_KNOWN_NON_PAYLOAD_LINES = {
    "BACKUP SET",
    "DOCUMENT",
    "EXTENDED METADATA",
    "MANUAL ENTRY ONLY",
    "MASTER SIGNING PUBLIC KEY",
    "RECOVERY",
    "SHARD QUORUM",
}


def extract_pdf_fallback_lines_from_pdf(reader: PdfReader) -> list[str]:
    candidates = extract_pdf_fallback_line_candidates_from_pdf(reader)
    if not candidates:
        return []
    return candidates[0]


def extract_pdf_fallback_line_candidates_from_pdf(reader: PdfReader) -> list[list[str]]:
    candidates: list[list[str]] = []
    errors: list[ValueError] = []
    seen: set[tuple[str, ...]] = set()
    for raw_lines in _pdf_fallback_raw_line_sources(reader):
        try:
            candidate = extract_pdf_fallback_lines(raw_lines)
        except ValueError as exc:
            errors.append(exc)
            continue
        if not candidate:
            continue
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    if candidates:
        candidates.sort(key=fallback_extraction_score, reverse=True)
        return candidates
    if errors:
        raise errors[0]
    return []


def _pdf_fallback_raw_line_sources(reader: PdfReader) -> list[list[str]]:
    pieces: list[str] = []
    plain_lines: list[str] = []
    layout_lines: list[str] = []

    for page in reader.pages:
        page.extract_text(
            visitor_text=lambda text, _cm, _tm, _font_dict, _font_size: (
                pieces.append(text) if text.strip() else None
            )
        )

        plain_text = page.extract_text() or ""
        plain_lines.extend(plain_text.splitlines())

        layout_text = page.extract_text(extraction_mode="layout") or ""
        layout_lines.extend(layout_text.splitlines())

    joined_piece_lines = "".join(pieces).splitlines()
    sources: list[list[str]] = []
    for raw_lines in (pieces, joined_piece_lines, plain_lines, layout_lines):
        if raw_lines:
            sources.append(raw_lines)
    return sources


def extract_pdf_fallback_lines(lines: list[str]) -> list[str]:
    extracted: list[str] = []
    pending_sections: list[str] = []
    current_section: str | None = None
    pending_payload: str | None = None
    next_expected_line_number: int | None = None
    awaiting_payload_number: int | None = None

    def _queue_section(section: str) -> None:
        label = _FALLBACK_SECTION_LABELS[section]
        if current_section == label:
            return
        if pending_sections and pending_sections[-1] == label:
            return
        pending_sections.append(label)

    def _ensure_section() -> bool:
        nonlocal current_section, next_expected_line_number
        if current_section is not None:
            return True
        if not pending_sections:
            return False
        current_section = pending_sections.pop(0)
        extracted.append(current_section)
        next_expected_line_number = 1
        return True

    def _emit_payload(payload: str, *, line_number: int | None) -> bool:
        nonlocal current_section, next_expected_line_number
        if not _ensure_section():
            return False

        expected_line_number = 1 if next_expected_line_number is None else next_expected_line_number
        if line_number is not None and line_number != expected_line_number:
            if line_number == 1 and pending_sections:
                current_section = pending_sections.pop(0)
                extracted.append(current_section)
                expected_line_number = 1
            else:
                return False

        extracted.append(payload)
        if line_number is None:
            next_expected_line_number = expected_line_number + 1
        else:
            next_expected_line_number = line_number + 1
        return True

    def _flush_pending_payload(*, line_number: int | None = None) -> bool:
        nonlocal pending_payload
        if pending_payload is None:
            return False
        emitted = _emit_payload(pending_payload, line_number=line_number)
        if emitted:
            pending_payload = None
        return emitted

    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.upper() in _KNOWN_NON_PAYLOAD_LINES:
            continue
        section = detect_fallback_section(stripped)
        if section is not None:
            _flush_pending_payload()
            _queue_section(section)
            continue

        expected_line_number = 1 if next_expected_line_number is None else next_expected_line_number

        numbered_candidate = parse_pdf_fallback_payload_line(stripped)
        if numbered_candidate is not None:
            _flush_pending_payload()
            if _emit_payload(numbered_candidate[1], line_number=numbered_candidate[0]):
                continue

        numbered_only_match = _PDF_FALLBACK_LINE_NUMBER_ONLY.fullmatch(
            stripped
        ) or _PDF_FALLBACK_BARE_NUMBER_ONLY.fullmatch(stripped)
        if numbered_only_match is not None:
            if current_section is None and not pending_sections:
                continue
            line_number = int(numbered_only_match.group(1))
            if _flush_pending_payload(line_number=line_number):
                continue
            if line_number == expected_line_number or (line_number == 1 and pending_sections):
                awaiting_payload_number = line_number
            continue

        payload_candidate: str | None
        try:
            payload_candidate = normalize_pdf_fallback_payload_fragment(stripped)
        except ValueError:
            payload_candidate = None
        if payload_candidate is None:
            if awaiting_payload_number is not None:
                raise ValueError(
                    "fallback text contains non-empty lines with characters "
                    "outside the z-base-32 alphabet"
                )
            _flush_pending_payload()
            continue

        if awaiting_payload_number is not None:
            if _emit_payload(payload_candidate, line_number=awaiting_payload_number):
                awaiting_payload_number = None
                pending_payload = None
                continue
            awaiting_payload_number = None

        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if (
            _PDF_FALLBACK_LINE_NUMBER_ONLY.fullmatch(next_line) is not None
            or _PDF_FALLBACK_BARE_NUMBER_ONLY.fullmatch(next_line) is not None
        ):
            if current_section is None and not pending_sections:
                continue
            pending_payload = payload_candidate
            continue
        if not _looks_like_unindexed_payload_fragment(stripped):
            _flush_pending_payload()
            continue
        if pending_payload is not None:
            _flush_pending_payload()
        _emit_payload(payload_candidate, line_number=None)

    _flush_pending_payload()
    return extracted


def _extract_pdf_fallback_lines(lines: list[str]) -> list[str]:
    """Backward-compatible private alias used by existing unit tests."""

    return extract_pdf_fallback_lines(lines)


def normalize_pdf_fallback_payload_fragment(line: str) -> str:
    normalized = filter_fallback_lines([line])
    return normalized[0]


def normalized_fallback_payload_text(lines: list[str]) -> str:
    return "".join(ch.lower() for line in lines for ch in line if not ch.isspace() and ch != "-")


def fallback_extraction_score(lines: list[str]) -> tuple[int, int]:
    payload_lines = [line for line in lines if detect_fallback_section(line) is None]
    payload_chars = sum(len(normalized_fallback_payload_text([line])) for line in payload_lines)
    return payload_chars, len(lines)


def _fallback_extraction_score(lines: list[str]) -> tuple[int, int]:
    """Backward-compatible private alias used by existing unit tests."""

    return fallback_extraction_score(lines)


def _looks_like_unindexed_payload_fragment(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return any(ch.isspace() for ch in stripped)


def parse_pdf_fallback_payload_line(line: str) -> tuple[int, str] | None:
    numbered_match = _PDF_FALLBACK_LINE_NUMBER.fullmatch(line)
    if numbered_match is not None:
        payload = normalize_pdf_fallback_payload_fragment(numbered_match.group(2).strip())
        return int(numbered_match.group(1)), payload

    indexed_row_match = _PDF_FALLBACK_INDEXED_ROW.fullmatch(line)
    if indexed_row_match is None:
        return None

    line_number = int(indexed_row_match.group(1))
    tokens = indexed_row_match.group(2).split()
    while tokens:
        candidate = " ".join(tokens)
        try:
            normalized_candidate = normalize_pdf_fallback_payload_fragment(candidate)
        except ValueError:
            normalized_candidate = None
        if normalized_candidate is not None:
            return line_number, normalized_candidate
        trailing_token = tokens[-1]
        try:
            normalize_pdf_fallback_payload_fragment(trailing_token)
        except ValueError:
            pass
        else:
            return None
        tokens.pop()
    return None
