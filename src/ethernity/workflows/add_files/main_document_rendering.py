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

"""Build QR and AUTH frames for extension documents."""

from __future__ import annotations

from ethernity.crypto.signing import encode_auth_payload, sign_auth
from ethernity.encoding.chunking import chunk_payload
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.qr.capacity import choose_frame_chunk_size
from ethernity.render.service import RenderService

from .models import ExtensionOutputSettings, ExtensionPublication


def build_main_qr_payloads(
    plan: ExtensionPublication,
    *,
    output_settings: ExtensionOutputSettings,
    render_service: RenderService,
) -> tuple[list[Frame], Frame, list[Frame], list[bytes | str]]:
    auth_frame = build_extension_auth_frame(plan, output_settings=output_settings)
    main_chunk_size = choose_frame_chunk_size(
        len(plan.encrypted.ciphertext),
        preferred_chunk_size=output_settings.qr_chunk_size,
        doc_id=plan.encrypted.doc_id,
        frame_type=FrameType.MAIN_DOCUMENT,
        qr_config=output_settings.config.qr_config,
        payload_codec=output_settings.qr_payload_codec,
    )
    frames = list(
        chunk_payload(
            plan.encrypted.ciphertext,
            doc_id=plan.encrypted.doc_id,
            frame_type=FrameType.MAIN_DOCUMENT,
            chunk_size=main_chunk_size,
        )
    )
    qr_frames = [*frames, auth_frame]
    return (
        frames,
        auth_frame,
        qr_frames,
        render_service.build_qr_payloads(qr_frames, codec=output_settings.qr_payload_codec),
    )


def build_extension_auth_frame(
    plan: ExtensionPublication,
    *,
    output_settings: ExtensionOutputSettings,
) -> Frame:
    auth_signature = sign_auth(
        plan.encrypted.doc_hash,
        sign_pub=output_settings.sign_pub,
        sign_priv=plan.prepared.signing_seed,
    )
    auth_payload = encode_auth_payload(
        plan.encrypted.doc_hash,
        sign_pub=output_settings.sign_pub,
        signature=auth_signature,
    )
    return Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=plan.encrypted.doc_id,
        index=0,
        total=1,
        data=auth_payload,
    )
