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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ethernity import render as render_module
from ethernity.crypto import sharding as sharding_module
from ethernity.crypto.sharding import ShardPayload
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.encoding.qr_payloads import QR_PAYLOAD_CODEC_RAW, QrPayloadCodec
from ethernity.render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ethernity.render.layout_debug import layout_debug_json_path as debug_output_path
from ethernity.render.service import RenderService
from ethernity.render.types import DocumentOrigin
from ethernity.render.validation import validate_rendered_pdf_document


def render_shard_document(
    shard: ShardPayload,
    *,
    doc_id: bytes,
    output_dir: str,
    render_service: RenderService,
    filename_prefix: str | None = None,
    doc_type: str | None = None,
    layout_debug_json_path: str | None = None,
    layout_debug_dir: str | None = None,
    qr_payload_codec: QrPayloadCodec = QR_PAYLOAD_CODEC_RAW,
    origin: DocumentOrigin,
) -> str:
    """Render one shard document to PDF and return its output path."""

    signing_key = shard.key_type == sharding_module.KEY_TYPE_SIGNING_SEED
    if filename_prefix is None:
        filename_prefix = "signing-key-shard" if signing_key else "shard"
    if doc_type is None and signing_key:
        doc_type = DOC_TYPE_SIGNING_KEY_SHARD
    if layout_debug_json_path is None:
        layout_debug_json_path = debug_output_path(
            layout_debug_dir,
            f"{filename_prefix}-{shard.share_index:02d}-of-{shard.share_count:02d}",
        )

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
        origin=origin,
    )
    render_result = render_module.render_frames_to_pdf(shard_inputs)
    validate_rendered_pdf_document(
        inputs=shard_inputs,
        result=render_result,
        document_label=f"rendered {filename_prefix} document",
    )
    return shard_path


@dataclass(frozen=True)
class ShardRenderContext:
    """Identity, destination, and rendering options shared by a batch of shards."""

    doc_id: bytes
    output_dir: str
    render_service: RenderService
    layout_debug_dir: str | None
    qr_payload_codec: QrPayloadCodec
    origin: DocumentOrigin


def render_shard_documents(
    passphrase_shards: Sequence[ShardPayload],
    signing_key_shards: Sequence[ShardPayload],
    *,
    context: ShardRenderContext,
    on_document: Callable[[ShardPayload, str], None],
) -> tuple[list[str], list[str]]:
    """Render both shard groups in share order, reporting only validated documents."""

    passphrase_paths: list[str] = []
    signing_key_paths: list[str] = []
    for payloads, paths in (
        (passphrase_shards, passphrase_paths),
        (signing_key_shards, signing_key_paths),
    ):
        for shard in sorted(payloads, key=lambda item: item.share_index):
            path = render_shard_document(
                shard,
                doc_id=context.doc_id,
                output_dir=context.output_dir,
                render_service=context.render_service,
                layout_debug_dir=context.layout_debug_dir,
                qr_payload_codec=context.qr_payload_codec,
                origin=context.origin,
            )
            paths.append(path)
            on_document(shard, path)
    return passphrase_paths, signing_key_paths


__all__ = ["ShardRenderContext", "render_shard_document", "render_shard_documents"]
