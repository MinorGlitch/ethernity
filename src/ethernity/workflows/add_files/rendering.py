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

"""Extension document rendering steps."""

from __future__ import annotations

from collections.abc import Callable

from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES
from ethernity.encoding.framing import DOC_ID_LEN
from ethernity.render.service import RenderService
from ethernity.render.types import DocumentOrigin, RenderInputs, RenderResult
from ethernity.render.validation import validate_rendered_pdf_document
from ethernity.workflows.add_files.errors import AddFilesWorkflowError
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.events import report_render_page

from .main_document_rendering import build_main_qr_payloads
from .models import (
    ExtensionOutputSettings,
    ExtensionPublication,
    ExtensionRenderResult,
)
from .recovery_rendering import build_recovery_inputs


def render_extension_documents(
    plan: ExtensionPublication,
    *,
    output_settings: ExtensionOutputSettings,
    render_frames_to_pdf: Callable[[RenderInputs], RenderResult],
    layout_debug_json_path: Callable[[str | None, str], str | None],
) -> ExtensionRenderResult:
    if len(plan.encrypted.ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise AddFilesWorkflowError(
            code=issue_codes.EXTENSION_TOO_LARGE,
            message=(
                "extension ciphertext exceeds MAX_CIPHERTEXT_BYTES "
                f"({MAX_CIPHERTEXT_BYTES}): {len(plan.encrypted.ciphertext)} bytes"
            ),
        )

    render_service = RenderService(output_settings.config, on_page=report_render_page)
    origin = DocumentOrigin(
        kind="extension",
        extension_index=plan.prepared.next_index,
        update_mode=plan.encrypted.built.document.header.update_mode,
        root_doc_id=plan.prepared.root_doc_hash[:DOC_ID_LEN].hex(),
    )
    frames, auth_frame, qr_frames, qr_payloads = build_main_qr_payloads(
        plan,
        output_settings=output_settings,
        render_service=render_service,
    )
    qr_inputs = render_service.qr_inputs(
        qr_frames,
        plan.paths.qr_document_path,
        qr_payloads=qr_payloads,
        layout_debug_json_path=layout_debug_json_path(
            output_settings.layout_debug_dir, "qr_document"
        ),
        origin=origin,
    )
    recovery_inputs = build_recovery_inputs(
        plan,
        output_settings=output_settings,
        render_service=render_service,
        frames=frames,
        auth_frame=auth_frame,
        layout_debug_json_path=layout_debug_json_path,
        origin=origin,
    )

    qr_render_result = render_frames_to_pdf(qr_inputs)
    validate_rendered_pdf_document(
        inputs=qr_inputs,
        result=qr_render_result,
        document_label="rendered extension main document",
    )
    recovery_render_result = render_frames_to_pdf(recovery_inputs)
    validate_rendered_pdf_document(
        inputs=recovery_inputs,
        result=recovery_render_result,
        document_label="rendered extension recovery document",
    )

    return ExtensionRenderResult(
        recovery_document_fallback_frames=tuple(
            section.frame for section in recovery_inputs.fallback_sections or ()
        ),
        recovery_document_fallback_summary=recovery_render_result.fallback_summary,
    )
