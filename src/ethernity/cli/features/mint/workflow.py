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

"""Mint fresh shard documents for an existing backup."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from ethernity.artifacts.publish import create_sibling_staging_dir
from ethernity.cli.features.backup.execution import (
    _layout_debug_json_path,
    _render_shard,
)
from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    resolve_auth_payload,
    signing_seed_from_shard_frames,
    validated_shard_payloads_from_frames,
)
from ethernity.cli.features.recover.planning import (
    RecoveryInspection,
    RecoveryPlan,
    _extra_auth_frames_from_args,
    _frames_from_args,
    _shard_frames_from_args,
    build_recovery_plan,
    inspect_recovery_inputs,
    validate_recover_args,
)
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.events import EventSink, emit_phase, emit_progress, event_session
from ethernity.cli.shared.inspection import blocking_issue_from_exception
from ethernity.cli.shared.io.outputs import (
    _commit_prepared_output_dir,
    _discard_prepared_output_dir,
    _ensure_directory,
)
from ethernity.cli.shared.ndjson import ApiCommandError
from ethernity.cli.shared.types import MintArgs, MintResult, RecoverArgs
from ethernity.config import apply_render_style, load_app_config
from ethernity.core.models import ShardingConfig
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    LEGACY_SHARD_VERSION,
    ShardPayload,
    decode_shard_payload,
    mint_replacement_shards,
    split_passphrase,
    split_signing_seed,
)
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import Frame
from ethernity.extensions.chain import (
    reconstruct_authenticated_latest_logical_state,
    validate_authenticated_extension_chain,
)
from ethernity.extensions.errors import ExtensionRecoveryError
from ethernity.extensions.recovery import (
    decode_imported_extension_link,
    decode_root_manifest,
    recover_chain_entries,
    validate_expected_recovery_head,
    validate_root_manifest_authority,
)
from ethernity.formats.envelope_codec import decode_any_envelope, decode_envelope
from ethernity.formats.envelope_types import EnvelopeManifest
from ethernity.formats.extension_envelope import ExtensionEnvelope
from ethernity.render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ethernity.render.layout_debug import resolve_layout_debug_dir
from ethernity.render.service import RenderService
from ethernity.render.types import RenderLineage

MAX_SHARDS = 255
_UNSET = object()


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
class _MintExtensionCandidate:
    document: Any
    envelope: ExtensionEnvelope


@dataclass(frozen=True)
class _MintInputState:
    config: Any
    recover_args: RecoverArgs
    frames: tuple[Frame, ...]
    extra_auth_frames: tuple[Frame, ...]
    shard_frames: tuple[Frame, ...]
    shard_fallback_files: tuple[str, ...]
    shard_payloads_file: tuple[str, ...]
    shard_scan: tuple[str, ...]
    signing_key_frames: tuple[Frame, ...]
    input_label: str | None
    input_detail: str | None
    root_dir: str | None


@dataclass(frozen=True)
class MintInspectionState:
    recovery: RecoveryInspection
    manifest: EnvelopeManifest | None
    source_summary: dict[str, object] | None
    selected_extension_index: int | None
    selected_extension_doc_hash: str | None
    signing_key_frame_count: int
    signing_key_validated_shard_count: int
    signing_key_required_threshold: int | None
    signing_key_satisfied: bool
    signing_key_source: str | None
    mint_capabilities: dict[str, bool]
    blocking_issues: tuple[dict[str, Any], ...]


_PASSPHRASE_MINT_BLOCKER_CODES = frozenset({"PASSPHRASE_REPLACEMENT_NOT_READY"})
_SIGNING_KEY_MINT_BLOCKER_CODES = frozenset({"SIGNING_KEY_REPLACEMENT_NOT_READY"})


def run_mint_command(args: MintArgs, *, debug: bool = False) -> int:
    """Mint fresh shard documents from an existing backup."""

    from ethernity.cli.shared.ui.summary import print_mint_summary

    result = execute_mint(args, debug=debug)
    print_mint_summary(result, quiet=args.quiet)
    _print_completion_actions(result, quiet=args.quiet)
    return 0


def execute_mint(
    args: MintArgs,
    *,
    debug: bool = False,
    event_sink: EventSink | None = None,
) -> MintResult:
    """Mint fresh shard documents from an existing backup and return the result."""

    with event_session(event_sink):
        emit_phase(phase="plan", label="Resolving mint inputs")
        state = _load_mint_input_state(args)
        shard_frames = list(state.shard_frames)
        plan = _build_recovery_plan_for_mint(args, state, passphrase_shard_frames=shard_frames)
        if plan.auth_payload is None:
            raise ApiCommandError(
                code=api_codes.AUTH_REQUIRED,
                message="minting requires an authenticated backup input with an AUTH payload",
            )

        emit_progress(
            phase="plan",
            current=1,
            total=1,
            unit="step",
            details={
                "input_label": state.input_label,
                "input_detail": state.input_detail,
                "main_frame_count": len(plan.main_frames),
                "auth_frame_count": len(plan.auth_frames),
                "shard_frame_count": len(shard_frames),
                "signing_key_shard_frame_count": len(state.signing_key_frames),
            },
        )

        emit_phase(phase="mint", label="Generating minted shard payloads")
        return _mint_from_plan(
            plan=plan,
            config=state.config,
            args=args,
            passphrase_shard_frames=shard_frames,
            signing_key_frames=list(state.signing_key_frames),
            manifest_signing_seed=_UNSET,
            debug=debug,
        )


def inspect_mint_inputs(args: MintArgs, *, debug: bool = False) -> MintInspectionState:
    state = _load_mint_input_state(args, require_output_configuration=False)
    recovery_shard_frames, recovery_shard_fallback_files, recovery_shard_payloads_file = (
        _recovery_shard_inputs_for_plan(
            passphrase=args.passphrase,
            shard_frames=list(state.shard_frames),
            shard_fallback_files=list(state.shard_fallback_files),
            shard_payloads_file=list(state.shard_payloads_file),
        )
    )
    plan = _try_build_recovery_plan_for_mint(
        args,
        state,
        passphrase_shard_frames=list(state.shard_frames),
    )
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
        recovery = _mint_recovery_inspection_with_plan_shard_unlock(recovery, plan)

    blocking_issues = [dict(item) for item in recovery.blocking_issues]
    if recovery.auth_payload is None:
        _append_unique_blocking_issue(
            blocking_issues,
            _mint_blocking_issue(
                "AUTH_REQUIRED",
                "minting requires an authenticated backup input with an AUTH payload",
            ),
        )

    if plan is None and recovery.auth_payload is not None and recovery.unlock.satisfied:
        plan = _try_build_recovery_plan_for_mint(
            args,
            state,
            passphrase_shard_frames=list(state.shard_frames),
        )
    target_plan = plan
    selected_extension_index: int | None = None
    selected_extension_doc_hash: str | None = None
    chain_target_trusted = True
    if plan is not None:
        try:
            target_plan = _resolve_mint_chain_target(
                plan,
                quiet=args.quiet,
                debug=debug,
                allow_stale_head=args.allow_stale_head,
            )
            recovery = _mint_recovery_inspection_with_target(recovery, target_plan)
        except Exception as exc:
            chain_target_trusted = False
            _append_unique_blocking_issue(
                blocking_issues,
                dict(
                    blocking_issue_from_exception(
                        exc,
                        fallback_code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                        fallback_details={"stage": "replay"},
                    )
                ),
            )

    manifest: EnvelopeManifest | None = None
    source_summary: dict[str, object] | None = None
    if (
        chain_target_trusted
        and recovery.unlock.satisfied
        and recovery.unlock.resolved_passphrase is not None
    ):
        if plan is not None and plan.import_documents:
            try:
                chain = recover_chain_entries(plan, quiet=True, debug=debug)
                manifest = chain.manifest
                selected_extension_index = chain.selected_extension_index
                selected_extension_doc_hash = chain.selected_extension_doc_hash
                source_summary = _mint_source_summary(manifest)
            except Exception as exc:
                _append_unique_blocking_issue(
                    blocking_issues,
                    dict(
                        blocking_issue_from_exception(
                            exc,
                            fallback_code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                            fallback_details={"stage": "replay"},
                        )
                    ),
                )
        else:
            try:
                ciphertext = recovery.ciphertext
                passphrase = recovery.unlock.resolved_passphrase
                if target_plan is not None:
                    ciphertext = target_plan.ciphertext
                    passphrase = target_plan.passphrase
                plaintext = decrypt_bytes(
                    ciphertext,
                    passphrase=passphrase,
                    debug=debug,
                )
                manifest, _payload = decode_envelope(plaintext)
                source_summary = _mint_source_summary(manifest)
            except Exception as exc:
                _append_unique_blocking_issue(
                    blocking_issues,
                    _mint_blocking_issue("UNLOCK_FAILED", str(exc), details={"stage": "decrypt"}),
                )

    (
        signing_key_validated_shard_count,
        signing_key_required_threshold,
        signing_key_satisfied,
        signing_key_source,
        signing_key_issues,
    ) = _inspect_mint_signing_key_state(
        manifest=manifest,
        recovery=recovery,
        signing_key_frames=list(state.signing_key_frames),
    )
    _extend_unique_blocking_issues(blocking_issues, signing_key_issues)
    _extend_unique_blocking_issues(
        blocking_issues,
        _inspect_mint_replacement_blockers(
            args=args,
            recovery=recovery,
            passphrase_shard_frames=list(state.shard_frames),
            signing_key_frames=list(state.signing_key_frames),
        ),
    )

    mint_capabilities = _inspect_mint_capabilities(
        args=args,
        recovery=recovery,
        manifest=manifest,
        signing_key_satisfied=signing_key_satisfied,
        blocking_issues=blocking_issues,
    )
    return MintInspectionState(
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
        mint_capabilities=mint_capabilities,
        blocking_issues=tuple(blocking_issues),
    )


def _build_recovery_plan_for_mint(
    args: MintArgs,
    state: _MintInputState,
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
        root_dir=None,
        extension_index=args.extension_index,
        extension_doc_hash=args.extension_doc_hash,
        expected_head_doc_hash=args.expected_head_doc_hash,
        args=state.recover_args,
        quiet=args.quiet,
    )


def _try_build_recovery_plan_for_mint(
    args: MintArgs,
    state: _MintInputState,
    *,
    passphrase_shard_frames: list[Frame],
) -> RecoveryPlan | None:
    if not (args.passphrase or passphrase_shard_frames):
        return None
    try:
        return _build_recovery_plan_for_mint(
            args,
            state,
            passphrase_shard_frames=passphrase_shard_frames,
        )
    except Exception:
        return None


def _mint_recovery_inspection_with_target(
    recovery: RecoveryInspection,
    target_plan: Any,
) -> RecoveryInspection:
    return replace(
        recovery,
        ciphertext=target_plan.ciphertext,
        doc_id=target_plan.doc_id,
        doc_hash=target_plan.doc_hash,
        auth_payload=target_plan.auth_payload,
        auth_status=target_plan.auth_status,
    )


def _mint_recovery_inspection_with_plan_shard_unlock(
    recovery: RecoveryInspection,
    plan: RecoveryPlan,
) -> RecoveryInspection:
    shard_payloads = _mint_passphrase_shard_payloads_for_inspection(plan.shard_frames)
    if not shard_payloads:
        return recovery
    unique_share_indexes = {payload.share_index for payload in shard_payloads}
    first_payload = shard_payloads[0]
    return replace(
        recovery,
        shard_frames=tuple(plan.shard_frames),
        shard_fallback_files=tuple(plan.shard_fallback_files),
        shard_payloads_file=tuple(plan.shard_payloads_file),
        shard_scan=tuple(plan.shard_scan),
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
    )


def _mint_passphrase_shard_payloads_for_inspection(
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


def _mint_blocking_issue(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details or {},
    }


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


def _extend_unique_blocking_issues(
    blocking_issues: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    for issue in issues:
        _append_unique_blocking_issue(blocking_issues, issue)


def _mint_source_summary(manifest: EnvelopeManifest) -> dict[str, object]:
    return {
        "format_version": manifest.format_version,
        "input_origin": manifest.input_origin,
        "input_roots": list(manifest.input_roots),
        "sealed": manifest.sealed,
        "payload_codec": manifest.payload_codec,
        "payload_raw_len": manifest.payload_raw_len,
        "file_count": len(manifest.files),
    }


def _load_mint_input_state(
    args: MintArgs,
    *,
    require_output_configuration: bool = True,
) -> _MintInputState:
    _validate_mint_args(args, require_output_configuration=require_output_configuration)
    config = load_app_config(args.config, paper_size=args.paper)
    config = apply_render_style(config, args.design)
    recover_args = _recover_args_from_mint_args(args)
    frames: list[Frame]
    input_label: str | None
    input_detail: str | None
    root_dir: str | None = None
    if args.frames:
        frames = list(args.frames)
        input_label = args.input_label or "Backup recovery input"
        input_detail = args.input_detail
    else:
        frames_result = _frames_from_args(
            recover_args,
            allow_unsigned=False,
            quiet=args.quiet,
        )
        if len(frames_result) == 3:
            frames, input_label, input_detail = frames_result
        else:
            frames, input_label, input_detail, detected_root_dir = frames_result
            root_dir = None if detected_root_dir is None else str(detected_root_dir)
    extra_auth_frames = _extra_auth_frames_from_args(
        recover_args,
        allow_unsigned=False,
        quiet=args.quiet,
    )
    shard_frames, shard_fallback_files, shard_payloads_file, shard_scan = _shard_frames_from_args(
        recover_args,
        quiet=args.quiet,
    )
    signing_key_frames = _signing_key_shard_frames_from_args(args, quiet=args.quiet)
    return _MintInputState(
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
        root_dir=root_dir,
    )


def _inspect_mint_signing_key_state(
    *,
    manifest: EnvelopeManifest | None,
    recovery: RecoveryInspection,
    signing_key_frames: list[Frame],
) -> tuple[int, int | None, bool, str | None, list[dict[str, Any]]]:
    if manifest is None:
        return 0, None, False, None, []
    if manifest.signing_seed is not None:
        return 0, None, True, "embedded signing seed", []

    source = "signing authority shards"
    if recovery.auth_payload is None:
        return (
            0,
            None,
            False,
            source,
            [
                _mint_blocking_issue(
                    "AUTH_REQUIRED",
                    "minting requires an authenticated backup input with an AUTH payload",
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
                _mint_blocking_issue(
                    "SIGNING_KEY_SHARDS_REQUIRED",
                    (
                        "backup is sealed; provide signing authority shard inputs "
                        "to mint new shard documents"
                    ),
                )
            ],
        )
    try:
        payloads = validated_shard_payloads_from_frames(
            signing_key_frames,
            expected_doc_id=recovery.doc_id,
            expected_doc_hash=recovery.doc_hash,
            expected_sign_pub=recovery.auth_payload.sign_pub,
            allow_unsigned=False,
            key_type=KEY_TYPE_SIGNING_SEED,
            secret_label="signing key",
        )
    except InsufficientShardError as exc:
        return (
            exc.provided_count,
            exc.threshold,
            False,
            source,
            [
                _mint_blocking_issue(
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
            [_mint_blocking_issue("SIGNING_KEY_SHARDS_INVALID", str(exc))],
        )
    return (
        len(payloads),
        payloads[0].threshold if payloads else None,
        True,
        source,
        [],
    )


def _inspect_mint_replacement_blockers(
    *,
    args: MintArgs,
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
            blockers.append(_mint_blocking_issue("PASSPHRASE_REPLACEMENT_NOT_READY", str(exc)))
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
            blockers.append(_mint_blocking_issue("SIGNING_KEY_REPLACEMENT_NOT_READY", str(exc)))
    return blockers


def _inspect_mint_capabilities(
    *,
    args: MintArgs,
    recovery: RecoveryInspection,
    manifest: EnvelopeManifest | None,
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
        "can_mint_passphrase_shards": passphrase_ready
        and args.mint_passphrase_shards
        and not bool(blocker_codes & _PASSPHRASE_MINT_BLOCKER_CODES),
        "can_mint_signing_key_shards": signing_key_ready
        and args.mint_signing_key_shards
        and not bool(blocker_codes & _SIGNING_KEY_MINT_BLOCKER_CODES),
    }


def _raise_extension_recovery_api_error(exc: ExtensionRecoveryError) -> None:
    raise ApiCommandError(code=exc.code, message=str(exc), details=exc.details) from exc


def _validate_expected_mint_recovery_head(
    plan: Any,
    *,
    selected_extension_index: int | None,
    selected_extension_doc_hash: str | None,
) -> None:
    try:
        validate_expected_recovery_head(
            plan,
            selected_extension_index=selected_extension_index,
            selected_extension_doc_hash=selected_extension_doc_hash,
        )
    except ExtensionRecoveryError as exc:
        _raise_extension_recovery_api_error(exc)


def _resolve_mint_chain_target(
    plan: Any,
    *,
    quiet: bool,
    debug: bool,
    allow_stale_head: bool = False,
    root_decoded: tuple[EnvelopeManifest, bytes] | None = None,
) -> Any:
    auth_payload = getattr(plan, "auth_payload", None)
    passphrase = getattr(plan, "passphrase", None)
    import_documents = getattr(plan, "import_documents", ())
    requested_index = getattr(plan, "extension_index", None)
    requested_doc_hash = getattr(plan, "extension_doc_hash", None)
    _validate_mint_extension_selector(requested_index, requested_doc_hash)
    requested_doc_hash_bytes = (
        _parse_mint_extension_doc_hash(requested_doc_hash)
        if requested_doc_hash is not None
        else None
    )
    if requested_index == 0:
        _validate_expected_mint_recovery_head(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        _require_mint_head_acknowledgement(
            plan,
            allow_stale_head=allow_stale_head,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
            has_imported_extensions=len(import_documents) > 1,
        )
        return replace(plan, extension_index=None, extension_doc_hash=None, import_documents=())

    explicit_extension_selection = requested_index is not None or requested_doc_hash is not None
    if len(import_documents) <= 1 or auth_payload is None or passphrase is None:
        if explicit_extension_selection:
            _raise_missing_mint_extension_target(requested_index, requested_doc_hash)
        _validate_expected_mint_recovery_head(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        return plan

    documents_by_doc_hash = {document.doc_hash: document for document in import_documents}
    root_manifest: EnvelopeManifest | None = None
    root_payload: bytes | None = None
    root_sign_pub: bytes | None = None
    try:
        if root_decoded is None:
            root_manifest, root_payload = decode_root_manifest(
                ciphertext=plan.ciphertext,
                passphrase=passphrase,
                debug=debug,
            )
        else:
            root_manifest, root_payload = root_decoded
        root_sign_pub = validate_root_manifest_authority(
            root_manifest,
            auth_payload,
            doc_hash=plan.doc_hash,
        )
    except ApiCommandError:
        raise
    except ExtensionRecoveryError as exc:
        _raise_extension_recovery_api_error(exc)
    except ValueError as exc:
        raise ValueError(f"imported extension chain could not be trusted: {exc}") from exc

    if root_manifest is None or root_payload is None:
        raise AssertionError("root manifest decoding did not return manifest data")

    if root_sign_pub is None:
        if _mint_documents_include_extension_for_root(
            plan,
            import_documents=import_documents,
            passphrase=passphrase,
            debug=debug,
        ):
            raise ValueError(
                "imported extension chain could not be trusted: "
                "extension minting requires an unsealed root signing authority"
            )
        if explicit_extension_selection:
            _raise_missing_mint_extension_target(requested_index, requested_doc_hash)
        _validate_expected_mint_recovery_head(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        return plan

    candidates = _decode_mint_extension_candidates(
        plan,
        import_documents=tuple(import_documents),
        passphrase=passphrase,
        root_sign_pub=root_sign_pub,
        requested_doc_hash=requested_doc_hash_bytes,
        fail_on_root_authority_errors=not explicit_extension_selection,
        quiet=quiet,
        debug=debug,
    )
    _reject_conflicting_mint_extension_indices(candidates)
    candidates = _select_mint_extension_candidates(
        candidates,
        requested_index=requested_index,
        requested_doc_hash=requested_doc_hash,
    )
    decoded_links = []
    for candidate in candidates:
        try:
            decoded_links.append(
                decode_imported_extension_link(
                    candidate.document,
                    passphrase=passphrase,
                    expected_sign_pub=root_sign_pub,
                    quiet=quiet,
                    debug=debug,
                )
            )
        except ValueError as exc:
            raise ValueError(f"imported extension chain could not be trusted: {exc}") from exc
    if not decoded_links:
        _validate_expected_mint_recovery_head(
            plan,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
        )
        return replace(plan, extension_index=None, extension_doc_hash=None, import_documents=())
    decoded_links.sort(key=lambda item: item.link.document.header.index)
    try:
        validate_authenticated_extension_chain(
            root_doc_hash=plan.doc_hash,
            expected_sign_pub=root_sign_pub,
            extensions=tuple(item.link for item in decoded_links),
        )
        reconstruct_authenticated_latest_logical_state(
            root_manifest,
            root_payload,
            root_doc_hash=plan.doc_hash,
            expected_sign_pub=root_sign_pub,
            extensions=tuple(item.link for item in decoded_links),
        )
    except ValueError as exc:
        raise ValueError(f"imported extension chain could not be trusted: {exc}") from exc
    latest_decoded = decoded_links[-1]
    latest = documents_by_doc_hash[latest_decoded.link.doc_hash]
    _validate_expected_mint_recovery_head(
        plan,
        selected_extension_index=latest_decoded.link.document.header.index,
        selected_extension_doc_hash=latest.doc_hash.hex(),
    )
    _require_mint_head_acknowledgement(
        plan,
        allow_stale_head=allow_stale_head,
        selected_extension_index=latest_decoded.link.document.header.index,
        selected_extension_doc_hash=latest.doc_hash.hex(),
        has_imported_extensions=True,
    )

    return replace(
        plan,
        ciphertext=latest.ciphertext,
        doc_id=latest.doc_id,
        doc_hash=latest.doc_hash,
        auth_payload=latest_decoded.auth_payload,
        auth_status=latest_decoded.auth_status,
        extension_index=latest_decoded.link.document.header.index,
        extension_doc_hash=latest.doc_hash.hex(),
        import_documents=(),
    )


def _require_mint_head_acknowledgement(
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
        code=api_codes.RECOVERY_HEAD_UNTRUSTED,
        message=(
            "mint cannot prove the supplied recovery set is the latest chain state; "
            "provide --expected-head-doc-hash or pass --allow-stale-head to acknowledge this risk"
        ),
        details={
            "stage": "selection",
            "validated_head_index": validated_head_index,
            "validated_head_doc_hash": validated_head_doc_hash,
            "freshness_scope": "supplied_carriers_only",
            "required_acknowledgement": "--allow-stale-head",
        },
    )


def _validate_mint_extension_selector(
    requested_index: int | None,
    requested_doc_hash: str | None,
) -> None:
    if requested_index is not None and requested_doc_hash is not None:
        raise ValueError("use either --extension-index or --extension-doc-hash, not both")
    if requested_index is not None and (isinstance(requested_index, bool) or requested_index < 0):
        raise ValueError("--extension-index must be >= 0")
    if requested_doc_hash is not None:
        _parse_mint_extension_doc_hash(requested_doc_hash)


def _raise_missing_mint_extension_target(
    requested_index: int | None,
    requested_doc_hash: str | None,
) -> None:
    if requested_index is not None:
        raise ValueError(f"extension index {requested_index} was not found")
    if requested_doc_hash is not None:
        _parse_mint_extension_doc_hash(requested_doc_hash)
        raise ValueError(f"extension doc_hash {requested_doc_hash.strip().lower()} was not found")


def _parse_mint_extension_doc_hash(value: str) -> bytes:
    normalized = value.strip().lower()
    try:
        requested_bytes = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError("--extension-doc-hash must be lowercase hex") from exc
    if len(requested_bytes) != 32:
        raise ValueError("--extension-doc-hash must be a 32-byte hex value")
    return requested_bytes


def _decode_mint_extension_candidates(
    plan: Any,
    *,
    import_documents: tuple[Any, ...],
    passphrase: str,
    root_sign_pub: bytes,
    fail_on_root_authority_errors: bool,
    quiet: bool,
    debug: bool,
    requested_doc_hash: bytes | None = None,
) -> tuple[_MintExtensionCandidate, ...]:
    candidates: list[_MintExtensionCandidate] = []
    seen_doc_hashes = {plan.doc_hash}
    for document in import_documents:
        if document.doc_hash in seen_doc_hashes:
            continue
        _raise_if_mint_doc_id_collision(document, plan)
        selected_doc_hash = (
            requested_doc_hash is not None and document.doc_hash == requested_doc_hash
        )
        fail_on_document_errors = fail_on_root_authority_errors or selected_doc_hash
        try:
            auth_payload, _auth_status = resolve_auth_payload(
                list(document.auth_frames),
                doc_id=document.doc_id,
                doc_hash=document.doc_hash,
                allow_unsigned=False,
                require_auth=True,
                quiet=quiet,
            )
        except ValueError as exc:
            if fail_on_document_errors:
                raise ValueError(
                    _mint_extension_trust_error(
                        document,
                        f"imported extension AUTH could not be trusted: {exc}",
                        selected=selected_doc_hash,
                    )
                ) from exc
            continue
        if auth_payload is None or auth_payload.sign_pub != root_sign_pub:
            if selected_doc_hash:
                raise ValueError(
                    _mint_extension_trust_error(
                        document,
                        "imported extension AUTH signing key does not match root authority",
                        selected=True,
                    )
                )
            continue
        try:
            plaintext = decrypt_bytes(document.ciphertext, passphrase=passphrase, debug=debug)
            version, decoded = decode_any_envelope(plaintext)
        except Exception as exc:
            if fail_on_document_errors:
                raise ValueError(
                    _mint_extension_trust_error(
                        document,
                        f"imported root-authority document could not be trusted: {exc}",
                        selected=selected_doc_hash,
                    )
                ) from exc
            continue
        if version != 2 or not isinstance(decoded, ExtensionEnvelope):
            if fail_on_document_errors:
                raise ValueError(
                    _mint_extension_trust_error(
                        document,
                        (
                            "imported root-authority document could not be trusted: "
                            "imported document did not decode as an extension envelope"
                        ),
                        selected=selected_doc_hash,
                    )
                )
            continue
        if decoded.header.root_doc_hash != plan.doc_hash:
            if fail_on_document_errors:
                raise ValueError(
                    _mint_extension_trust_error(
                        document,
                        "imported root-authority extension targets a different root backup",
                        selected=selected_doc_hash,
                    )
                )
            continue
        seen_doc_hashes.add(document.doc_hash)
        candidates.append(_MintExtensionCandidate(document=document, envelope=decoded))
    return tuple(sorted(candidates, key=lambda item: item.envelope.header.index))


def _mint_extension_trust_error(
    document: Any,
    message: str,
    *,
    selected: bool,
) -> str:
    if not selected:
        return message
    return f"selected extension doc_hash {document.doc_hash.hex()} could not be trusted: {message}"


def _reject_conflicting_mint_extension_indices(
    candidates: tuple[_MintExtensionCandidate, ...],
) -> None:
    by_index: dict[int, _MintExtensionCandidate] = {}
    for candidate in candidates:
        index = candidate.envelope.header.index
        existing = by_index.get(index)
        if existing is not None and existing.document.doc_hash != candidate.document.doc_hash:
            raise ValueError(
                f"content import contains multiple authenticated extensions for index {index}"
            )
        by_index[index] = candidate


def _select_mint_extension_candidates(
    candidates: tuple[_MintExtensionCandidate, ...],
    *,
    requested_index: int | None,
    requested_doc_hash: str | None,
) -> tuple[_MintExtensionCandidate, ...]:
    if requested_index is not None:
        if requested_index == 0:
            return ()
        if not any(candidate.envelope.header.index == requested_index for candidate in candidates):
            raise ValueError(f"extension index {requested_index} was not found")
        return tuple(
            candidate
            for candidate in candidates
            if candidate.envelope.header.index <= requested_index
        )
    if requested_doc_hash is not None:
        requested = _parse_mint_extension_doc_hash(requested_doc_hash)
        target_index = next(
            (
                candidate.envelope.header.index
                for candidate in candidates
                if candidate.document.doc_hash == requested
            ),
            None,
        )
        if target_index is None:
            raise ValueError(
                f"extension doc_hash {requested_doc_hash.strip().lower()} was not found"
            )
        return tuple(
            candidate for candidate in candidates if candidate.envelope.header.index <= target_index
        )
    return candidates


def _raise_if_mint_doc_id_collision(document: Any, plan: Any) -> None:
    if document.doc_id != plan.doc_id:
        return
    raise ValueError(
        "imported extension chain could not be trusted: "
        "content import contains a document whose doc_id collides with the selected root backup"
    )


def _mint_documents_include_extension_for_root(
    plan: Any,
    *,
    import_documents: tuple[Any, ...],
    passphrase: str,
    debug: bool,
) -> bool:
    for document in import_documents:
        if document.doc_hash == plan.doc_hash:
            continue
        _raise_if_mint_doc_id_collision(document, plan)
        if _mint_document_targets_current_root(
            document,
            passphrase=passphrase,
            root_doc_hash=plan.doc_hash,
            debug=debug,
        ):
            return True
    return False


def _mint_document_targets_current_root(
    document: Any,
    *,
    passphrase: str,
    root_doc_hash: bytes,
    debug: bool,
) -> bool:
    try:
        plaintext = decrypt_bytes(document.ciphertext, passphrase=passphrase, debug=debug)
        version, decoded = decode_any_envelope(plaintext)
    except Exception:
        return False
    return (
        version == 2
        and isinstance(decoded, ExtensionEnvelope)
        and decoded.header.root_doc_hash == root_doc_hash
    )


def _recover_args_from_mint_args(args: MintArgs) -> RecoverArgs:
    recover_args = RecoverArgs(
        config=args.config,
        paper=args.paper,
        fallback_file=args.fallback_file,
        payloads_file=args.payloads_file,
        scan=list(args.scan or []),
        passphrase=args.passphrase,
        shard_fallback_file=list(args.shard_fallback_file or []),
        shard_payloads_file=list(args.shard_payloads_file or []),
        shard_scan=list(args.shard_scan or []),
        shard_frames=list(args.shard_frames or []),
        auth_fallback_file=args.auth_fallback_file,
        auth_payloads_file=args.auth_payloads_file,
        extension_index=args.extension_index,
        extension_doc_hash=args.extension_doc_hash,
        output=None,
        allow_unsigned=False,
        assume_yes=True,
        quiet=args.quiet,
    )
    validate_recover_args(recover_args)
    return recover_args


def _validate_mint_args(args: MintArgs, *, require_output_configuration: bool = True) -> None:
    if (
        require_output_configuration
        and not args.mint_passphrase_shards
        and not args.mint_signing_key_shards
    ):
        raise ValueError("mint must create at least one shard document type")
    if (
        require_output_configuration
        and args.passphrase_replacement_count is not None
        and not args.mint_passphrase_shards
    ):
        raise ValueError(
            "cannot request passphrase replacement shards when passphrase output is off"
        )
    if (
        require_output_configuration
        and args.signing_key_replacement_count is not None
        and not args.mint_signing_key_shards
    ):
        raise ValueError(
            "cannot request signing authority replacement shards when signing authority output "
            "is off"
        )
    if args.passphrase_replacement_count is not None and args.passphrase_replacement_count < 1:
        raise ValueError("passphrase replacement count must be >= 1")
    if args.signing_key_replacement_count is not None and args.signing_key_replacement_count < 1:
        raise ValueError("signing key replacement count must be >= 1")
    if (
        require_output_configuration
        and args.passphrase_replacement_count is not None
        and not _has_existing_shard_inputs(
            args.shard_fallback_file,
            args.shard_payloads_file,
            args.shard_scan,
        )
    ):
        raise ValueError("passphrase replacement minting requires existing passphrase shard inputs")
    if (
        require_output_configuration
        and args.signing_key_replacement_count is not None
        and not _has_existing_shard_inputs(
            args.signing_key_shard_fallback_file,
            args.signing_key_shard_payloads_file,
            args.signing_key_shard_scan,
        )
    ):
        raise ValueError(
            "signing authority replacement minting requires existing signing authority shard inputs"
        )
    _recover_args_from_mint_args(args)
    _validate_quorum_pair(
        args.shard_threshold,
        args.shard_count,
        threshold_label="shard threshold",
        count_label="shard count",
        pair_label="--shard-threshold and --shard-count",
        required=(
            require_output_configuration
            and args.mint_passphrase_shards
            and args.passphrase_replacement_count is None
        ),
    )
    _validate_quorum_pair(
        args.signing_key_shard_threshold,
        args.signing_key_shard_count,
        threshold_label="signing authority shard threshold",
        count_label="signing authority shard count",
        pair_label=("--signing-key-shard-threshold and --signing-key-shard-count"),
        required=False,
    )
    if require_output_configuration and args.mint_signing_key_shards:
        if args.signing_key_replacement_count is not None:
            return
        has_explicit_signing_quorum = (
            args.signing_key_shard_threshold is not None
            and args.signing_key_shard_count is not None
        )
        has_passphrase_quorum = args.shard_threshold is not None and args.shard_count is not None
        if not has_explicit_signing_quorum and not has_passphrase_quorum:
            raise ValueError(
                "minting signing authority shards requires a shard quorum or an explicit "
                "signing authority shard quorum"
            )


def _validate_quorum_pair(
    threshold: int | None,
    count: int | None,
    *,
    threshold_label: str,
    count_label: str,
    pair_label: str,
    required: bool,
) -> None:
    if threshold is None and count is None:
        if required:
            raise ValueError(f"{pair_label} are required")
        return
    if threshold is None or count is None:
        raise ValueError(f"both {pair_label} are required")
    if threshold < 1:
        raise ValueError(f"{threshold_label} must be >= 1")
    if threshold > MAX_SHARDS:
        raise ValueError(f"{threshold_label} must be <= {MAX_SHARDS}")
    if count < threshold:
        raise ValueError(f"{count_label} must be >= {threshold_label}")
    if count > MAX_SHARDS:
        raise ValueError(f"{count_label} must be <= {MAX_SHARDS}")


def _has_existing_shard_inputs(
    fallback_files: list[str] | None,
    payload_files: list[str] | None,
    scan_paths: list[str] | None = None,
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


def _mint_from_plan(
    *,
    plan,
    config,
    args: MintArgs,
    passphrase_shard_frames: list[Frame],
    signing_key_frames: list[Frame],
    manifest_signing_seed: object,
    debug: bool,
) -> MintResult:
    target_plan = _resolve_mint_chain_target(
        plan,
        quiet=args.quiet,
        debug=debug,
        allow_stale_head=args.allow_stale_head,
    )
    if manifest_signing_seed is _UNSET:
        plaintext = decrypt_bytes(plan.ciphertext, passphrase=plan.passphrase, debug=debug)
        manifest, _payload = decode_envelope(plaintext)
        resolved_manifest_signing_seed = manifest.signing_seed
    else:
        resolved_manifest_signing_seed = cast(bytes | None, manifest_signing_seed)
    sign_priv, signing_key_source = _resolve_signing_authority(
        manifest_signing_seed=resolved_manifest_signing_seed,
        signing_key_frames=signing_key_frames,
        doc_id=target_plan.doc_id,
        doc_hash=target_plan.doc_hash,
        expected_sign_pub=target_plan.auth_payload.sign_pub,
    )
    sign_pub = derive_public_key(sign_priv)
    if sign_pub != target_plan.auth_payload.sign_pub:
        raise ValueError("signing authority does not match the authenticated backup")

    passphrase_resolution = _ReplacementShardResolution()
    signing_resolution = _ReplacementShardResolution()

    shard_payloads: list[ShardPayload] = []
    if args.mint_passphrase_shards:
        if args.passphrase_replacement_count is not None:
            passphrase_resolution = _replacement_payloads_from_frames(
                passphrase_shard_frames,
                doc_id=target_plan.doc_id,
                doc_hash=target_plan.doc_hash,
                sign_pub=target_plan.auth_payload.sign_pub,
                key_type=KEY_TYPE_PASSPHRASE,
                secret_label="passphrase",
            )
            _require_replacement_payloads(
                passphrase_resolution,
                secret_label="passphrase",
            )
            shard_payloads = mint_replacement_shards(
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
                target_plan.passphrase,
                threshold=passphrase_sharding.threshold,
                shares=passphrase_sharding.shares,
                doc_hash=target_plan.doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )

    signing_key_payloads: list[ShardPayload] = []
    if args.mint_signing_key_shards:
        if args.signing_key_replacement_count is not None:
            signing_resolution = _replacement_payloads_from_frames(
                signing_key_frames,
                doc_id=target_plan.doc_id,
                doc_hash=target_plan.doc_hash,
                sign_pub=target_plan.auth_payload.sign_pub,
                key_type=KEY_TYPE_SIGNING_SEED,
                secret_label="signing key",
            )
            _require_replacement_payloads(
                signing_resolution,
                secret_label="signing key",
            )
            signing_key_payloads = mint_replacement_shards(
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
                doc_hash=target_plan.doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )

    output_dir = _ensure_mint_output_dir(
        args.output_dir,
        target_plan.doc_id.hex(),
        existing_directory_is_parent=args.output_dir_existing_parent,
    )
    staging_output_dir = _prepare_mint_staging_dir(output_dir)
    layout_debug_dir = resolve_layout_debug_dir(
        args.layout_debug_dir,
        forbidden_dirs={
            "final output": output_dir,
            "staging output": staging_output_dir,
        },
    )
    render_service = RenderService(config)
    qr_payload_codec = config.cli_defaults.backup.qr_payload_codec
    lineage = RenderLineage(kind="minted_shard_set")
    total_documents = len(shard_payloads) + len(signing_key_payloads)
    rendered_documents = 0

    emit_progress(
        phase="mint",
        current=1,
        total=1,
        unit="step",
        details={
            "passphrase_shard_count": len(shard_payloads),
            "signing_key_shard_count": len(signing_key_payloads),
            "signing_key_source": signing_key_source,
        },
    )
    emit_phase(phase="render", label="Rendering minted shard documents")

    shard_paths: list[str] = []
    signing_key_shard_paths: list[str] = []
    try:
        for shard in sorted(shard_payloads, key=lambda item: item.share_index):
            shard_paths.append(
                _render_shard(
                    shard,
                    doc_id=target_plan.doc_id,
                    output_dir=staging_output_dir,
                    render_service=render_service,
                    filename_prefix="shard",
                    layout_debug_json_path=_layout_debug_json_path(
                        layout_debug_dir,
                        f"shard-{shard.share_index:02d}-of-{shard.share_count:02d}",
                    ),
                    qr_payload_codec=qr_payload_codec,
                    lineage=lineage,
                )
            )
            rendered_documents += 1
            emit_progress(
                phase="render",
                current=rendered_documents,
                total=total_documents,
                unit="documents",
                label=f"Rendered passphrase shard {shard.share_index} of {shard.share_count}",
                details={"path": shard_paths[-1], "kind": "shard_document"},
            )

        for shard in sorted(signing_key_payloads, key=lambda item: item.share_index):
            signing_key_shard_paths.append(
                _render_shard(
                    shard,
                    doc_id=target_plan.doc_id,
                    output_dir=staging_output_dir,
                    render_service=render_service,
                    filename_prefix="signing-key-shard",
                    doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
                    layout_debug_json_path=_layout_debug_json_path(
                        layout_debug_dir,
                        f"signing-key-shard-{shard.share_index:02d}-of-{shard.share_count:02d}",
                    ),
                    qr_payload_codec=qr_payload_codec,
                    lineage=lineage,
                )
            )
            rendered_documents += 1
            emit_progress(
                phase="render",
                current=rendered_documents,
                total=total_documents,
                unit="documents",
                label=f"Rendered signing-key shard {shard.share_index} of {shard.share_count}",
                details={
                    "path": signing_key_shard_paths[-1],
                    "kind": "signing_key_shard_document",
                },
            )
        _commit_prepared_output_dir(staging_output_dir, output_dir)
    except Exception:
        _discard_prepared_output_dir(staging_output_dir)
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

    return MintResult(
        doc_id=target_plan.doc_id,
        doc_hash=target_plan.doc_hash,
        output_dir=output_dir,
        shard_paths=final_shard_paths,
        signing_key_shard_paths=final_signing_key_shard_paths,
        signing_key_source=signing_key_source,
        notes=notes,
        selected_extension_index=getattr(target_plan, "extension_index", None),
        selected_extension_doc_hash=getattr(target_plan, "extension_doc_hash", None),
    )


def _signing_key_shard_frames_from_args(args: MintArgs, *, quiet: bool) -> list[Frame]:
    signing_key_frames = list(args.signing_key_shard_frames or [])
    fallback_files = list(args.signing_key_shard_fallback_file or [])
    payload_files = list(args.signing_key_shard_payloads_file or [])
    scan_files = list(args.signing_key_shard_scan or [])
    if not fallback_files and not payload_files and not scan_files:
        return signing_key_frames
    temp_args = RecoverArgs(
        shard_fallback_file=fallback_files,
        shard_payloads_file=payload_files,
        shard_frames=signing_key_frames,
        shard_scan=scan_files,
        quiet=quiet,
    )
    frames, _fallback_files, _payload_files, _scan_files = _shard_frames_from_args(
        temp_args,
        quiet=quiet,
    )
    return frames


def _resolve_signing_authority(
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
            code=api_codes.SIGNING_KEY_SHARDS_REQUIRED,
            message=(
                "backup is sealed; provide signing authority shard inputs to mint "
                "new shard documents"
            ),
        )
    signing_seed = signing_seed_from_shard_frames(
        signing_key_frames,
        expected_doc_id=doc_id,
        expected_doc_hash=doc_hash,
        expected_sign_pub=expected_sign_pub,
        allow_unsigned=False,
    )
    return signing_seed, "signing authority shards"


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
        payloads = validated_shard_payloads_from_frames(
            frames,
            expected_doc_id=doc_id,
            expected_doc_hash=doc_hash,
            expected_sign_pub=sign_pub,
            allow_unsigned=False,
            key_type=key_type,
            secret_label=secret_label,
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
    args: MintArgs,
) -> tuple[str, ...]:
    notes: list[str] = []
    if args.passphrase_replacement_count is not None and passphrase_resolution.uses_legacy_shards:
        notes.append(
            "Legacy v1 passphrase shards detected. Compatible replacements stay on v1; "
            "prefer minting a full new passphrase shard set to migrate to shard payload v2."
        )
    if args.signing_key_replacement_count is not None and signing_resolution.uses_legacy_shards:
        notes.append(
            "Legacy v1 signing authority shards detected. Compatible replacements stay on v1; "
            "prefer minting a full new signing authority shard set to migrate to shard payload v2."
        )
    return tuple(notes)


def _print_legacy_replacement_warning(notes: tuple[str, ...], *, quiet: bool) -> None:
    if quiet or not notes:
        return
    from ethernity.cli.shared.ui_api import console, panel

    console.print(
        panel(
            "Legacy shard advisory",
            "\n".join(f"- {note}" for note in notes),
            style="warning",
        )
    )


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
            f"cannot mint compatible replacement {secret_label} shards: "
            f"need at least {threshold} validated shard(s), got {resolution.provided_count}"
            f"{_legacy_replacement_resolution_hint(resolution, secret_label=secret_label)}"
        )
    raise ValueError(
        f"cannot mint compatible replacement {secret_label} shards: "
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
        f"provide a full quorum or remove existing {secret_label} shard inputs to mint a fresh set"
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
        f"so mint a fresh {secret_label} shard set to migrate to shard payload v2"
    )


def _resolve_signing_key_output_sharding(args: MintArgs) -> ShardingConfig:
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


def _ensure_mint_output_dir(
    output_dir: str | None,
    doc_id_hex: str,
    *,
    existing_directory_is_parent: bool = False,
) -> str:
    directory = output_dir or f"mint-{doc_id_hex}"
    resolved = Path(directory).expanduser()
    if existing_directory_is_parent and resolved.is_dir():
        resolved = resolved / f"mint-{doc_id_hex}"
    if resolved.exists():
        raise ValueError(
            f"output directory already exists: {resolved}; "
            "use a different --output-dir path or remove the existing directory"
        )
    _ensure_directory(resolved.parent, exist_ok=True)
    return str(resolved)


def _prepare_mint_staging_dir(output_dir: str) -> str:
    return str(create_sibling_staging_dir(output_dir))


def _print_completion_actions(result: MintResult, *, quiet: bool) -> None:
    if quiet:
        return
    from ethernity.cli.shared.ui_api import print_completion_panel

    actions = [f"Saved to {result.output_dir}"]
    if result.shard_paths:
        actions.append(f"Store {len(result.shard_paths)} fresh shard documents separately.")
    if result.signing_key_shard_paths:
        actions.append(
            "Store "
            f"{len(result.signing_key_shard_paths)} fresh signing authority shard documents "
            "separately."
        )
    actions.append("Verify the new shard documents before retiring any older set.")
    print_completion_panel("Mint complete", actions, quiet=quiet)
