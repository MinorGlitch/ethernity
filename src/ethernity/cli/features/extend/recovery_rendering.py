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

"""Recovery-document helpers for extend rendering."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, cast

from fpdf import FPDF

from ethernity import render as render_module
from ethernity.cli.shared.constants import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.ui.debug import _append_signing_key_lines
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.layout import compute_layout
from ethernity.render.recovery_meta import build_recovery_meta, recovery_meta_lines_extra
from ethernity.render.service import RenderService
from ethernity.render.spec import document_spec
from ethernity.render.text import page_format
from ethernity.render.types import RenderInputs, RenderLineage

from .models import PreparedExtensionPublishPlan, ResolvedExtendRuntime


def expected_recovery_fallback_lines(inputs: RenderInputs) -> tuple[str, ...]:
    base_context = dict(inputs.context)
    paper_size = str(base_context.get("paper_size") or "A4")
    doc_id = base_context.get("doc_id")
    if not isinstance(doc_id, str):
        doc_id = inputs.frames[0].doc_id.hex()
    spec = document_spec(inputs.doc_type, paper_size, base_context)
    if inputs.doc_type.strip().lower() == DOC_TYPE_RECOVERY:
        if inputs.recovery_meta is None:
            raise ValueError("recovery metadata is required for recovery fallback validation")
        spec = replace(
            spec,
            header=replace(
                spec.header,
                meta_lines_extra=recovery_meta_lines_extra(inputs.recovery_meta),
            ),
        )
    layout_spec = spec.with_header(doc_id=doc_id, page_label="Page 1 / 1")
    pdf = FPDF(unit="mm", format=cast(Any, page_format(layout_spec.page)))
    pdf.set_auto_page_break(False)
    _layout, fallback_lines = compute_layout(
        inputs,
        layout_spec,
        pdf,
        list(inputs.key_lines or ()),
        include_keys=False,
        include_instructions=True,
    )
    return tuple(line for line in fallback_lines if line.strip())


def build_recovery_inputs(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime: ResolvedExtendRuntime,
    render_service: RenderService,
    frames: list[Frame],
    auth_frame: Frame,
    layout_debug_json_path: Callable[[str | None, str], str | None],
    lineage: RenderLineage,
) -> RenderInputs:
    key_lines = build_recovery_key_lines(plan, runtime=runtime)
    recovery_meta = build_recovery_meta(
        passphrase=(
            None
            if runtime.recovery_quorum_shares is not None
            else plan.prepared.encryption_passphrase
        ),
        quorum_threshold=runtime.recovery_quorum_threshold,
        quorum_shares=runtime.recovery_quorum_shares,
        signing_pub=runtime.sign_pub,
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
        plan.artifacts.recovery_document_path,
        key_lines=key_lines,
        recovery_meta=recovery_meta,
        fallback_sections=fallback_sections,
        layout_debug_json_path=layout_debug_json_path(
            runtime.layout_debug_dir,
            "recovery_document",
        ),
        lineage=lineage,
    )


def build_recovery_key_lines(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime: ResolvedExtendRuntime,
) -> list[str]:
    if runtime.reuse_root_unlock:
        threshold = runtime.recovery_quorum_threshold
        shares = runtime.recovery_quorum_shares
        if threshold is None or shares is None:
            raise ApiCommandError(
                code="RUNTIME_ERROR",
                message="root shard quorum was not resolved for unlock_policy=reuse-root",
            )
        key_lines = [
            "Passphrase is stored in the root backup shard documents.",
            f"Recover with {threshold} of {shares} root shard documents.",
        ]
    elif runtime.publish_policy.passphrase_shard_count > 0:
        threshold = runtime.passphrase_shard_threshold
        if threshold is None:
            raise ApiCommandError(
                code="RUNTIME_ERROR",
                message="passphrase shard threshold was not resolved",
            )
        key_lines = [
            "Passphrase is sharded.",
            (
                "Recover with "
                f"{threshold} of {runtime.publish_policy.passphrase_shard_count} shard documents."
            ),
        ]
    else:
        key_lines = ["Passphrase:", plan.prepared.encryption_passphrase]
    _append_signing_key_lines(
        key_lines,
        sign_pub=runtime.sign_pub,
        sealed=False,
        stored_in_main=False,
        stored_as_shards=runtime.publish_policy.signing_key_shard_count > 0,
        not_stored_message="Signing private key not stored in this extension document.",
    )
    return key_lines
