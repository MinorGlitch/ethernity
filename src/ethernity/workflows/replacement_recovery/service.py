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
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    LEGACY_SHARD_VERSION,
    ShardPayload,
    create_replacement_shards,
    decode_shard_payload,
    split_passphrase,
    split_signing_seed,
)
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import Frame
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import (
    ChainRecoveryResult,
    recover_chain_entries,
)
from ethernity.formats.document_codec import decode_backup_document
from ethernity.formats.manifest import BackupManifest
from ethernity.formats.manifest_summary import manifest_summary_payload
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
    RecoveryInspection,
    RecoveryPlan,
    build_recovery_plan,
    inspect_recovery_inputs,
    normalize_recovery_request,
)
from ethernity.workflows.shared import issue_codes
from ethernity.workflows.shared.events import (
    CommandError as ApiCommandError,
    EventSink,
    emit_phase,
    emit_progress,
    event_session,
    report_render_page,
)
from ethernity.workflows.shared.inspection import (
    blocking_issue,
    blocking_issue_from_exception,
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
    frames: tuple[Frame, ...]
    extra_auth_frames: tuple[Frame, ...]
    shard_frames: tuple[Frame, ...]
    shard_fallback_files: tuple[str, ...]
    shard_payloads_file: tuple[str, ...]
    shard_scan: tuple[str, ...]
    signing_key_frames: tuple[Frame, ...]
    input_label: str | None
    input_detail: str | None


@dataclass(frozen=True)
class ReplacementRecoveryInspection:
    recovery: RecoveryInspection
    manifest: BackupManifest | None
    source_summary: dict[str, object] | None
    selected_extension_index: int | None
    selected_extension_doc_hash: str | None
    signing_key_frame_count: int
    signing_key_validated_shard_count: int
    signing_key_required_threshold: int | None
    signing_key_satisfied: bool
    signing_key_source: str | None
    replacement_capabilities: dict[str, bool]
    blocking_issues: tuple[dict[str, Any], ...]


_PASSPHRASE_REPLACEMENT_BLOCKER_CODES = frozenset({"PASSPHRASE_REPLACEMENT_NOT_READY"})
_SIGNING_KEY_REPLACEMENT_BLOCKER_CODES = frozenset({"SIGNING_KEY_REPLACEMENT_NOT_READY"})


def execute_replacement_recovery_operation(
    args: ReplacementRecoveryRequest,
    *,
    debug: bool = False,
    event_sink: EventSink | None = None,
) -> ReplacementRecoveryOperationResult:
    """Create replacement recovery documents and return the result."""

    with event_session(event_sink):
        emit_phase(phase="plan", label="Resolving replacement recovery inputs")
        state = _load_replacement_input_state(args)
        shard_frames = list(state.shard_frames)
        plan = _build_replacement_recovery_plan(args, state, passphrase_shard_frames=shard_frames)
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
                "input_label": state.input_label,
                "input_detail": state.input_detail,
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
        )


def inspect_replacement_recovery_inputs(
    args: ReplacementRecoveryRequest, *, debug: bool = False
) -> ReplacementRecoveryInspection:
    state = _load_replacement_input_state(args, require_output_configuration=False)
    recovery_shard_frames, recovery_shard_fallback_files, recovery_shard_payloads_file = (
        _recovery_shard_inputs_for_plan(
            passphrase=args.passphrase,
            shard_frames=list(state.shard_frames),
            shard_fallback_files=list(state.shard_fallback_files),
            shard_payloads_file=list(state.shard_payloads_file),
        )
    )
    plan = _try_build_replacement_recovery_plan(
        args,
        state,
        passphrase_shard_frames=list(state.shard_frames),
    )
    recovery = _inspect_replacement_root(
        args,
        state,
        plan,
        recovery_shard_frames,
        recovery_shard_fallback_files,
        recovery_shard_payloads_file,
    )
    blocking_issues = [dict(item) for item in recovery.blocking_issues]
    if recovery.auth_payload is None:
        _append_unique_blocking_issue(
            blocking_issues,
            blocking_issue(
                "AUTH_REQUIRED",
                "replacement recovery requires an authenticated backup input with an AUTH payload",
            ),
        )

    if plan is None and recovery.auth_payload is not None and recovery.unlock.satisfied:
        plan = _try_build_replacement_recovery_plan(
            args,
            state,
            passphrase_shard_frames=list(state.shard_frames),
        )
    chain = None
    selected_extension_index: int | None = None
    selected_extension_doc_hash: str | None = None
    chain_target_trusted = True
    if plan is not None:
        try:
            chain = _recover_replacement_chain(
                plan,
                debug=debug,
                allow_stale_head=args.allow_stale_head,
            )
            recovery = _replacement_recovery_inspection_with_root(recovery, plan)
        except Exception as exc:
            chain_target_trusted = False
            _append_unique_blocking_issue(
                blocking_issues,
                dict(
                    blocking_issue_from_exception(
                        exc,
                        fallback_code=issue_codes.RECOVERY_HEAD_UNTRUSTED,
                        fallback_details={"stage": "replay"},
                    )
                ),
            )

    manifest: BackupManifest | None = None
    source_summary: dict[str, object] | None = None
    if (
        chain_target_trusted
        and recovery.unlock.satisfied
        and recovery.unlock.resolved_passphrase is not None
    ):
        if chain is not None:
            manifest = chain.manifest
            selected_extension_index = chain.selected_extension_index
            selected_extension_doc_hash = chain.selected_extension_doc_hash
            source_summary = manifest_summary_payload(manifest)
        else:
            try:
                ciphertext = recovery.ciphertext
                passphrase = recovery.unlock.resolved_passphrase
                plaintext = decrypt_bytes(
                    ciphertext,
                    passphrase=passphrase,
                    debug=debug,
                )
                manifest, _payload = decode_backup_document(plaintext)
                source_summary = manifest_summary_payload(manifest)
            except Exception as exc:
                _append_unique_blocking_issue(
                    blocking_issues,
                    blocking_issue("UNLOCK_FAILED", str(exc), details={"stage": "decrypt"}),
                )

    (
        signing_key_validated_shard_count,
        signing_key_required_threshold,
        signing_key_satisfied,
        signing_key_source,
        signing_key_issues,
    ) = _inspect_replacement_signing_key_state(
        manifest=manifest,
        recovery=recovery,
        signing_key_frames=list(state.signing_key_frames),
    )
    _append_unique_blocking_issues(blocking_issues, signing_key_issues)
    _append_unique_blocking_issues(
        blocking_issues,
        _inspect_replacement_replacement_blockers(
            args=args,
            recovery=recovery,
            passphrase_shard_frames=list(state.shard_frames),
            signing_key_frames=list(state.signing_key_frames),
        ),
    )

    replacement_capabilities = _inspect_replacement_capabilities(
        args=args,
        recovery=recovery,
        manifest=manifest,
        signing_key_satisfied=signing_key_satisfied,
        blocking_issues=blocking_issues,
    )
    return ReplacementRecoveryInspection(
        recovery=recovery,
        manifest=manifest,
        source_summary=source_summary,
        selected_extension_index=selected_extension_index,
        selected_extension_doc_hash=selected_extension_doc_hash,
        signing_key_frame_count=len(state.signing_key_frames),
        signing_key_validated_shard_count=signing_key_validated_shard_count,
        signing_key_required_threshold=signing_key_required_threshold,
        signing_key_satisfied=signing_key_satisfied,
        signing_key_source=signing_key_source,
        replacement_capabilities=replacement_capabilities,
        blocking_issues=tuple(blocking_issues),
    )


def _inspect_replacement_root(
    args: ReplacementRecoveryRequest,
    state: _ReplacementInputState,
    plan: RecoveryPlan | None,
    recovery_shard_frames: list[Frame],
    recovery_shard_fallback_files: list[str],
    recovery_shard_payloads_file: list[str],
) -> RecoveryInspection:
    inspection_frames = list(state.frames)
    inspection_extra_auth_frames = list(state.extra_auth_frames)
    inspection_passphrase = args.passphrase
    inspection_shard_frames = recovery_shard_frames
    inspection_shard_fallback_files = recovery_shard_fallback_files
    inspection_shard_payloads_file = recovery_shard_payloads_file
    if plan is not None:
        inspection_frames = list(plan.main_frames)
        inspection_extra_auth_frames = list(plan.auth_frames)
        if inspection_passphrase is None:
            inspection_passphrase = plan.passphrase
            inspection_shard_frames = []
            inspection_shard_fallback_files = []
            inspection_shard_payloads_file = []

    recovery = inspect_recovery_inputs(
        frames=inspection_frames,
        extra_auth_frames=inspection_extra_auth_frames,
        shard_frames=inspection_shard_frames,
        passphrase=inspection_passphrase,
        allow_unsigned=False,
        input_label=state.input_label,
        input_detail=state.input_detail,
        shard_fallback_files=inspection_shard_fallback_files,
        shard_payloads_file=inspection_shard_payloads_file,
        shard_scan=list(state.shard_scan),
        quiet=args.quiet,
    )
    if plan is not None and args.passphrase is None and plan.shard_frames:
        recovery = _replacement_recovery_inspection_with_plan_shard_unlock(recovery, plan)

    return recovery


def _build_replacement_recovery_plan(
    args: ReplacementRecoveryRequest,
    state: _ReplacementInputState,
    *,
    passphrase_shard_frames: list[Frame],
) -> RecoveryPlan:
    recovery_shard_frames, recovery_shard_fallback_files, recovery_shard_payloads_file = (
        _recovery_shard_inputs_for_plan(
            passphrase=args.passphrase,
            shard_frames=passphrase_shard_frames,
            shard_fallback_files=list(state.shard_fallback_files),
            shard_payloads_file=list(state.shard_payloads_file),
        )
    )
    return build_recovery_plan(
        frames=list(state.frames),
        extra_auth_frames=list(state.extra_auth_frames),
        shard_frames=recovery_shard_frames,
        passphrase=args.passphrase,
        allow_unsigned=False,
        input_label=state.input_label,
        input_detail=state.input_detail,
        shard_fallback_files=recovery_shard_fallback_files,
        shard_payloads_file=recovery_shard_payloads_file,
        shard_scan=list(state.shard_scan),
        output_path=None,
        extension_index=args.extension_index,
        extension_doc_hash=args.extension_doc_hash,
        expected_head_doc_hash=args.expected_head_doc_hash,
        args=state.recover_args,
        quiet=args.quiet,
    )


def _try_build_replacement_recovery_plan(
    args: ReplacementRecoveryRequest,
    state: _ReplacementInputState,
    *,
    passphrase_shard_frames: list[Frame],
) -> RecoveryPlan | None:
    if not (args.passphrase or passphrase_shard_frames):
        return None
    try:
        return _build_replacement_recovery_plan(
            args,
            state,
            passphrase_shard_frames=passphrase_shard_frames,
        )
    except Exception:
        return None


def _replacement_recovery_inspection_with_root(
    recovery: RecoveryInspection,
    plan: RecoveryPlan,
) -> RecoveryInspection:
    return replace(
        recovery,
        ciphertext=plan.ciphertext,
        doc_id=plan.doc_id,
        doc_hash=plan.doc_hash,
        auth_payload=plan.auth_payload,
        auth_status=plan.auth_status,
    )


def _replacement_recovery_inspection_with_plan_shard_unlock(
    recovery: RecoveryInspection,
    plan: RecoveryPlan,
) -> RecoveryInspection:
    shard_payloads = _replacement_passphrase_shard_payloads_for_inspection(plan.shard_frames)
    if not shard_payloads:
        return recovery
    unique_share_indexes = {payload.share_index for payload in shard_payloads}
    first_payload = shard_payloads[0]
    return replace(
        recovery,
        unlock=replace(
            recovery.unlock,
            mode="shards",
            passphrase_provided=False,
            validated_shard_count=len(unique_share_indexes),
            required_shard_threshold=first_payload.threshold,
            shard_share_count=first_payload.share_count,
            satisfied=True,
            resolved_passphrase=plan.passphrase,
        ),
        source=replace(
            recovery.source,
            shard_frames=tuple(plan.shard_frames),
            shard_fallback_files=tuple(plan.shard_fallback_files),
            shard_payloads_file=tuple(plan.shard_payloads_file),
            shard_scan=tuple(plan.shard_scan),
        ),
    )


def _replacement_passphrase_shard_payloads_for_inspection(
    shard_frames: tuple[Frame, ...],
) -> tuple[ShardPayload, ...]:
    payloads: list[ShardPayload] = []
    for frame in shard_frames:
        try:
            payload = decode_shard_payload(frame.data)
        except ValueError:
            continue
        if payload.key_type == KEY_TYPE_PASSPHRASE:
            payloads.append(payload)
    return tuple(payloads)


def _append_unique_blocking_issue(
    blocking_issues: list[dict[str, Any]],
    issue: dict[str, Any],
) -> None:
    for existing in blocking_issues:
        if (
            existing.get("code") == issue.get("code")
            and existing.get("message") == issue.get("message")
            and existing.get("details") == issue.get("details")
        ):
            return
    blocking_issues.append(issue)


def _append_unique_blocking_issues(
    blocking_issues: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    for issue in issues:
        _append_unique_blocking_issue(blocking_issues, issue)


def _load_replacement_input_state(
    args: ReplacementRecoveryRequest,
    *,
    require_output_configuration: bool = True,
) -> _ReplacementInputState:
    _validate_replacement_args(args, require_output_configuration=require_output_configuration)
    config = load_app_config(args.config_path, paper_size=args.paper_size)
    config = apply_render_style(config, args.design)
    recover_args = _recovery_request_for_replacement(args)
    frames: list[Frame]
    input_label: str | None
    input_detail: str | None
    if args.frames:
        frames = list(args.frames)
        input_label = args.input_label or "Backup recovery input"
        input_detail = args.input_detail
    else:
        frames, input_label, input_detail = recover_inputs.load_recovery_frames(
            recover_args,
            allow_unsigned=False,
            quiet=args.quiet,
            include_recovery_sheets=True,
        )
    extra_auth_frames = recover_inputs.load_extra_auth_frames(
        recover_args,
        allow_unsigned=False,
        quiet=args.quiet,
    )
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = (
        recover_inputs.load_shard_frames(
            recover_args,
            quiet=args.quiet,
        )
    )
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
        frames=tuple(frames),
        extra_auth_frames=tuple(extra_auth_frames),
        shard_frames=tuple(shard_frames),
        shard_fallback_files=tuple(shard_fallback_files),
        shard_payloads_file=tuple(shard_payloads_file),
        shard_scan=tuple(shard_scan),
        signing_key_frames=tuple(signing_key_frames),
        input_label=input_label,
        input_detail=input_detail,
    )


def _inspect_replacement_signing_key_state(
    *,
    manifest: BackupManifest | None,
    recovery: RecoveryInspection,
    signing_key_frames: list[Frame],
) -> tuple[int, int | None, bool, str | None, list[dict[str, Any]]]:
    if manifest is None:
        return 0, None, False, None, []
    if manifest.signing_seed is not None:
        return 0, None, True, "embedded signing seed", []

    source = "signing-key shards"
    if recovery.auth_payload is None:
        return (
            0,
            None,
            False,
            source,
            [
                blocking_issue(
                    "AUTH_REQUIRED",
                    "replacement recovery requires an authenticated backup input with an AUTH "
                    "payload",
                )
            ],
        )
    if not signing_key_frames:
        return (
            0,
            None,
            False,
            source,
            [
                blocking_issue(
                    "SIGNING_KEY_SHARDS_REQUIRED",
                    (
                        "backup is sealed; provide signing-key shard inputs "
                        "to create replacement shard documents"
                    ),
                )
            ],
        )
    try:
        payloads = RecoveryTrust(
            recovery.doc_id, recovery.doc_hash, recovery.auth_payload.sign_pub, False
        ).validated_shards(
            signing_key_frames, key_type=KEY_TYPE_SIGNING_SEED, secret_label="signing key"
        )
    except InsufficientShardError as exc:
        return (
            exc.provided_count,
            exc.threshold,
            False,
            source,
            [
                blocking_issue(
                    "SIGNING_KEY_SHARDS_UNDER_QUORUM",
                    f"need at least {exc.threshold} shard(s) to recover signing key",
                    details={
                        "provided_count": exc.provided_count,
                        "required_threshold": exc.threshold,
                    },
                )
            ],
        )
    except ValueError as exc:
        return (
            0,
            None,
            False,
            source,
            [blocking_issue("SIGNING_KEY_SHARDS_INVALID", str(exc))],
        )
    return (
        len(payloads),
        payloads[0].threshold if payloads else None,
        True,
        source,
        [],
    )


def _inspect_replacement_replacement_blockers(
    *,
    args: ReplacementRecoveryRequest,
    recovery: RecoveryInspection,
    passphrase_shard_frames: list[Frame],
    signing_key_frames: list[Frame],
) -> list[dict[str, Any]]:
    if recovery.auth_payload is None:
        return []

    blockers: list[dict[str, Any]] = []
    if args.passphrase_replacement_count is not None:
        resolution = _replacement_payloads_from_frames(
            passphrase_shard_frames,
            doc_id=recovery.doc_id,
            doc_hash=recovery.doc_hash,
            sign_pub=recovery.auth_payload.sign_pub,
            key_type=KEY_TYPE_PASSPHRASE,
            secret_label="passphrase",
        )
        try:
            _require_replacement_payloads(resolution, secret_label="passphrase")
        except ValueError as exc:
            blockers.append(blocking_issue("PASSPHRASE_REPLACEMENT_NOT_READY", str(exc)))
    if args.signing_key_replacement_count is not None:
        resolution = _replacement_payloads_from_frames(
            signing_key_frames,
            doc_id=recovery.doc_id,
            doc_hash=recovery.doc_hash,
            sign_pub=recovery.auth_payload.sign_pub,
            key_type=KEY_TYPE_SIGNING_SEED,
            secret_label="signing key",
        )
        try:
            _require_replacement_payloads(resolution, secret_label="signing key")
        except ValueError as exc:
            blockers.append(blocking_issue("SIGNING_KEY_REPLACEMENT_NOT_READY", str(exc)))
    return blockers


def _inspect_replacement_capabilities(
    *,
    args: ReplacementRecoveryRequest,
    recovery: RecoveryInspection,
    manifest: BackupManifest | None,
    signing_key_satisfied: bool,
    blocking_issues: list[dict[str, Any]],
) -> dict[str, bool]:
    blocker_codes = {
        str(issue.get("code"))
        for issue in blocking_issues
        if isinstance(issue, dict) and issue.get("code") is not None
    }
    passphrase_ready = (
        recovery.auth_payload is not None and recovery.unlock.satisfied and manifest is not None
    )
    signing_key_ready = passphrase_ready and signing_key_satisfied
    return {
        "can_replacement_passphrase_shards": passphrase_ready
        and args.create_passphrase_shards
        and not bool(blocker_codes & _PASSPHRASE_REPLACEMENT_BLOCKER_CODES),
        "can_replacement_signing_key_shards": signing_key_ready
        and args.create_signing_key_shards
        and not bool(blocker_codes & _SIGNING_KEY_REPLACEMENT_BLOCKER_CODES),
    }


def _raise_extension_recovery_error(exc: ExtensionRecoveryError) -> NoReturn:
    raise ApiCommandError(code=exc.code, message=str(exc), details=exc.details) from exc


def _recover_replacement_chain(
    plan: RecoveryPlan,
    *,
    debug: bool,
    allow_stale_head: bool = False,
) -> ChainRecoveryResult:
    try:
        chain = recover_chain_entries(plan, debug=debug)
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


def _validate_replacement_args(
    args: ReplacementRecoveryRequest, *, require_output_configuration: bool = True
) -> None:
    if (
        require_output_configuration
        and not args.create_passphrase_shards
        and not args.create_signing_key_shards
    ):
        raise ValueError("replacement recovery must create at least one shard document type")
    if (
        require_output_configuration
        and args.passphrase_replacement_count is not None
        and not args.create_passphrase_shards
    ):
        raise ValueError(
            "cannot request passphrase replacement shards when passphrase output is off"
        )
    if (
        require_output_configuration
        and args.signing_key_replacement_count is not None
        and not args.create_signing_key_shards
    ):
        raise ValueError(
            "cannot request replacement signing-key shards when signing-key output is off"
        )
    _validate_replacement_counts(args, require_output_configuration=require_output_configuration)


def _validate_replacement_counts(
    args: ReplacementRecoveryRequest, *, require_output_configuration: bool
) -> None:
    if args.passphrase_replacement_count is not None and args.passphrase_replacement_count < 1:
        raise ValueError("passphrase replacement count must be >= 1")
    if args.signing_key_replacement_count is not None and args.signing_key_replacement_count < 1:
        raise ValueError("signing key replacement count must be >= 1")
    if (
        require_output_configuration
        and args.passphrase_replacement_count is not None
        and not _has_existing_shard_inputs(
            args.shard_text_files,
            args.shard_payload_files,
            args.shard_scan_paths,
        )
    ):
        raise ValueError("passphrase shard replacement requires existing passphrase shard inputs")
    if (
        require_output_configuration
        and args.signing_key_replacement_count is not None
        and not _has_existing_shard_inputs(
            args.signing_key_shard_text_files,
            args.signing_key_shard_payload_files,
            args.signing_key_shard_scan_paths,
        )
    ):
        raise ValueError("signing-key shard replacement requires existing signing-key shard inputs")
    _recovery_request_for_replacement(args)
    validate_quorum_pair(
        args.shard_threshold,
        args.shard_count,
        pair_label="--shard-threshold and --shard-count",
        required=(
            require_output_configuration
            and args.create_passphrase_shards
            and args.passphrase_replacement_count is None
        ),
    )
    validate_quorum_pair(
        args.signing_key_shard_threshold,
        args.signing_key_shard_count,
        label="signing-key shard",
        pair_label=("--signing-key-shard-threshold and --signing-key-shard-count"),
        required=False,
    )
    if require_output_configuration and args.create_signing_key_shards:
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
) -> ReplacementRecoveryOperationResult:
    chain = _recover_replacement_chain(
        plan,
        debug=debug,
        allow_stale_head=args.allow_stale_head,
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
    sign_pub = derive_public_key(sign_priv)
    if sign_pub != plan.auth_payload.sign_pub:
        raise ValueError("signing key does not match the authenticated backup")

    passphrase_resolution, shard_payloads = _create_passphrase_output(
        plan, args, passphrase_shard_frames, sign_priv, sign_pub
    )
    signing_resolution, signing_key_payloads = _create_signing_key_output(
        plan, args, signing_key_frames, sign_priv, sign_pub
    )
    emit_phase(phase="output", label="Preparing replacement destination")
    output_dir = _ensure_replacement_output_dir(
        args.output_dir,
        plan.doc_id.hex(),
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
                "signing_key_source": signing_key_source,
            },
        )
        shard_paths, signing_key_shard_paths = _render_replacement_documents(
            shard_payloads,
            signing_key_payloads,
            context=ShardRenderContext(
                doc_id=plan.doc_id,
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
        doc_id=plan.doc_id,
        doc_hash=plan.doc_hash,
        output_dir=output_dir,
        shard_paths=final_shard_paths,
        signing_key_shard_paths=final_signing_key_shard_paths,
        signing_key_source=signing_key_source,
        notes=notes,
        selected_extension_index=chain.selected_extension_index,
        selected_extension_doc_hash=chain.selected_extension_doc_hash,
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
    plan: RecoveryPlan,
    args: ReplacementRecoveryRequest,
    signing_key_frames: list[Frame],
    sign_priv: bytes,
    sign_pub: bytes,
) -> tuple[_ReplacementShardResolution, list[ShardPayload]]:
    signing_resolution = _ReplacementShardResolution()
    assert plan.auth_payload is not None
    signing_key_payloads: list[ShardPayload] = []
    if args.create_signing_key_shards:
        if args.signing_key_replacement_count is not None:
            signing_resolution = _replacement_payloads_from_frames(
                signing_key_frames,
                doc_id=plan.doc_id,
                doc_hash=plan.doc_hash,
                sign_pub=plan.auth_payload.sign_pub,
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
                doc_hash=plan.doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )

    return signing_resolution, signing_key_payloads


def _create_passphrase_output(
    plan: RecoveryPlan,
    args: ReplacementRecoveryRequest,
    passphrase_shard_frames: list[Frame],
    sign_priv: bytes,
    sign_pub: bytes,
) -> tuple[_ReplacementShardResolution, list[ShardPayload]]:
    passphrase_resolution = _ReplacementShardResolution()
    assert plan.auth_payload is not None
    shard_payloads: list[ShardPayload] = []
    if args.create_passphrase_shards:
        if args.passphrase_replacement_count is not None:
            passphrase_resolution = _replacement_payloads_from_frames(
                passphrase_shard_frames,
                doc_id=plan.doc_id,
                doc_hash=plan.doc_hash,
                sign_pub=plan.auth_payload.sign_pub,
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
                plan.passphrase,
                threshold=passphrase_sharding.threshold,
                shares=passphrase_sharding.shares,
                doc_hash=plan.doc_hash,
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


def _raise_if_under_quorum_replacement_inputs(
    resolution: _ReplacementShardResolution,
    *,
    secret_label: str,
) -> None:
    if not resolution.under_quorum:
        return
    threshold = cast(int, resolution.threshold)
    raise ValueError(
        f"cannot evaluate compatible replacement {secret_label} shards: "
        f"need at least {threshold} validated shard(s), got {resolution.provided_count}; "
        f"provide a full quorum or remove existing {secret_label} shard inputs to create a "
        "fresh set"
        f"{_legacy_replacement_resolution_hint(resolution, secret_label=secret_label)}"
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
