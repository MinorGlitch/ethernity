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

"""Fallback-PDF validation helpers for extend execution."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader

from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.cli.shared.io.fallback_parser import (
    detect_fallback_section,
    filter_fallback_lines,
    split_fallback_sections,
)
from ethernity.cli.shared.io.recovery_pdf import (
    extract_pdf_fallback_line_candidates_from_pdf as shared_extract_pdf_fallback_line_candidates,
)
from ethernity.cli.shared.ndjson import ApiCommandError

from .models import EXTENSION_MAIN_CARRIER_INVALID

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


def validate_fallback_recovery_document(
    *,
    path: Path,
    expected_ciphertext: bytes,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
    expected_recovery_fallback_lines: tuple[str, ...] | None,
    quiet: bool,
    pdf_reader_factory: Callable[[str], PdfReader] = PdfReader,
    extract_pdf_fallback_lines_from_pdf: Callable[[PdfReader], list[str]] | None = None,
    validate_pdf_fallback_main_section_fn: Callable[..., None] | None = None,
    frame_from_fallback_lines: Callable[..., Any] | None = None,
    resolve_auth_payload: Callable[..., tuple[Any, str]] | None = None,
) -> None:
    _ = expected_ciphertext
    validate_main = validate_pdf_fallback_main_section_fn or validate_pdf_fallback_main_section
    build_auth_frame = frame_from_fallback_lines
    resolve_auth = resolve_auth_payload
    if build_auth_frame is None or resolve_auth is None:
        raise ValueError("fallback recovery validation requires auth frame and AUTH resolver hooks")

    auth_payload = None
    try:
        reader = pdf_reader_factory(str(path))
        if extract_pdf_fallback_lines_from_pdf is None:
            fallback_candidates = shared_extract_pdf_fallback_line_candidates(reader)
        else:
            fallback_candidates = [extract_pdf_fallback_lines_from_pdf(reader)]
        if not fallback_candidates:
            raise ValueError("fallback sections were not found in the recovery document")

        last_error: Exception | None = None
        for fallback_lines in fallback_candidates:
            try:
                sections = split_fallback_sections(fallback_lines)
                validate_main(
                    section_lines=sections["main"],
                    expected_lines=expected_recovery_fallback_lines,
                )
                if not sections["auth"]:
                    raise ValueError(
                        "missing AUTH fallback section; include the AUTH section from recovery"
                    )
                auth_frame = build_auth_frame(sections["auth"], label="auth", quiet=quiet)
                auth_payload, _auth_status = resolve_auth(
                    [auth_frame],
                    doc_id=expected_doc_id,
                    doc_hash=expected_doc_hash,
                    allow_unsigned=False,
                    require_auth=True,
                    quiet=quiet,
                )
            except Exception as exc:
                last_error = exc
                continue
            break
        else:
            raise last_error or ValueError(
                "fallback sections were not found in the recovery document"
            )
    except ApiCommandError:
        raise
    except Exception as exc:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=f"rendered MAIN carrier {path.name} fallback is invalid: {exc}",
        ) from exc

    if auth_payload is not None and auth_payload.sign_pub != expected_sign_pub:
        raise ApiCommandError(
            code=EXTENSION_MAIN_CARRIER_INVALID,
            message=(
                f"rendered extension AUTH in {path.name} does not match the "
                "root-derived signing authority"
            ),
        )


def validate_pdf_fallback_main_section(
    *,
    section_lines: list[str],
    expected_lines: tuple[str, ...] | None,
) -> None:
    if not section_lines:
        raise ValueError("missing MAIN fallback section; include the MAIN section from recovery")
    actual_lines = filter_fallback_lines(section_lines)
    for actual in actual_lines:
        if normalize_pdf_fallback_payload_fragment(actual) is None:
            raise ValueError("fallback MAIN payload contains invalid z-base-32 content")
    if expected_lines is None:
        return

    if any(detect_fallback_section(line) for line in expected_lines):
        expected_main_lines = split_fallback_sections(expected_lines)["main"]
    else:
        expected_main_lines = list(expected_lines)
    normalized_expected = filter_fallback_lines(expected_main_lines)
    if normalized_fallback_payload_text(actual_lines) != normalized_fallback_payload_text(
        normalized_expected
    ):
        raise ValueError("fallback MAIN payload does not match the planned extension ciphertext")


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


def extract_pdf_fallback_lines_from_pdf_impl(reader: PdfReader) -> list[str]:
    candidates = extract_pdf_fallback_line_candidates_from_pdf_impl(reader)
    if not candidates:
        return []
    return candidates[0]


def extract_pdf_fallback_line_candidates_from_pdf_impl(reader: PdfReader) -> list[list[str]]:
    pieces: list[str] = []
    for page in reader.pages:
        page.extract_text(
            visitor_text=lambda text, _cm, _tm, _font_dict, _font_size: (
                pieces.append(text) if text.strip() else None
            )
        )

    lines: list[str] = []
    for page in reader.pages:
        extracted_text = page.extract_text() or ""
        lines.extend(extracted_text.splitlines())

    candidates: list[list[str]] = []
    errors: list[ValueError] = []
    seen: set[tuple[str, ...]] = set()
    for raw_lines in (pieces, lines):
        try:
            candidate = extract_pdf_fallback_lines(raw_lines)
        except ValueError as exc:
            errors.append(exc)
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


def normalize_pdf_fallback_payload_fragment(line: str) -> str:
    normalized = filter_fallback_lines([line])
    return normalized[0]


def normalized_fallback_payload_text(lines: list[str]) -> str:
    return "".join(ch.lower() for line in lines for ch in line if not ch.isspace() and ch != "-")


def fallback_extraction_score(lines: list[str]) -> tuple[int, int]:
    payload_lines = [line for line in lines if detect_fallback_section(line) is None]
    payload_chars = sum(len(normalized_fallback_payload_text([line])) for line in payload_lines)
    return payload_chars, len(lines)


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


def is_qr_absent_scan_error(exc: Exception) -> bool:
    return "no QR codes found in scan inputs" in str(exc)
