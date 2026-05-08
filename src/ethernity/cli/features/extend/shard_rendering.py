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

"""Shard and recovery-kit rendering helpers for extend execution."""

from __future__ import annotations

from typing import Any, Callable

from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.crypto import sharding as sharding_module
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.render.doc_types import DOC_TYPE_KIT_INDEX, DOC_TYPE_SIGNING_KEY_SHARD
from ethernity.render.service import RenderService
from ethernity.render.types import RenderInputs, RenderLineage

from .models import (
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    PreparedExtensionPublishPlan,
    ResolvedExtendRuntime,
)


def build_passphrase_shards(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime: ResolvedExtendRuntime,
) -> list[sharding_module.ShardPayload]:
    if not isinstance(runtime.passphrase, ExtensionPassphraseShards):
        return []
    return sharding_module.split_passphrase(
        plan.prepared.encryption_passphrase,
        threshold=runtime.passphrase.threshold,
        shares=runtime.passphrase.share_count,
        doc_hash=plan.encrypted.doc_hash,
        sign_priv=plan.prepared.signing_seed,
        sign_pub=runtime.sign_pub,
    )


def build_signing_key_shards(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime: ResolvedExtendRuntime,
) -> list[sharding_module.ShardPayload]:
    if not isinstance(runtime.signing_key, ExtensionSigningKeyShards):
        return []
    return sharding_module.split_signing_seed(
        plan.prepared.signing_seed,
        threshold=runtime.signing_key.threshold,
        shares=runtime.signing_key.share_count,
        doc_hash=plan.encrypted.doc_hash,
        sign_priv=plan.prepared.signing_seed,
        sign_pub=runtime.sign_pub,
    )


def build_kit_index_inputs(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime: ResolvedExtendRuntime,
    render_service: RenderService,
    qr_frames: list[Frame],
    passphrase_shards: tuple[sharding_module.ShardPayload, ...],
    signing_key_shards: tuple[sharding_module.ShardPayload, ...],
    layout_debug_json_path: Callable[[str | None, str], str | None],
    build_kit_index_inventory_rows: Callable[..., list[dict[str, str]]],
    lineage: RenderLineage,
) -> RenderInputs | None:
    output_path = plan.artifacts.recovery_kit_index_path
    if output_path is None:
        return None
    template_path = runtime.kit_index_template_path
    if template_path is None:
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="recovery_kit_index output was planned without a compatible template",
        )
    inventory_rows = [
        {
            "component_id": f"Extension {plan.prepared.next_index:02d}",
            "detail": f"Document ID {plan.encrypted.doc_id.hex()}",
            "status": "Generated",
        },
        *build_kit_index_inventory_rows(
            shard_payloads=list(passphrase_shards),
            signing_key_shard_payloads=list(signing_key_shards),
        ),
    ]
    context = render_service.base_context({"inventory_rows": inventory_rows})
    return render_service.kit_inputs(
        qr_frames,
        output_path,
        qr_payloads=render_service.build_qr_payloads(qr_frames, codec=runtime.qr_payload_codec),
        context=context,
        template_path=template_path,
        doc_type=DOC_TYPE_KIT_INDEX,
        layout_debug_json_path=layout_debug_json_path(
            runtime.layout_debug_dir,
            "recovery_kit_index",
        ),
        lineage=lineage,
    )


def render_extension_shard(
    shard: sharding_module.ShardPayload,
    *,
    doc_id: bytes,
    output_path: Any,
    render_service: RenderService,
    template_path: Any,
    qr_payload_codec: Any,
    layout_debug_dir: str | None,
    stem: str,
    render_frames_to_pdf: Callable[[RenderInputs], None],
    layout_debug_json_path: Callable[[str | None, str], str | None],
    lineage: RenderLineage,
    doc_type: str | None = None,
) -> None:
    shard_frame = Frame(
        version=VERSION,
        frame_type=FrameType.KEY_DOCUMENT,
        doc_id=doc_id,
        index=0,
        total=1,
        data=sharding_module.encode_shard_payload(shard),
    )
    shard_inputs = render_service.shard_inputs(
        shard_frame,
        output_path,
        shard_index=shard.share_index,
        shard_total=shard.share_count,
        shard_threshold=shard.threshold,
        qr_payloads=render_service.build_qr_payloads([shard_frame], codec=qr_payload_codec),
        template_path=template_path,
        doc_type=doc_type,
        layout_debug_json_path=layout_debug_json_path(layout_debug_dir, stem),
        lineage=lineage,
    )
    render_frames_to_pdf(shard_inputs)


SIGNING_KEY_SHARD_DOC_TYPE = DOC_TYPE_SIGNING_KEY_SHARD
