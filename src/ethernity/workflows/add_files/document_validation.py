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

"""Validate the rendered update's MAIN and recovery documents."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from ethernity.crypto.document_identity import doc_id_and_hash_from_ciphertext
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.frame_sets import (
    deduplicate_frame_slots,
    split_main_and_auth_frames,
)
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions.recovery import resolve_required_auth_payload
from ethernity.render.checks import (
    RenderValidationError,
    validate_fallback_summary,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
)
from ethernity.render.fallback_labels import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.render.types import FallbackSection, FallbackSummary
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.recovery.frame_inputs import recovery_frames_from_scan
from ethernity.workflows.shared import api_codes

from .models import (
    ExtensionPublication,
    ExtensionRenderResult,
)


def validate_staged_extension_documents(
    plan: ExtensionPublication,
    rendered: ExtensionRenderResult,
) -> None:
    expected_sign_pub = derive_public_key(plan.prepared.signing_seed)
    validate_main_document(
        path=plan.paths.qr_document_path,
        expected_doc_id=plan.encrypted.doc_id,
        expected_doc_hash=plan.encrypted.doc_hash,
        expected_sign_pub=expected_sign_pub,
        require_auth=True,
    )
    validate_recovery_document(
        path=plan.paths.recovery_document_path,
        frames=rendered.recovery_document_fallback_frames,
        fallback_summary=rendered.recovery_document_fallback_summary,
        expected_doc_id=plan.encrypted.doc_id,
        expected_doc_hash=plan.encrypted.doc_hash,
        expected_sign_pub=expected_sign_pub,
        require_auth=True,
    )


def validate_main_document(
    *,
    path: Path,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
    require_auth: bool,
) -> None:
    try:
        frames = list(recovery_frames_from_scan([str(path)]).frames)
        _validate_document_frames(
            path=path,
            frames=frames,
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=expected_sign_pub,
            require_auth=require_auth,
        )
    except AddFilesWorkflowError:
        raise
    except Exception as exc:
        raise AddFilesWorkflowError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=f"rendered MAIN document {path.name} is invalid: {exc}",
        ) from exc


def validate_recovery_document(
    *,
    path: Path,
    frames: tuple[Frame, ...],
    fallback_summary: FallbackSummary | None,
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
    require_auth: bool,
) -> None:
    try:
        reader = _validate_recovery_document_pdf(path)
        _validate_recovery_fallback_summary(path, frames, fallback_summary)
        validate_fallback_text_in_pdf(
            document_label=f"rendered recovery document {path.name}",
            reader=reader,
            fallback_sections=_recovery_fallback_sections(frames),
            fallback_summary=fallback_summary,
        )
        _validate_document_frames(
            path=path,
            frames=list(frames),
            expected_doc_id=expected_doc_id,
            expected_doc_hash=expected_doc_hash,
            expected_sign_pub=expected_sign_pub,
            require_auth=require_auth,
        )
    except AddFilesWorkflowError:
        raise
    except RenderValidationError as exc:
        raise _render_validation_error(exc) from exc
    except Exception as exc:
        raise AddFilesWorkflowError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=f"rendered recovery document {path.name} is invalid: {exc}",
        ) from exc


def _validate_recovery_document_pdf(path: Path) -> PdfReader:
    return validate_pdf_has_pages(
        path,
        document_label=f"rendered recovery document {path.name}",
    )


def _validate_recovery_fallback_summary(
    path: Path,
    frames: tuple[Frame, ...],
    fallback_summary: FallbackSummary | None,
) -> None:
    try:
        validate_fallback_summary(
            document_label=f"rendered recovery document {path.name}",
            frames=frames,
            fallback_summary=fallback_summary,
        )
    except RenderValidationError as exc:
        raise _render_validation_error(exc) from exc


def _recovery_fallback_sections(frames: tuple[Frame, ...]) -> tuple[FallbackSection, ...]:
    labels = {
        FrameType.AUTH: AUTH_FALLBACK_LABEL,
        FrameType.MAIN_DOCUMENT: MAIN_FALLBACK_LABEL,
    }
    try:
        sections = tuple(
            FallbackSection(label=labels[FrameType(frame.frame_type)], frame=frame)
            for frame in frames
        )
    except KeyError as exc:
        raise RenderValidationError("recovery fallback contains an unexpected frame role") from exc
    expected_roles = (FrameType.AUTH, FrameType.MAIN_DOCUMENT)
    if tuple(section.frame.frame_type for section in sections) != expected_roles:
        raise RenderValidationError(
            "recovery fallback must contain AUTH then MAIN sections",
            details={"frame_roles": tuple(int(section.frame.frame_type) for section in sections)},
        )
    return sections


def _render_validation_error(exc: RenderValidationError) -> AddFilesWorkflowError:
    return AddFilesWorkflowError(
        code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
        message=str(exc),
        details=exc.details,
    )


def _validate_document_frames(
    *,
    path: Path,
    frames: list[Frame],
    expected_doc_id: bytes,
    expected_doc_hash: bytes,
    expected_sign_pub: bytes,
    require_auth: bool,
) -> None:
    deduped = deduplicate_frame_slots(list(frames))
    main_frames, auth_frames = split_main_and_auth_frames(deduped)
    ciphertext = reassemble_payload(
        main_frames,
        expected_frame_type=FrameType.MAIN_DOCUMENT,
    )
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    if doc_id != expected_doc_id or doc_hash != expected_doc_hash:
        raise AddFilesWorkflowError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=(
                f"rendered MAIN document {path.name} does not match the "
                "planned extension ciphertext"
            ),
        )
    auth_payload = None
    if auth_frames or require_auth:
        auth_payload, _auth_status = resolve_required_auth_payload(
            auth_frames,
            doc_id=expected_doc_id,
            doc_hash=expected_doc_hash,
        )
    if auth_payload is not None and auth_payload.sign_pub != expected_sign_pub:
        raise AddFilesWorkflowError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=(f"rendered extension AUTH in {path.name} does not match the root signing key"),
        )
