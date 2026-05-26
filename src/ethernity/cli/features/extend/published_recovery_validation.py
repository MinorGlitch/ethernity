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

"""Published extension recovery-document validation."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from ethernity.cli.shared import api_codes
from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.cli.shared.io.fallback_parser import detect_fallback_section, filter_fallback_lines
from ethernity.cli.shared.io.frames import _frames_from_fallback_lines
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.encoding.framing import Frame
from ethernity.extensions.recovery import (
    imported_document_from_recovery_frames,
    resolve_required_auth_payload,
)
from ethernity.render.proofs import RenderProofError, validate_pdf_has_pages

_FALLBACK_LINE_NUMBER_RE = re.compile(r"^\s*(?P<counter>\d+)[.)]?\s+")


def validate_published_recovery_document_carrier(
    *,
    path: Path,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
    quiet: bool,
) -> None:
    try:
        reader = _validate_recovery_document_pdf(
            path,
            artifact_label=f"published recovery document {path.name}",
        )
        frames = _frames_from_fallback_lines(
            extract_published_recovery_document_fallback_lines(reader),
            allow_invalid_auth=False,
            quiet=quiet,
        )
        _validate_published_recovery_document_frames(
            path=path,
            frames=frames,
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=expected_sign_pub,
        )
    except ApiCommandError:
        raise
    except RenderProofError as exc:
        raise ApiCommandError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=str(exc),
            details=exc.details,
        ) from exc
    except Exception as exc:
        raise ApiCommandError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=f"published recovery document {path.name} is invalid: {exc}",
        ) from exc


def _validate_recovery_document_pdf(
    path: Path,
    *,
    artifact_label: str | None = None,
) -> PdfReader:
    return validate_pdf_has_pages(
        path,
        artifact_label=artifact_label or f"published recovery document {path.name}",
    )


def extract_published_recovery_document_fallback_lines(reader: PdfReader) -> list[str]:
    """Extract marked AUTH and MAIN fallback lines from a rendered recovery-document PDF."""

    lines: list[str] = []
    current_section: str | None = None
    accept_payload_continuation = False
    expected_row = 1

    for raw_line in _recovery_document_pdf_lines(reader):
        section = detect_fallback_section(raw_line)
        if section in {"auth", "main"}:
            current_section = section
            accept_payload_continuation = False
            expected_row = 1
            lines.append(AUTH_FALLBACK_LABEL if section == "auth" else MAIN_FALLBACK_LABEL)
            continue
        if section is not None:
            current_section = None
            continue
        if current_section not in {"auth", "main"}:
            continue

        payload_line = _extract_pdf_fallback_payload_line(
            raw_line,
            require_counter=True,
            expected_counter=expected_row,
        )
        if payload_line is None and accept_payload_continuation:
            payload_line = _extract_pdf_fallback_payload_line(
                raw_line,
                require_counter=False,
                expected_counter=None,
            )
        if payload_line is None:
            accept_payload_continuation = False
            continue
        lines.append(payload_line)
        if _FALLBACK_LINE_NUMBER_RE.match(raw_line) is not None:
            expected_row += 1
        accept_payload_continuation = True

    if AUTH_FALLBACK_LABEL not in lines:
        raise ValueError("published recovery document is missing AUTH fallback section")
    if MAIN_FALLBACK_LABEL not in lines:
        raise ValueError("published recovery document is missing MAIN fallback section")
    return lines


def _recovery_document_pdf_lines(reader: PdfReader) -> list[str]:
    return [line for page in reader.pages for line in (page.extract_text() or "").splitlines()]


def _extract_pdf_fallback_payload_line(
    line: str,
    *,
    require_counter: bool,
    expected_counter: int | None,
) -> str | None:
    counter_match = _FALLBACK_LINE_NUMBER_RE.match(line)
    has_counter = counter_match is not None
    if require_counter and counter_match is None:
        return None
    if (
        expected_counter is not None
        and counter_match is not None
        and int(counter_match.group("counter")) != expected_counter
    ):
        return None
    candidate = _FALLBACK_LINE_NUMBER_RE.sub("", line.strip()) if has_counter else line.strip()
    tokens: list[str] = []
    for token in candidate.split():
        if len(token) > 4:
            break
        try:
            filter_fallback_lines([token])
        except ValueError:
            break
        tokens.append(token)
    if not tokens:
        return None
    candidate = " ".join(tokens)
    try:
        filter_fallback_lines([candidate])
    except ValueError:
        return None
    return candidate


def _validate_published_recovery_document_frames(
    *,
    path: Path,
    frames: list[Frame],
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
) -> None:
    document = imported_document_from_recovery_frames(
        frames, source_label="published recovery document"
    )
    if document.doc_id != expected_doc_id or document.doc_hash != expected_doc_hash:
        raise ApiCommandError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=f"published recovery document {path.name} does not match extension ciphertext",
        )
    auth_payload, _auth_status = resolve_required_auth_payload(
        document.auth_frames,
        doc_id=expected_doc_id,
        doc_hash=expected_doc_hash,
    )
    if auth_payload.sign_pub != expected_sign_pub:
        raise ApiCommandError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=(
                f"published recovery document AUTH in {path.name} does not match the "
                "root-derived signing authority"
            ),
        )


__all__ = [
    "extract_published_recovery_document_fallback_lines",
    "validate_published_recovery_document_carrier",
]
