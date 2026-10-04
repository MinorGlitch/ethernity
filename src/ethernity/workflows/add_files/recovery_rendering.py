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

"""Build extension recovery-document render inputs."""

from __future__ import annotations

from typing import Callable

from ethernity import render as render_module
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.render.fallback_labels import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.render.recovery_lines import append_signing_key_lines
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.service import RenderService
from ethernity.render.types import DocumentOrigin, RenderInputs

from .models import (
    ExtensionOutputSettings,
    ExtensionPublication,
)


def build_recovery_inputs(
    plan: ExtensionPublication,
    *,
    output_settings: ExtensionOutputSettings,
    render_service: RenderService,
    frames: list[Frame],
    auth_frame: Frame,
    layout_debug_json_path: Callable[[str | None, str], str | None],
    origin: DocumentOrigin,
) -> RenderInputs:
    key_lines = build_recovery_key_lines(output_settings=output_settings)
    recovery_meta = build_recovery_meta(
        passphrase=None,
        quorum_threshold=None,
        quorum_shares=None,
        signing_pub=output_settings.sign_pub,
        quorum_label="Root Backup Recovery",
    )
    fallback_sections = [
        render_module.FallbackSection(label=AUTH_FALLBACK_LABEL, frame=auth_frame),
        render_module.FallbackSection(
            label=MAIN_FALLBACK_LABEL,
            frame=Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=plan.encrypted.doc_id,
                index=0,
                total=1,
                data=plan.encrypted.ciphertext,
            ),
        ),
    ]
    return render_service.recovery_inputs(
        frames,
        plan.paths.recovery_document_path,
        key_lines=key_lines,
        recovery_meta=recovery_meta,
        fallback_sections=fallback_sections,
        layout_debug_json_path=layout_debug_json_path(
            output_settings.layout_debug_dir,
            "recovery_document",
        ),
        origin=origin,
    )


def build_recovery_key_lines(
    *,
    output_settings: ExtensionOutputSettings,
) -> list[str]:
    key_lines = [
        "Passphrase recovery depends on the root backup recovery sheets.",
        "This update does not create or replace passphrase recovery sheets.",
    ]
    append_signing_key_lines(
        key_lines,
        sign_pub=output_settings.sign_pub,
        sealed=False,
        stored_in_main=False,
        stored_as_shards=False,
        not_stored_message=(
            "Signing private key is inherited from the root backup and is not stored here."
        ),
    )
    return key_lines
