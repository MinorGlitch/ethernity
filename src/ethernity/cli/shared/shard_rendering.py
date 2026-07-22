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

"""Shared rendering for passphrase and signing-key shard documents."""

from __future__ import annotations

from pathlib import Path

from ethernity import render as render_module
from ethernity.cli.shared.render_validation import validate_rendered_pdf_artifact
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.sharding import ShardPayload
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.encoding.qr_payloads import QR_PAYLOAD_CODEC_RAW, QrPayloadCodec
from ethernity.render.service import RenderService
from ethernity.render.types import RenderLineage


def render_shard_document(
    shard: ShardPayload,
    *,
    doc_id: bytes,
    output_dir: str,
    render_service: RenderService,
    filename_prefix: str,
    doc_type: str | None = None,
    layout_debug_json_path: str | None = None,
    qr_payload_codec: QrPayloadCodec = QR_PAYLOAD_CODEC_RAW,
    lineage: RenderLineage,
) -> str:
    """Render one shard document to PDF and return its output path."""

    shard_frame = Frame(
        version=VERSION,
        frame_type=FrameType.KEY_DOCUMENT,
        doc_id=doc_id,
        index=0,
        total=1,
        data=sharding_module.encode_shard_payload(shard),
    )
    shard_path = str(
        Path(output_dir)
        / f"{filename_prefix}-{doc_id.hex()}-{shard.share_index}-of-{shard.share_count}.pdf"
    )
    shard_inputs = render_service.shard_inputs(
        shard_frame,
        shard_path,
        shard_index=shard.share_index,
        shard_total=shard.share_count,
        shard_threshold=shard.threshold,
        qr_payloads=render_service.build_qr_payloads([shard_frame], codec=qr_payload_codec),
        doc_type=doc_type,
        layout_debug_json_path=layout_debug_json_path,
        lineage=lineage,
    )
    render_result = render_module.render_frames_to_pdf(shard_inputs)
    validate_rendered_pdf_artifact(
        inputs=shard_inputs,
        result=render_result,
        artifact_label=f"rendered {filename_prefix} artifact",
    )
    return shard_path


__all__ = ["render_shard_document"]
