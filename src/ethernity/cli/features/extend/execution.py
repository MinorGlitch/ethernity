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

import os
import secrets
import shutil
import stat
import tempfile
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from ethernity import render as render_module
from ethernity.artifacts.publish import discard_staged_artifact_dir, publish_staged_artifacts
from ethernity.cli.features.extend import rendering as _rendering_impl, runtime as _runtime_impl
from ethernity.cli.features.extend.main_carrier_validation import (
    validate_staged_main_carrier,
    validate_staged_recovery_kit_index_document,
)
from ethernity.cli.features.extend.models import (
    EncryptedPreparedExtension,
    ExecutedExtendRun,
    ExtensionArtifactPostValidator,
    ExtensionArtifactRenderer,
    PreparedExtendRun,
    PreparedExtensionPublishPlan,
    PublishedExtensionResult,
    RenderedExtensionArtifacts,
    ReuseRootPassphraseShards,
)
from ethernity.cli.features.extend.planning import resolve_extend_state
from ethernity.cli.features.extend.prepare import (
    prepare_extend_run,
    prepare_staged_extension_publish,
)
from ethernity.cli.features.extend.shard_validation import validate_staged_shard_carriers
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.events import emit_phase, emit_progress
from ethernity.cli.shared.log import _warn
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.recovery_kit_index import build_recovery_kit_index_inventory_rows
from ethernity.cli.shared.types import ExtendArgs
from ethernity.extensions.build import Chunker, default_extension_chunker
from ethernity.extensions.staging import (
    EXTENSION_CHAIN_LOCK_DIR_NAME,
    create_staged_extension_artifact_plan,
    preflight_extension_publish_target,
    validate_staged_extension_dir,
)
from ethernity.render.layout_debug import layout_debug_json_path

DirectoryIdentity = tuple[int, int]


def execute_staged_extension_publish(
    plan: PreparedExtensionPublishPlan,
    *,
    renderer: ExtensionArtifactRenderer,
    post_validate: ExtensionArtifactPostValidator,
    root_passphrase_shard_threshold: int | None = None,
    root_passphrase_shard_count: int | None = None,
) -> PublishedExtensionResult:
    """Render into a staged extension directory, validate, and promote atomically."""

    staging_dir = plan.artifacts.staging_dir
    validate_phase_emitted = False

    def _validate_staging(path) -> None:
        nonlocal validate_phase_emitted
        if not validate_phase_emitted:
            emit_phase(phase="validate", label="Validating staged extension artifacts")
            validate_phase_emitted = True
        validate_staged_extension_dir(
            path,
            expected_index=plan.prepared.next_index,
            publish_policy=plan.publish_policy,
            expected_root_dir_identity=plan.artifacts.root_dir_identity,
            expected_extensions_dir_identity=plan.artifacts.extensions_dir_identity,
        )

    def _populate() -> RenderedExtensionArtifacts:
        emit_phase(phase="render", label="Rendering extension artifacts")
        rendered = renderer(plan)
        emit_progress(
            phase="render",
            current=1,
            total=1,
            unit="step",
            details={"staging_dir": staging_dir},
        )
        return rendered

    def _validate_artifacts(rendered: RenderedExtensionArtifacts) -> None:
        post_validate(plan, rendered)
        emit_progress(
            phase="validate",
            current=1,
            total=1,
            unit="step",
            details={"staging_dir": staging_dir},
        )
        emit_phase(phase="publish", label="Publishing extension artifacts")

    publish_result = publish_staged_artifacts(
        staging_dir=staging_dir,
        final_dir=plan.artifacts.final_dir,
        populate=_populate,
        validate_staging=_validate_staging,
        validate_artifacts=_validate_artifacts,
        validate_promotion=lambda: _validate_published_chain_head_for_promotion(plan),
        lock_dir=staging_dir.parent / EXTENSION_CHAIN_LOCK_DIR_NAME,
    )
    final_dir = publish_result.final_dir
    emit_progress(
        phase="publish",
        current=1,
        total=1,
        unit="step",
        details={"extension_dir": final_dir},
    )

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
            _result_root_passphrase_shard_threshold(
                plan,
                root_passphrase_shard_threshold=root_passphrase_shard_threshold,
                root_passphrase_shard_count=root_passphrase_shard_count,
            )
            if plan.prepared.args.unlock_policy == "reuse-root"
            else None
        ),
        root_passphrase_shard_count=(
            _result_root_passphrase_shard_count(
                plan,
                root_passphrase_shard_count=root_passphrase_shard_count,
            )
            if plan.prepared.args.unlock_policy == "reuse-root"
            else 0
        ),
        parent_head_index=plan.prepared.inspection.validated_head_index,
        parent_head_doc_hash=plan.prepared.inspection.validated_head_doc_hash,
        expected_head_doc_hash=plan.prepared.args.expected_head_doc_hash,
    )


def _validate_published_chain_head_for_promotion(plan: PreparedExtensionPublishPlan) -> None:
    """Verify the published chain still matches the lineage used to build the extension."""

    try:
        current = resolve_extend_state(
            replace(
                plan.prepared.args,
                input=None,
                input_dir=None,
                base_dir=None,
            )
        )
    except ApiCommandError as exc:
        raise ApiCommandError(
            code=api_codes.CHAIN_INVALID,
            message=f"published extension chain could not be revalidated: {exc.message}",
            details={
                "stage": "publish_head",
                "cause_code": exc.code,
                "cause_details": exc.details,
            },
        ) from exc

    if current.inspection.blocking_issues:
        first_issue = current.inspection.blocking_issues[0]
        raise ApiCommandError(
            code=api_codes.CHAIN_INVALID,
            message=(
                "published extension chain is no longer valid before promotion: "
                f"{first_issue.get('message')}"
            ),
            details={
                "stage": "publish_head",
                "issue": dict(first_issue),
            },
        )

    mismatches: dict[str, object] = {}
    if current.root_doc_hash != plan.prepared.root_doc_hash:
        mismatches["root_doc_hash"] = {
            "expected": plan.prepared.root_doc_hash.hex(),
            "actual": _hex_or_none(current.root_doc_hash),
        }
    if current.parent_doc_hash != plan.prepared.parent_doc_hash:
        mismatches["parent_doc_hash"] = {
            "expected": plan.prepared.parent_doc_hash.hex(),
            "actual": _hex_or_none(current.parent_doc_hash),
        }
    if current.next_index != plan.prepared.next_index:
        mismatches["next_index"] = {
            "expected": plan.prepared.next_index,
            "actual": current.next_index,
        }
    if mismatches:
        raise ApiCommandError(
            code=api_codes.CHAIN_INVALID,
            message="published extension chain head changed before promotion",
            details={"stage": "publish_head", "mismatches": mismatches},
        )


def _hex_or_none(value: bytes | None) -> str | None:
    return None if value is None else value.hex()


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
    _preflight_prepared_extension_publish_target(prepared)
    nonce_value = nonce or secrets.token_hex(4)
    publish = prepare_staged_extension_publish(
        prepared,
        chunker=default_extension_chunker if chunker is None else chunker,
        nonce=nonce_value,
        publish_policy=runtime.to_publish_policy(),
    )
    try:
        (
            render_runtime,
            layout_debug_staging_dir,
            layout_debug_dir_identity,
        ) = _runtime_with_staged_layout_debug(
            runtime,
            nonce=nonce_value,
        )
    except BaseException:
        discard_staged_artifact_dir(publish.artifacts.staging_dir)
        raise

    def _renderer(plan: PreparedExtensionPublishPlan) -> RenderedExtensionArtifacts:
        return _render_extension_artifacts(plan, runtime=render_runtime)

    def _post_validate(
        plan: PreparedExtensionPublishPlan,
        rendered: RenderedExtensionArtifacts,
    ) -> None:
        validate_staged_main_carrier(plan, rendered)
        validate_staged_shard_carriers(plan, rendered)
        validate_staged_recovery_kit_index_document(plan)

    try:
        result = execute_staged_extension_publish(
            publish,
            renderer=_renderer,
            post_validate=_post_validate,
            root_passphrase_shard_threshold=(
                runtime.passphrase.threshold
                if isinstance(runtime.passphrase, ReuseRootPassphraseShards)
                else None
            ),
            root_passphrase_shard_count=(
                runtime.passphrase.share_count
                if isinstance(runtime.passphrase, ReuseRootPassphraseShards)
                else 0
            ),
        )
    except BaseException:
        _discard_staged_layout_debug(layout_debug_staging_dir)
        raise
    _publish_staged_layout_debug(
        layout_debug_staging_dir,
        runtime.layout_debug_dir,
        expected_final_dir_identity=layout_debug_dir_identity,
        quiet=prepared.args.quiet,
    )
    return ExecutedExtendRun(
        prepared=prepared,
        runtime=runtime,
        publish=publish,
        result=result,
    )


def validate_prepared_extend_render(
    prepared: PreparedExtendRun,
    *,
    runtime,
    encrypted: EncryptedPreparedExtension,
    nonce: str | None = None,
) -> RenderedExtensionArtifacts:
    """Render and validate extension artifacts in a temporary no-publish workspace."""

    preview_root = Path(tempfile.mkdtemp(prefix=".extension-render-preview-"))
    try:
        publish_policy = runtime.to_publish_policy()
        artifacts = create_staged_extension_artifact_plan(
            preview_root,
            index=prepared.next_index,
            doc_id_hex=encrypted.doc_id.hex(),
            nonce=nonce or secrets.token_hex(4),
            publish_policy=publish_policy,
        )
        render_runtime = runtime
        if runtime.layout_debug_dir is not None:
            layout_debug_dir = preview_root / "layout-debug"
            layout_debug_dir.mkdir(mode=0o700)
            render_runtime = replace(runtime, layout_debug_dir=str(layout_debug_dir))
        plan = PreparedExtensionPublishPlan(
            prepared=prepared,
            encrypted=encrypted,
            publish_policy=publish_policy,
            artifacts=artifacts,
        )
        rendered = _render_extension_artifacts(plan, runtime=render_runtime)
        validate_staged_extension_dir(
            artifacts.staging_dir,
            expected_index=prepared.next_index,
            publish_policy=publish_policy,
            expected_root_dir_identity=artifacts.root_dir_identity,
            expected_extensions_dir_identity=artifacts.extensions_dir_identity,
        )
        validate_staged_main_carrier(plan, rendered)
        validate_staged_shard_carriers(plan, rendered)
        validate_staged_recovery_kit_index_document(plan)
        return rendered
    finally:
        discard_staged_artifact_dir(preview_root)


def _preflight_prepared_extension_publish_target(prepared: PreparedExtendRun) -> None:
    try:
        preflight_extension_publish_target(
            prepared.args.root_dir or prepared.inspection.root_dir,
            index=prepared.next_index,
            allow_missing_root=bool(prepared.args.scan),
            require_empty_extensions=bool(prepared.args.scan),
        )
    except ValueError as exc:
        raise ApiCommandError(
            code=api_codes.EXTENSION_PUBLISH_TARGET_INVALID,
            message=str(exc),
            details={"stage": "publish_target"},
        ) from exc


def _runtime_with_staged_layout_debug(
    runtime,
    *,
    nonce: str,
):
    if runtime.layout_debug_dir is None:
        return runtime, None, None
    layout_debug_dir = Path(runtime.layout_debug_dir)
    layout_debug_dir_identity = _layout_debug_dir_identity(layout_debug_dir)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".extension-layout-{nonce}-",
            dir=str(layout_debug_dir),
        )
    )
    return (
        replace(runtime, layout_debug_dir=str(staging_dir)),
        staging_dir,
        layout_debug_dir_identity,
    )


def _publish_staged_layout_debug(
    staging_dir: Path | None,
    final_dir: str | None,
    *,
    expected_final_dir_identity: DirectoryIdentity | None,
    quiet: bool,
) -> None:
    if staging_dir is None or final_dir is None:
        return
    final_path = Path(final_dir)
    try:
        try:
            _replace_layout_debug_sidecars(
                staging_dir,
                final_path,
                expected_final_dir_identity=expected_final_dir_identity,
            )
        except (OSError, ValueError) as exc:
            _warn(
                "Extension published, but layout debug sidecar promotion failed.",
                quiet=quiet,
                details={
                    "layout_debug_dir": str(final_path),
                    "layout_debug_staging_dir": str(staging_dir),
                    "error": str(exc),
                },
            )
    finally:
        _discard_staged_layout_debug(staging_dir)


def _discard_staged_layout_debug(staging_dir: Path | None) -> None:
    if staging_dir is None:
        return
    with suppress(OSError):
        shutil.rmtree(staging_dir, ignore_errors=True)


def _replace_layout_debug_sidecars(
    staging_dir: Path,
    final_path: Path,
    *,
    expected_final_dir_identity: DirectoryIdentity | None,
) -> None:
    sidecars = sorted(staging_dir.glob("*.layout.json"))
    if expected_final_dir_identity is None:
        for path in sidecars:
            path.replace(final_path / path.name)
        return
    if os.replace in os.supports_dir_fd:
        final_fd = _open_verified_layout_debug_dir(final_path, expected_final_dir_identity)
        try:
            for path in sidecars:
                os.replace(path, path.name, dst_dir_fd=final_fd)
        finally:
            os.close(final_fd)
        return
    for path in sidecars:
        _require_layout_debug_dir_identity(final_path, expected_final_dir_identity)
        path.replace(final_path / path.name)


def _layout_debug_dir_identity(path: Path) -> DirectoryIdentity:
    stat_result = path.lstat()
    if stat.S_ISLNK(stat_result.st_mode):
        raise ValueError("layout debug directory must not be a symlink")
    if not stat.S_ISDIR(stat_result.st_mode):
        raise ValueError("layout debug path must be a directory")
    return stat_result.st_dev, stat_result.st_ino


def _require_layout_debug_dir_identity(path: Path, expected: DirectoryIdentity) -> None:
    actual = _layout_debug_dir_identity(path)
    if actual != expected:
        raise ValueError("layout debug directory changed before sidecar promotion")


def _open_verified_layout_debug_dir(path: Path, expected: DirectoryIdentity) -> int:
    _require_layout_debug_dir_identity(path, expected)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        stat_result = os.fstat(fd)
        if not stat.S_ISDIR(stat_result.st_mode):
            raise ValueError("layout debug path must be a directory")
        if (stat_result.st_dev, stat_result.st_ino) != expected:
            raise ValueError("layout debug directory changed before sidecar promotion")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _render_extension_artifacts(
    plan: PreparedExtensionPublishPlan,
    *,
    runtime,
) -> RenderedExtensionArtifacts:
    return _rendering_impl.render_extension_artifacts(
        plan,
        runtime=runtime,
        render_frames_to_pdf=render_module.render_frames_to_pdf,
        layout_debug_json_path=layout_debug_json_path,
        build_kit_index_inventory_rows=build_recovery_kit_index_inventory_rows,
    )


def _result_root_passphrase_shard_threshold(
    plan: PreparedExtensionPublishPlan,
    *,
    root_passphrase_shard_threshold: int | None,
    root_passphrase_shard_count: int | None,
) -> int | None:
    if root_passphrase_shard_count is None:
        return plan.prepared.root_passphrase_shard_threshold
    return root_passphrase_shard_threshold


def _result_root_passphrase_shard_count(
    plan: PreparedExtensionPublishPlan,
    *,
    root_passphrase_shard_count: int | None,
) -> int:
    if root_passphrase_shard_count is None:
        return plan.prepared.root_passphrase_shard_count
    return root_passphrase_shard_count


__all__ = [
    "execute_prepared_extend",
    "execute_staged_extension_publish",
    "run_extend",
    "validate_prepared_extend_render",
]
