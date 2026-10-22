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

"""Create replacement recovery documents for an existing backup."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn, cast

from ethernity.config import AppConfig, apply_render_style, load_app_config
from ethernity.core.models import ShardingConfig
from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    LEGACY_SHARD_VERSION,
    ShardPayload,
    create_replacement_shards,
    split_passphrase,
    split_signing_seed,
)
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import Frame
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import (
    ChainRecoveryResult,
)
from ethernity.publication import create_sibling_staging_dir
from ethernity.render.layout_debug import resolve_layout_debug_dir
from ethernity.render.service import RenderService
from ethernity.render.types import DocumentOrigin
from ethernity.workflows.recovery import inputs as recover_inputs
from ethernity.workflows.recovery.keys import (
    InsufficientShardError,
    RecoveryTrust,
    signing_seed_from_shard_frames,
)
from ethernity.workflows.recovery.planning import (
    RecoveryPlan,
    build_recovery_plan,
    normalize_recovery_request,
)
from ethernity.workflows.recovery.session import RecoverySession
from ethernity.workflows.recovery.source_state import LoadedRecoveryInputs
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.events import (
    CommandError as ApiCommandError,
    EventSink,
    emit_phase,
    emit_progress,
    event_session,
    report_render_page,
)
from ethernity.workflows.shared.operation_types import ReplacementRecoveryOperationResult
from ethernity.workflows.shared.outputs import (
    commit_prepared_output_dir,
    discard_prepared_output_dir,
    ensure_directory,
)
from ethernity.workflows.shared.quorum import validate_quorum_pair
from ethernity.workflows.shared.requests import (
    RecoveryRequest,
    ReplacementRecoveryRequest,
)
from ethernity.workflows.shared.shard_rendering import ShardRenderContext, render_shard_documents


@dataclass(frozen=True)
class _ReplacementShardResolution:
    payloads: tuple[ShardPayload, ...] = ()
    provided_count: int = 0
    threshold: int | None = None
    shard_version: int | None = None

    @property
    def under_quorum(self) -> bool:
        return self.threshold is not None and self.provided_count < self.threshold

    @property
    def uses_legacy_shards(self) -> bool:
        return self.shard_version == LEGACY_SHARD_VERSION


@dataclass(frozen=True)
class _ReplacementInputState:
    config: AppConfig
    recover_args: RecoveryRequest
    loaded: LoadedRecoveryInputs
    signing_key_frames: tuple[Frame, ...]


@dataclass(frozen=True)
class ReplacementRecoveryMaterial:
    """Root credentials and selected version already verified by the consuming workflow."""

    trust: RecoveryTrust
    passphrase: str
    signing_seed: bytes
    signing_key_source: str
    selected_extension_index: int | None = None
    selected_extension_doc_hash: str | None = None


def execute_replacement_recovery_operation(
    args: ReplacementRecoveryRequest,
    *,
    debug: bool = False,
    event_sink: EventSink | None = None,
    session: RecoverySession | None = None,
) -> ReplacementRecoveryOperationResult:
    """Create replacement recovery documents and return the result."""

    session = session or RecoverySession()
    with event_session(event_sink):
        emit_phase(phase="plan", label="Resolving replacement recovery inputs")
        state = _load_replacement_input_state(args, session=session)
        shard_frames = list(state.loaded.shard_frames)
        plan = _build_replacement_recovery_plan(args, state, session=session)
        if plan.auth_payload is None:
            raise ApiCommandError(
                code=issue_codes.AUTH_REQUIRED,
                message=(
                    "replacement recovery requires an authenticated backup input with an AUTH "
                    "payload"
                ),
            )

        plan.emit_plan_progress(
            details={
                "input_label": state.loaded.source.input_label,
                "input_detail": state.loaded.source.input_detail,
                "shard_frame_count": len(shard_frames),
                "signing_key_shard_frame_count": len(state.signing_key_frames),
            }
        )

        emit_phase(phase="generate", label="Generating replacement shard payloads")
        return _replacement_from_plan(
            plan=plan,
            config=state.config,
            args=args,
            passphrase_shard_frames=shard_frames,
            signing_key_frames=list(state.signing_key_frames),
            debug=debug,
            session=session,
        )


def _replacement_plan_inputs(
    args: ReplacementRecoveryRequest, state: _ReplacementInputState
) -> LoadedRecoveryInputs:
    shard_frames, fallback_files, payload_files = _recovery_shard_inputs_for_plan(
        passphrase=args.passphrase,
        shard_frames=list(state.loaded.shard_frames),
        shard_fallback_files=list(state.loaded.shard_fallback_files),
        shard_payloads_file=list(state.loaded.shard_payload_files),
    )
    return replace(
        state.loaded,
        shard_frames=tuple(shard_frames),
        shard_fallback_files=tuple(fallback_files),
        shard_payload_files=tuple(payload_files),
    )


def _build_replacement_recovery_plan(
    args: ReplacementRecoveryRequest, state: _ReplacementInputState, *, session: RecoverySession
) -> RecoveryPlan:
    return build_recovery_plan(
        _replacement_plan_inputs(args, state),
        replace(state.recover_args, expected_head_doc_hash=args.expected_head_doc_hash),
        session=session,
    )


def _load_replacement_input_state(
    args: ReplacementRecoveryRequest,
    *,
    session: RecoverySession | None = None,
) -> _ReplacementInputState:
    config = load_app_config(args.config_path, paper_size=args.paper_size)
    config = apply_render_style(config, args.design)
    recover_args = _recovery_request_for_replacement(args)
    loaded = (session or RecoverySession()).load(recover_args)
    frames = list(loaded.source.frames)
    shard_frames = list(loaded.shard_frames)
    detected_signing_key_frames = recover_inputs.document_sheet_frames(
        frames, key_type=KEY_TYPE_SIGNING_SEED
    )
    frames, shard_frames = recover_inputs.route_document_frames(
        frames, shard_frames, passphrase=args.passphrase
    )
    signing_key_frames = [
        *detected_signing_key_frames,
        *_signing_key_shard_frames_from_args(args, quiet=args.quiet),
    ]
    return _ReplacementInputState(
        config=config,
        recover_args=recover_args,
        loaded=replace(
            loaded,
            source=replace(loaded.source, frames=tuple(frames)),
            shard_frames=tuple(shard_frames),
        ),
        signing_key_frames=tuple(signing_key_frames),
    )


def _raise_extension_recovery_error(exc: ExtensionRecoveryError) -> NoReturn:
    raise ApiCommandError(code=exc.code, message=str(exc), details=exc.details) from exc


def _recover_replacement_chain(
    plan: RecoveryPlan,
    *,
    debug: bool,
    allow_stale_head: bool = False,
    session: RecoverySession | None = None,
) -> ChainRecoveryResult:
    try:
        chain = (session or RecoverySession()).recover_chain(plan, debug=debug)
    except ExtensionRecoveryError as exc:
        _raise_extension_recovery_error(exc)
    _require_replacement_head_acknowledgement(
        plan,
        allow_stale_head=allow_stale_head,
        selected_extension_index=chain.selected_extension_index,
        selected_extension_doc_hash=chain.selected_extension_doc_hash,
        has_imported_extensions=len(plan.import_documents) > 1,
    )
    return chain


def _require_replacement_head_acknowledgement(
    plan: Any,
    *,
    allow_stale_head: bool,
    selected_extension_index: int | None,
    selected_extension_doc_hash: str | None,
    has_imported_extensions: bool,
) -> None:
    if not has_imported_extensions:
        return
    if getattr(plan, "expected_head_doc_hash", None) is not None or allow_stale_head:
        return
    validated_head_index = selected_extension_index if selected_extension_index is not None else 0
    validated_head_doc_hash = selected_extension_doc_hash or plan.doc_hash.hex()
    raise ApiCommandError(
        code=issue_codes.RECOVERY_HEAD_UNTRUSTED,
        message=(
            "replacement recovery cannot prove the supplied set is the latest chain state; "
            "provide an expected latest backup fingerprint or acknowledge that newer documents "
            "may be missing"
        ),
        details={
            "stage": "selection",
            "validated_head_index": validated_head_index,
            "validated_head_doc_hash": validated_head_doc_hash,
            "freshness_scope": "supplied_carriers_only",
            "required_acknowledgement": "--allow-stale-head",
        },
    )


def _recovery_request_for_replacement(args: ReplacementRecoveryRequest) -> RecoveryRequest:
    recovery_request = replace(
        args.recovery_request(),
        config_path=args.config_path,
        paper_size=args.paper_size,
        recovery_text_file=args.recovery_text_file,
        payloads_file=args.payloads_file,
        scan_paths=args.scan_paths,
        frames=args.frames,
        extension_index=args.extension_index,
        extension_doc_hash=args.extension_doc_hash,
        quiet=args.quiet,
    )
    return normalize_recovery_request(recovery_request)


def _validate_replacement_args(args: ReplacementRecoveryRequest) -> None:
    if not args.create_passphrase_shards and not args.create_signing_key_shards:
        raise ValueError("replacement recovery must create at least one shard document type")
    if args.passphrase_replacement_count is not None and not args.create_passphrase_shards:
        raise ValueError(
            "cannot request passphrase replacement shards when passphrase output is off"
        )
    if args.signing_key_replacement_count is not None and not args.create_signing_key_shards:
        raise ValueError(
            "cannot request replacement signing-key shards when signing-key output is off"
        )
    _validate_replacement_counts(args)


def _validate_replacement_counts(args: ReplacementRecoveryRequest) -> None:
    if args.passphrase_replacement_count is not None and args.passphrase_replacement_count < 1:
        raise ValueError("passphrase replacement count must be >= 1")
    if args.signing_key_replacement_count is not None and args.signing_key_replacement_count < 1:
        raise ValueError("signing key replacement count must be >= 1")
    if args.passphrase_replacement_count is not None and not _has_existing_shard_inputs(
        args.shard_text_files,
        args.shard_payload_files,
        args.shard_scan_paths,
    ):
        raise ValueError("passphrase shard replacement requires existing passphrase shard inputs")
    if args.signing_key_replacement_count is not None and not _has_existing_shard_inputs(
        args.signing_key_shard_text_files,
        args.signing_key_shard_payload_files,
        args.signing_key_shard_scan_paths,
    ):
        raise ValueError("signing-key shard replacement requires existing signing-key shard inputs")
    validate_quorum_pair(
        args.shard_threshold,
        args.shard_count,
        pair_label="--shard-threshold and --shard-count",
        required=(args.create_passphrase_shards and args.passphrase_replacement_count is None),
    )
    validate_quorum_pair(
        args.signing_key_shard_threshold,
        args.signing_key_shard_count,
        label="signing-key shard",
        pair_label=("--signing-key-shard-threshold and --signing-key-shard-count"),
        required=False,
    )
    if args.create_signing_key_shards:
        if args.signing_key_replacement_count is not None:
            return
        has_explicit_signing_quorum = (
            args.signing_key_shard_threshold is not None
            and args.signing_key_shard_count is not None
        )
        has_passphrase_quorum = args.shard_threshold is not None and args.shard_count is not None
        if not has_explicit_signing_quorum and not has_passphrase_quorum:
            raise ValueError(
                "creating signing-key shards requires a shard quorum or an explicit "
                "signing-key shard quorum"
            )


def _has_existing_shard_inputs(
    fallback_files: Sequence[str | Path],
    payload_files: Sequence[str | Path],
    scan_paths: Sequence[str | Path] = (),
) -> bool:
    return bool(fallback_files or payload_files or scan_paths)


def _recovery_shard_inputs_for_plan(
    *,
    passphrase: str | None,
    shard_frames: list[Frame],
    shard_fallback_files: list[str],
    shard_payloads_file: list[str],
) -> tuple[list[Frame], list[str], list[str]]:
    if passphrase:
        return [], [], []
    return shard_frames, shard_fallback_files, shard_payloads_file


def _replacement_from_plan(
    *,
    plan: RecoveryPlan,
    config: AppConfig,
    args: ReplacementRecoveryRequest,
    passphrase_shard_frames: list[Frame],
    signing_key_frames: list[Frame],
    debug: bool,
    session: RecoverySession | None = None,
) -> ReplacementRecoveryOperationResult:
    chain = _recover_replacement_chain(
        plan,
        debug=debug,
        allow_stale_head=args.allow_stale_head,
        session=session,
    )
    if plan.auth_payload is None:
        raise ValueError("replacement recovery requires a verified root AUTH payload")
    sign_priv, signing_key_source = _recover_signing_seed(
        manifest_signing_seed=chain.manifest.signing_seed,
        signing_key_frames=signing_key_frames,
        doc_id=plan.doc_id,
        doc_hash=plan.doc_hash,
        expected_sign_pub=plan.auth_payload.sign_pub,
    )
    material = ReplacementRecoveryMaterial(
        trust=RecoveryTrust(plan.doc_id, plan.doc_hash, plan.auth_payload.sign_pub, False),
        passphrase=plan.passphrase,
        signing_seed=sign_priv,
        signing_key_source=signing_key_source,
        selected_extension_index=chain.selected_extension_index,
        selected_extension_doc_hash=chain.selected_extension_doc_hash,
    )
    return create_replacement_documents(
        material,
        config=config,
        args=args,
        passphrase_shard_frames=passphrase_shard_frames,
        signing_key_frames=signing_key_frames,
    )


def create_replacement_documents(
    material: ReplacementRecoveryMaterial,
    *,
    config: AppConfig,
    args: ReplacementRecoveryRequest,
    passphrase_shard_frames: Sequence[Frame] = (),
    signing_key_frames: Sequence[Frame] = (),
) -> ReplacementRecoveryOperationResult:
    """Generate sheets from verified credentials without reopening the backup."""
    _validate_replacement_args(args)
    sign_priv = material.signing_seed
    sign_pub = derive_public_key(sign_priv)
    if material.trust.allow_unsigned or sign_pub != material.trust.sign_pub:
        raise ValueError("signing key does not match the authenticated backup")

    passphrase_resolution, shard_payloads = _create_passphrase_output(
        material, args, list(passphrase_shard_frames), sign_priv, sign_pub
    )
    signing_resolution, signing_key_payloads = _create_signing_key_output(
        material, args, list(signing_key_frames), sign_priv, sign_pub
    )
    emit_phase(phase="output", label="Preparing replacement destination")
    output_dir = _ensure_replacement_output_dir(
        args.output_dir,
        material.trust.doc_id.hex(),
        existing_directory_is_parent=args.output_dir_existing_parent,
    )
    staging_output_dir = _prepare_replacement_staging_dir(output_dir)
    try:
        layout_debug_dir = resolve_layout_debug_dir(
            args.layout_debug_dir,
            forbidden_dirs={
                "final output": output_dir,
                "staging output": staging_output_dir,
            },
        )
        render_service = RenderService(config, on_page=report_render_page)
        qr_payload_codec = config.cli_defaults.backup.qr_payload_codec
        emit_progress(
            phase="generate",
            current=1,
            total=1,
            unit="step",
            details={
                "passphrase_shard_count": len(shard_payloads),
                "signing_key_shard_count": len(signing_key_payloads),
                "signing_key_source": material.signing_key_source,
            },
        )
        shard_paths, signing_key_shard_paths = _render_replacement_documents(
            shard_payloads,
            signing_key_payloads,
            context=ShardRenderContext(
                doc_id=material.trust.doc_id,
                output_dir=staging_output_dir,
                render_service=render_service,
                layout_debug_dir=layout_debug_dir,
                qr_payload_codec=qr_payload_codec,
                origin=DocumentOrigin(kind="replacement_recovery"),
            ),
        )
        commit_prepared_output_dir(staging_output_dir, output_dir)
    except BaseException:
        discard_prepared_output_dir(staging_output_dir)
        raise

    notes = _legacy_replacement_notes(
        passphrase_resolution=passphrase_resolution,
        signing_resolution=signing_resolution,
        args=args,
    )

    final_output_dir = Path(output_dir)
    final_shard_paths = tuple(str(final_output_dir / Path(path).name) for path in shard_paths)
    final_signing_key_shard_paths = tuple(
        str(final_output_dir / Path(path).name) for path in signing_key_shard_paths
    )

    return ReplacementRecoveryOperationResult(
        doc_id=material.trust.doc_id,
        doc_hash=material.trust.doc_hash,
        output_dir=output_dir,
        shard_paths=final_shard_paths,
        signing_key_shard_paths=final_signing_key_shard_paths,
        signing_key_source=material.signing_key_source,
        notes=notes,
        selected_extension_index=material.selected_extension_index,
        selected_extension_doc_hash=material.selected_extension_doc_hash,
    )


def _render_replacement_documents(
    passphrase_shards: Sequence[ShardPayload],
    signing_key_shards: Sequence[ShardPayload],
    *,
    context: ShardRenderContext,
) -> tuple[list[str], list[str]]:
    total = len(passphrase_shards) + len(signing_key_shards)
    rendered = 0

    def report_shard(shard: ShardPayload, path: str) -> None:
        nonlocal rendered
        rendered += 1
        signing_key = shard.key_type == KEY_TYPE_SIGNING_SEED
        label = "signing-key" if signing_key else "passphrase"
        kind = "signing_key_shard_document" if signing_key else "shard_document"
        emit_progress(
            phase="render",
            current=rendered,
            total=total,
            unit="documents",
            label=f"Rendered {label} shard {shard.share_index} of {shard.share_count}",
            details={"path": path, "kind": kind},
        )

    emit_phase(phase="render", label="Rendering replacement shard documents")
    return render_shard_documents(
        passphrase_shards,
        signing_key_shards,
        context=context,
        on_document=report_shard,
    )


def _create_signing_key_output(
    material: ReplacementRecoveryMaterial,
    args: ReplacementRecoveryRequest,
    signing_key_frames: list[Frame],
    sign_priv: bytes,
    sign_pub: bytes,
) -> tuple[_ReplacementShardResolution, list[ShardPayload]]:
    signing_resolution = _ReplacementShardResolution()
    signing_key_payloads: list[ShardPayload] = []
    if args.create_signing_key_shards:
        if args.signing_key_replacement_count is not None:
            signing_resolution = _replacement_payloads_from_frames(
                signing_key_frames,
                doc_id=material.trust.doc_id,
                doc_hash=material.trust.doc_hash,
                sign_pub=sign_pub,
                key_type=KEY_TYPE_SIGNING_SEED,
                secret_label="signing key",
            )
            _require_replacement_payloads(
                signing_resolution,
                secret_label="signing key",
            )
            signing_key_payloads = create_replacement_shards(
                list(signing_resolution.payloads),
                count=args.signing_key_replacement_count,
                sign_priv=sign_priv,
            )
        else:
            signing_key_sharding = _resolve_signing_key_output_sharding(args)
            signing_key_payloads = split_signing_seed(
                sign_priv,
                threshold=signing_key_sharding.threshold,
                shares=signing_key_sharding.shares,
                doc_hash=material.trust.doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )

    return signing_resolution, signing_key_payloads


def _create_passphrase_output(
    material: ReplacementRecoveryMaterial,
    args: ReplacementRecoveryRequest,
    passphrase_shard_frames: list[Frame],
    sign_priv: bytes,
    sign_pub: bytes,
) -> tuple[_ReplacementShardResolution, list[ShardPayload]]:
    passphrase_resolution = _ReplacementShardResolution()
    shard_payloads: list[ShardPayload] = []
    if args.create_passphrase_shards:
        if args.passphrase_replacement_count is not None:
            passphrase_resolution = _replacement_payloads_from_frames(
                passphrase_shard_frames,
                doc_id=material.trust.doc_id,
                doc_hash=material.trust.doc_hash,
                sign_pub=sign_pub,
                key_type=KEY_TYPE_PASSPHRASE,
                secret_label="passphrase",
            )
            _require_replacement_payloads(
                passphrase_resolution,
                secret_label="passphrase",
            )
            shard_payloads = create_replacement_shards(
                list(passphrase_resolution.payloads),
                count=args.passphrase_replacement_count,
                sign_priv=sign_priv,
            )
        else:
            passphrase_sharding = ShardingConfig(
                threshold=_required_int(args.shard_threshold, label="shard threshold"),
                shares=_required_int(args.shard_count, label="shard count"),
            )
            shard_payloads = split_passphrase(
                material.passphrase,
                threshold=passphrase_sharding.threshold,
                shares=passphrase_sharding.shares,
                doc_hash=material.trust.doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )

    return passphrase_resolution, shard_payloads


def _signing_key_shard_frames_from_args(
    args: ReplacementRecoveryRequest, *, quiet: bool
) -> list[Frame]:
    signing_key_frames = list(args.signing_key_shard_frames or [])
    fallback_files = list(args.signing_key_shard_text_files or [])
    payload_files = list(args.signing_key_shard_payload_files or [])
    scan_files = list(args.signing_key_shard_scan_paths or [])
    if not fallback_files and not payload_files and not scan_files:
        return signing_key_frames
    temp_args = RecoveryRequest(
        shard_text_files=fallback_files,
        shard_payload_files=payload_files,
        shard_frames=signing_key_frames,
        shard_scan_paths=scan_files,
        quiet=quiet,
    )
    frames, _fallback_files, _payload_files, _scan_files = recover_inputs.load_shard_frames(
        temp_args,
        quiet=quiet,
    )
    return frames


def _recover_signing_seed(
    *,
    manifest_signing_seed: bytes | None,
    signing_key_frames: list[Frame],
    doc_id: bytes,
    doc_hash: bytes,
    expected_sign_pub: bytes,
) -> tuple[bytes, str]:
    if manifest_signing_seed is not None:
        return manifest_signing_seed, "embedded signing seed"
    if not signing_key_frames:
        raise ApiCommandError(
            code=issue_codes.SIGNING_KEY_SHARDS_REQUIRED,
            message=(
                "backup is sealed; provide signing-key shard inputs to create new shard documents"
            ),
        )
    signing_seed = signing_seed_from_shard_frames(
        signing_key_frames,
        expected_doc_id=doc_id,
        expected_doc_hash=doc_hash,
        expected_sign_pub=expected_sign_pub,
        allow_unsigned=False,
    )
    return signing_seed, "signing-key shards"


def _replacement_payloads_from_frames(
    frames: list[Frame],
    *,
    doc_id: bytes,
    doc_hash: bytes,
    sign_pub: bytes,
    key_type: str,
    secret_label: str,
) -> _ReplacementShardResolution:
    if not frames:
        return _ReplacementShardResolution()
    try:
        payloads = RecoveryTrust(doc_id, doc_hash, sign_pub, False).validated_shards(
            frames, key_type=key_type, secret_label=secret_label
        )
    except InsufficientShardError as exc:
        return _ReplacementShardResolution(
            provided_count=exc.provided_count,
            threshold=exc.threshold,
            shard_version=exc.shard_version,
        )
    return _ReplacementShardResolution(
        payloads=tuple(payloads),
        shard_version=payloads[0].version if payloads else None,
    )


def _legacy_replacement_notes(
    *,
    passphrase_resolution: _ReplacementShardResolution,
    signing_resolution: _ReplacementShardResolution,
    args: ReplacementRecoveryRequest,
) -> tuple[str, ...]:
    notes: list[str] = []
    if args.passphrase_replacement_count is not None and passphrase_resolution.uses_legacy_shards:
        notes.append(
            "Legacy v1 passphrase shards detected. Compatible replacements stay on v1; "
            "prefer creating a full new passphrase shard set to migrate to shard payload v2."
        )
    if args.signing_key_replacement_count is not None and signing_resolution.uses_legacy_shards:
        notes.append(
            "Legacy v1 signing-key shards detected. Compatible replacements stay on v1; "
            "prefer creating a full new signing-key shard set to migrate to shard payload v2."
        )
    return tuple(notes)


def _require_replacement_payloads(
    resolution: _ReplacementShardResolution,
    *,
    secret_label: str,
) -> None:
    if resolution.payloads:
        return
    if resolution.under_quorum:
        threshold = cast(int, resolution.threshold)
        raise ValueError(
            f"cannot create compatible replacement {secret_label} shards: "
            f"need at least {threshold} validated shard(s), got {resolution.provided_count}"
            f"{_legacy_replacement_resolution_hint(resolution, secret_label=secret_label)}"
        )
    raise ValueError(
        f"cannot create compatible replacement {secret_label} shards: "
        f"provide existing {secret_label} shard inputs"
    )


def _legacy_replacement_resolution_hint(
    resolution: _ReplacementShardResolution,
    *,
    secret_label: str,
) -> str:
    if not resolution.uses_legacy_shards:
        return ""
    return (
        f". Existing {secret_label} shards are legacy v1; compatible replacements stay on v1, "
        f"so create a fresh {secret_label} shard set to migrate to shard payload v2"
    )


def _resolve_signing_key_output_sharding(
    args: ReplacementRecoveryRequest,
) -> ShardingConfig:
    if args.signing_key_shard_threshold is not None and args.signing_key_shard_count is not None:
        return ShardingConfig(
            threshold=args.signing_key_shard_threshold,
            shares=args.signing_key_shard_count,
        )
    return ShardingConfig(
        threshold=_required_int(args.shard_threshold, label="shard threshold"),
        shares=_required_int(args.shard_count, label="shard count"),
    )


def _required_int(value: int | None, *, label: str) -> int:
    if value is None:
        raise ValueError(f"{label} is required")
    return value


def replacement_recovery_directory_name(doc_id: bytes | str) -> str:
    """Return the output directory name for one document-bound replacement sheet set."""

    doc_id_hex = doc_id.hex() if isinstance(doc_id, bytes) else doc_id
    return f"replacement-recovery-{doc_id_hex}"


def require_replacement_recovery_output_available(path: str | Path) -> Path:
    """Return an unused replacement-recovery output path or raise."""

    resolved = Path(path).expanduser()
    if resolved.exists() or resolved.is_symlink():
        raise ValueError(
            f"output directory already exists: {resolved}; "
            "choose a new folder for replacement recovery sheets"
        )
    return resolved


def _ensure_replacement_output_dir(
    output_dir: str | Path | None,
    doc_id_hex: str,
    *,
    existing_directory_is_parent: bool = False,
) -> str:
    directory_name = replacement_recovery_directory_name(doc_id_hex)
    directory = output_dir or directory_name
    resolved = Path(directory).expanduser()
    if existing_directory_is_parent and resolved.is_dir():
        resolved = resolved / directory_name
    resolved = require_replacement_recovery_output_available(resolved)
    ensure_directory(resolved.parent, exist_ok=True)
    return str(resolved)


def _prepare_replacement_staging_dir(output_dir: str) -> str:
    return str(create_sibling_staging_dir(output_dir))
