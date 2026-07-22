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

"""Recovery-document helpers for extension rendering."""

from __future__ import annotations

from typing import Callable

from ethernity import render as render_module
from ethernity.encoding.framing import VERSION, Frame, FrameType
from ethernity.render.fallback_labels import AUTH_FALLBACK_LABEL, MAIN_FALLBACK_LABEL
from ethernity.render.recovery_lines import append_signing_key_lines
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.service import RenderService
from ethernity.render.types import RenderInputs, RenderLineage
from ethernity.workflows.extension.errors import ExtensionWorkflowError

from .models import (
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    PreparedExtensionPublishPlan,
    ResolvedExtendRuntime,
    ReuseRootPassphraseShards,
)


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
        passphrase=None,
        quorum_threshold=runtime.passphrase.threshold,
        quorum_shares=runtime.passphrase.share_count,
        signing_pub=runtime.sign_pub,
        quorum_label=_recovery_quorum_label(runtime.passphrase),
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


def _recovery_quorum_label(policy: object) -> str:
    if isinstance(policy, ReuseRootPassphraseShards):
        return "Root Shard Quorum"
    if isinstance(policy, ExtensionPassphraseShards):
        return "Extension Shard Quorum"
    return "Shard Quorum"


def build_recovery_key_lines(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime: ResolvedExtendRuntime,
) -> list[str]:
    if isinstance(runtime.passphrase, ReuseRootPassphraseShards):
        key_lines = [
            "Passphrase recovery depends on the root backup shard documents.",
            (
                "Recover with "
                f"{runtime.passphrase.threshold} of {runtime.passphrase.share_count} "
                "root shard documents."
            ),
        ]
    elif isinstance(runtime.passphrase, ExtensionPassphraseShards):
        key_lines = [
            "Passphrase is sharded.",
            (
                "Recover with "
                f"{runtime.passphrase.threshold} of {runtime.passphrase.share_count} "
                "shard documents."
            ),
        ]
    else:
        raise ExtensionWorkflowError(
            code="RUNTIME_ERROR",
            message="unknown extension passphrase storage policy",
        )
    append_signing_key_lines(
        key_lines,
        sign_pub=runtime.sign_pub,
        sealed=False,
        stored_in_main=False,
        stored_as_shards=isinstance(runtime.signing_key, ExtensionSigningKeyShards),
        not_stored_message="Signing private key not stored in this extension document.",
    )
    return key_lines
