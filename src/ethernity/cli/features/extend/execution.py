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

"""Execution helpers for extend orchestration."""

from __future__ import annotations

import secrets

from ethernity import render as render_module
from ethernity.artifacts.publish import publish_staged_artifacts
from ethernity.cli.features.backup import execution as backup_execution
from ethernity.cli.features.extend import rendering as _rendering_impl, runtime as _runtime_impl
from ethernity.cli.features.extend.main_carrier_validation import (
    validate_staged_main_carrier,
    validate_staged_recovery_kit_index_document,
)
from ethernity.cli.features.extend.models import (
    ExecutedExtendRun,
    ExtensionArtifactPostValidator,
    ExtensionArtifactRenderer,
    PreparedExtendRun,
    PreparedExtensionPublishPlan,
    PublishedExtensionResult,
    RenderedExtensionArtifacts,
)
from ethernity.cli.features.extend.prepare import (
    prepare_extend_run,
    prepare_staged_extension_publish,
)
from ethernity.cli.features.extend.shard_validation import validate_staged_shard_carriers
from ethernity.cli.shared.types import ExtendArgs
from ethernity.extensions.build import Chunker, default_extension_chunker
from ethernity.extensions.staging import validate_staged_extension_dir


def execute_staged_extension_publish(
    plan: PreparedExtensionPublishPlan,
    *,
    renderer: ExtensionArtifactRenderer,
    post_validate: ExtensionArtifactPostValidator,
) -> PublishedExtensionResult:
    """Render into a staged extension directory, validate, and promote atomically."""

    staging_dir = plan.artifacts.staging_dir

    def _validate_staging(path) -> None:
        validate_staged_extension_dir(
            path,
            expected_index=plan.prepared.next_index,
            publish_policy=plan.publish_policy,
        )

    publish_result = publish_staged_artifacts(
        staging_dir=staging_dir,
        final_dir=plan.artifacts.final_dir,
        populate=lambda: renderer(plan),
        validate_staging=_validate_staging,
        validate_artifacts=lambda rendered: post_validate(plan, rendered),
    )
    final_dir = publish_result.final_dir

    return PublishedExtensionResult(
        index=plan.prepared.next_index,
        doc_id=plan.encrypted.doc_id,
        doc_hash=plan.encrypted.doc_hash,
        final_dir=final_dir,
        qr_document_path=final_dir / plan.artifacts.qr_document_path.name,
        recovery_document_path=final_dir / plan.artifacts.recovery_document_path.name,
        recovery_kit_index_path=(
            None
            if plan.artifacts.recovery_kit_index_path is None
            else final_dir / plan.artifacts.recovery_kit_index_path.name
        ),
        shard_paths=tuple(final_dir / path.name for path in plan.artifacts.shard_paths),
        signing_key_shard_paths=tuple(
            final_dir / path.name for path in plan.artifacts.signing_key_shard_paths
        ),
        root_passphrase_shard_threshold=(
            plan.prepared.root_passphrase_shard_threshold
            if plan.prepared.args.unlock_policy == "reuse-root"
            else None
        ),
        root_passphrase_shard_count=(
            plan.prepared.root_passphrase_shard_count
            if plan.prepared.args.unlock_policy == "reuse-root"
            else 0
        ),
    )


def run_extend(
    args: ExtendArgs,
    *,
    chunker: Chunker | None = None,
    nonce: str | None = None,
) -> PublishedExtensionResult:
    """Build, render, validate, and publish one extension entry."""

    return execute_prepared_extend(
        prepare_extend_run(args),
        chunker=chunker,
        nonce=nonce,
    ).result


def execute_prepared_extend(
    prepared: PreparedExtendRun,
    *,
    chunker: Chunker | None = None,
    nonce: str | None = None,
) -> ExecutedExtendRun:
    """Build, render, validate, and publish one extension entry."""

    runtime = _runtime_impl.resolve_extend_runtime(prepared)
    publish = prepare_staged_extension_publish(
        prepared,
        chunker=default_extension_chunker if chunker is None else chunker,
        nonce=nonce or secrets.token_hex(4),
        publish_policy=runtime.to_publish_policy(),
    )

    def _renderer(plan: PreparedExtensionPublishPlan) -> RenderedExtensionArtifacts:
        return _render_extension_artifacts(plan, runtime=runtime)

    def _post_validate(
        plan: PreparedExtensionPublishPlan,
        rendered: RenderedExtensionArtifacts,
    ) -> None:
        validate_staged_main_carrier(plan, rendered)
        validate_staged_shard_carriers(plan, rendered)
        validate_staged_recovery_kit_index_document(plan)

    result = execute_staged_extension_publish(
        publish,
        renderer=_renderer,
        post_validate=_post_validate,
    )
    return ExecutedExtendRun(
        prepared=prepared,
        runtime=runtime,
        publish=publish,
        result=result,
    )


def _render_extension_artifacts(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime,
) -> RenderedExtensionArtifacts:
    return _rendering_impl.render_extension_artifacts(
        plan,
        runtime=runtime,
        render_frames_to_pdf=render_module.render_frames_to_pdf,
        layout_debug_json_path=backup_execution._layout_debug_json_path,
        build_kit_index_inventory_rows=backup_execution._build_kit_index_inventory_rows,
    )


__all__ = [
    "execute_prepared_extend",
    "execute_staged_extension_publish",
    "run_extend",
]
