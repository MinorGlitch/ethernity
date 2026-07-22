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

from collections.abc import Sequence
from pathlib import Path

from ethernity.encoding.framing import VERSION, Frame, FrameType, encode_frame
from ethernity.extensions.recovery import ImportedRecoveryDocument
from ethernity.render.fallback_labels import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.render.proofs import (
    RenderProofError,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
)
from ethernity.render.types import FallbackSection
from ethernity.workflows.extension.errors import ExtensionWorkflowError
from ethernity.workflows.shared import api_codes


def validate_published_recovery_document_carrier(
    *,
    path: Path,
    document: ImportedRecoveryDocument,
) -> None:
    try:
        reader = validate_pdf_has_pages(
            path,
            artifact_label=f"published recovery document {path.name}",
        )
        validate_fallback_text_in_pdf(
            artifact_label=f"published recovery document {path.name}",
            reader=reader,
            fallback_sections=_published_recovery_sections(document),
        )
    except ExtensionWorkflowError:
        raise
    except RenderProofError as exc:
        raise ExtensionWorkflowError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=str(exc),
            details=exc.details,
        ) from exc
    except Exception as exc:
        raise ExtensionWorkflowError(
            code=api_codes.EXTENSION_MAIN_CARRIER_INVALID,
            message=f"published recovery document {path.name} is invalid: {exc}",
        ) from exc


def validate_published_shard_fallback_carrier(
    *,
    path: Path,
    frames: Sequence[Frame],
) -> None:
    """Audit one published shard PDF's text against its machine-readable KEY frame."""

    try:
        distinct_frames = {encode_frame(frame): frame for frame in frames}
        if len(distinct_frames) != 1:
            raise RenderProofError("published shard must contain exactly one distinct QR frame")
        frame = next(iter(distinct_frames.values()))
        if frame.frame_type != FrameType.KEY_DOCUMENT:
            raise RenderProofError("published shard QR must contain a KEY_DOCUMENT frame")
        reader = validate_pdf_has_pages(path, artifact_label=f"published shard {path.name}")
        validate_fallback_text_in_pdf(
            artifact_label=f"published shard {path.name}",
            reader=reader,
            fallback_sections=(FallbackSection(label=None, frame=frame),),
        )
    except ExtensionWorkflowError:
        raise
    except RenderProofError as exc:
        raise ExtensionWorkflowError(
            code=api_codes.EXTENSION_SHARD_CARRIER_INVALID,
            message=str(exc),
            details=exc.details,
        ) from exc
    except Exception as exc:
        raise ExtensionWorkflowError(
            code=api_codes.EXTENSION_SHARD_CARRIER_INVALID,
            message=f"published shard {path.name} is invalid: {exc}",
        ) from exc


def _published_recovery_sections(
    document: ImportedRecoveryDocument,
) -> tuple[FallbackSection, ...]:
    distinct_auth_frames = {encode_frame(frame): frame for frame in document.auth_frames}
    if len(distinct_auth_frames) != 1:
        raise RenderProofError("published recovery document requires exactly one AUTH frame")
    auth_frame = next(iter(distinct_auth_frames.values()))
    if auth_frame.frame_type != FrameType.AUTH:
        raise RenderProofError("published recovery document authority frame has the wrong role")
    main_frame = Frame(
        version=VERSION,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=document.doc_id,
        index=0,
        total=1,
        data=document.ciphertext,
    )
    return (
        FallbackSection(label=AUTH_FALLBACK_LABEL, frame=auth_frame),
        FallbackSection(label=MAIN_FALLBACK_LABEL, frame=main_frame),
    )


__all__ = [
    "validate_published_recovery_document_carrier",
    "validate_published_shard_fallback_carrier",
]
