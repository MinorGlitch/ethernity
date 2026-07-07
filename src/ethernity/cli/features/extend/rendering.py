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

"""Rendering orchestration for extend execution."""

from __future__ import annotations

from typing import Callable

from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.core.bounds import MAX_CIPHERTEXT_BYTES
from ethernity.render.service import RenderService
from ethernity.render.types import RenderInputs, RenderLineage, RenderResult

from .main_document_rendering import build_main_qr_payloads
from .models import (
    EXTENSION_TOO_LARGE,
    PreparedExtensionPublishPlan,
    RenderedExtensionArtifacts,
    ResolvedExtendRuntime,
)
from .recovery_rendering import build_recovery_inputs
from .shard_rendering import (
    SIGNING_KEY_SHARD_DOC_TYPE,
    build_kit_index_inputs,
    build_passphrase_shards,
    build_signing_key_shards,
    render_extension_shard,
)


def _update_kit_index_qr_page_count(
    kit_index_inputs: RenderInputs | None,
    render_result: RenderResult,
) -> None:
    if kit_index_inputs is None:
        return
    if render_result.artifact_proof is None:
        raise ApiCommandError(
            code="RUNTIME_ERROR",
            message="QR document render did not return an artifact proof",
        )
    if render_result.artifact_proof.page_count > 0:
        kit_index_inputs.context["kit_qr_page_count"] = render_result.artifact_proof.page_count


def render_extension_artifacts(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime: ResolvedExtendRuntime,
    render_frames_to_pdf: Callable[[RenderInputs], RenderResult],
    layout_debug_json_path: Callable[[str | None, str], str | None],
    build_kit_index_inventory_rows: Callable[..., list[dict[str, str]]],
) -> RenderedExtensionArtifacts:
    if len(plan.encrypted.ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise ApiCommandError(
            code=EXTENSION_TOO_LARGE,
            message=(
                "extension ciphertext exceeds MAX_CIPHERTEXT_BYTES "
                f"({MAX_CIPHERTEXT_BYTES}): {len(plan.encrypted.ciphertext)} bytes"
            ),
        )

    passphrase_shards = tuple(build_passphrase_shards(plan, runtime=runtime))
    signing_key_shards = tuple(build_signing_key_shards(plan, runtime=runtime))
    render_service = RenderService(runtime.config)
    lineage = RenderLineage(kind="extension", extension_index=plan.prepared.next_index)
    frames, auth_frame, qr_frames, qr_payloads = build_main_qr_payloads(
        plan,
        runtime=runtime,
        render_service=render_service,
    )
    qr_inputs = render_service.qr_inputs(
        qr_frames,
        plan.artifacts.qr_document_path,
        qr_payloads=qr_payloads,
        layout_debug_json_path=layout_debug_json_path(runtime.layout_debug_dir, "qr_document"),
        lineage=lineage,
    )
    kit_index_inputs = build_kit_index_inputs(
        plan,
        runtime=runtime,
        render_service=render_service,
        qr_frames=qr_frames,
        passphrase_shards=passphrase_shards,
        signing_key_shards=signing_key_shards,
        layout_debug_json_path=layout_debug_json_path,
        build_kit_index_inventory_rows=build_kit_index_inventory_rows,
        lineage=lineage,
    )
    recovery_inputs = build_recovery_inputs(
        plan,
        runtime=runtime,
        render_service=render_service,
        frames=frames,
        auth_frame=auth_frame,
        layout_debug_json_path=layout_debug_json_path,
        lineage=lineage,
    )

    qr_render_result = render_frames_to_pdf(qr_inputs)
    _update_kit_index_qr_page_count(kit_index_inputs, qr_render_result)
    recovery_render_result = render_frames_to_pdf(recovery_inputs)
    if kit_index_inputs is not None:
        render_frames_to_pdf(kit_index_inputs)

    for shard, output_path in zip(passphrase_shards, plan.artifacts.shard_paths, strict=True):
        render_extension_shard(
            shard,
            doc_id=plan.encrypted.doc_id,
            output_path=output_path,
            render_service=render_service,
            qr_payload_codec=runtime.qr_payload_codec,
            layout_debug_dir=runtime.layout_debug_dir,
            stem=f"shard-{shard.share_index:02d}-of-{shard.share_count:02d}",
            render_frames_to_pdf=render_frames_to_pdf,
            layout_debug_json_path=layout_debug_json_path,
            lineage=lineage,
        )
    for shard, output_path in zip(
        signing_key_shards,
        plan.artifacts.signing_key_shard_paths,
        strict=True,
    ):
        render_extension_shard(
            shard,
            doc_id=plan.encrypted.doc_id,
            output_path=output_path,
            render_service=render_service,
            qr_payload_codec=runtime.qr_payload_codec,
            doc_type=SIGNING_KEY_SHARD_DOC_TYPE,
            layout_debug_dir=runtime.layout_debug_dir,
            stem=f"signing-key-shard-{shard.share_index:02d}-of-{shard.share_count:02d}",
            render_frames_to_pdf=render_frames_to_pdf,
            layout_debug_json_path=layout_debug_json_path,
            lineage=lineage,
        )
    return RenderedExtensionArtifacts(
        passphrase_shards=passphrase_shards,
        signing_key_shards=signing_key_shards,
        recovery_document_fallback_frames=tuple(
            section.frame for section in recovery_inputs.fallback_sections or ()
        ),
        recovery_document_fallback_proof=recovery_render_result.fallback_proof,
    )
