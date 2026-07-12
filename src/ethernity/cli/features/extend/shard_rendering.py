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
from ethernity.render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ethernity.render.proofs import (
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_render_layout_proof,
)
from ethernity.render.service import RenderService
from ethernity.render.types import RenderInputs, RenderLineage, RenderResult

from .models import (
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    PreparedExtensionPublishPlan,
    ResolvedExtendRuntime,
    ReuseRootPassphraseShards,
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
    kit_index_style = runtime.kit_index_style
    if kit_index_style is None:
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="recovery_kit_index output was planned without a compatible style",
        )
    inventory_rows = [
        {
            "component_id": f"Extension {plan.prepared.next_index:02d}",
            "detail": f"Document ID {plan.encrypted.doc_id.hex()}",
            "status": "Generated",
        },
        {
            "component_id": "ROOT-BACKUP",
            "detail": (
                "Requires matching root backup QR and recovery documents"
                f" for root document {plan.prepared.inspection.root_doc_id}"
            ),
            "status": "External",
        },
        *_root_shard_dependency_rows(runtime.passphrase),
        *build_kit_index_inventory_rows(
            shard_payloads=list(passphrase_shards),
            signing_key_shard_payloads=list(signing_key_shards),
            component_id_prefix=f"EXT-{plan.prepared.next_index:02d}-",
        ),
    ]
    context = render_service.base_context(
        {
            "doc_id": plan.encrypted.doc_id.hex(),
            "inventory_rows": inventory_rows,
        }
    )
    return render_service.kit_index_inputs(
        output_path,
        context=context,
        design_name=kit_index_style,
        qr_chunk_count=len(qr_frames),
        layout_debug_json_path=layout_debug_json_path(
            runtime.layout_debug_dir,
            "recovery_kit_index",
        ),
        lineage=lineage,
    )


def _root_shard_dependency_rows(policy: object) -> list[dict[str, str]]:
    if not isinstance(policy, ReuseRootPassphraseShards):
        return []
    return [
        {
            "component_id": "ROOT-SHARDS",
            "detail": (
                f"Requires root passphrase shard quorum {policy.threshold} of {policy.share_count}"
            ),
            "status": "External",
        }
    ]


def render_extension_shard(
    shard: sharding_module.ShardPayload,
    *,
    doc_id: bytes,
    output_path: Any,
    render_service: RenderService,
    qr_payload_codec: Any,
    layout_debug_dir: str | None,
    stem: str,
    render_frames_to_pdf: Callable[[RenderInputs], RenderResult],
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
        doc_type=doc_type,
        layout_debug_json_path=layout_debug_json_path(layout_debug_dir, stem),
        lineage=lineage,
    )
    render_result = render_frames_to_pdf(shard_inputs)
    _validate_rendered_extension_shard(
        inputs=shard_inputs,
        result=render_result,
        artifact_label=f"rendered extension {stem} artifact",
    )


def _validate_rendered_extension_shard(
    *,
    inputs: RenderInputs,
    result: RenderResult,
    artifact_label: str,
) -> None:
    fallback_sections = tuple(inputs.fallback_sections or ())
    validate_render_artifact_proof(
        artifact_label=artifact_label,
        inputs=inputs,
        artifact_proof=result.artifact_proof,
    )
    reader = validate_pdf_has_pages(inputs.output_path, artifact_label=artifact_label)
    validate_render_layout_proof(
        artifact_label=artifact_label,
        layout_proof=result.layout_proof,
        expected_page_count=len(reader.pages),
    )
    fallback_proof = (
        result.artifact_proof.fallback_proof if result.artifact_proof is not None else None
    ) or result.fallback_proof
    validate_fallback_render_proof(
        artifact_label=artifact_label,
        frames=tuple(section.frame for section in fallback_sections),
        fallback_proof=fallback_proof,
    )
    validate_fallback_text_in_pdf(
        artifact_label=artifact_label,
        reader=reader,
        fallback_sections=fallback_sections,
        fallback_proof=fallback_proof,
    )


SIGNING_KEY_SHARD_DOC_TYPE = DOC_TYPE_SIGNING_KEY_SHARD
