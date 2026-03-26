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

import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from ethernity.cli.features.backup.execution import (
    _layout_debug_json_path,
    _render_shard,
    _resolve_layout_debug_dir,
)
from ethernity.cli.features.backup.wizard import _prompt_quorum_choice
from ethernity.cli.features.recover.input_collection import prompt_recovery_input_interactive
from ethernity.cli.features.recover.key_recovery import (
    InsufficientShardError,
    _signing_seed_from_shard_frames,
    _validated_shard_payloads_from_frames,
)
from ethernity.cli.features.recover.planning import (
    RecoveryInspection,
    _extra_auth_frames_from_args,
    _frames_from_args,
    _shard_frames_from_args,
    build_recovery_plan,
    inspect_recovery_inputs,
    validate_recover_args,
)
from ethernity.cli.features.recover.wizard import _load_shard_frames, _prompt_key_material
from ethernity.cli.shared.events import EventSink, emit_phase, emit_progress, event_session
from ethernity.cli.shared.io.outputs import (
    _commit_prepared_output_dir,
    _discard_prepared_output_dir,
    _ensure_directory,
)
from ethernity.cli.shared.recovery_prompts import _prompt_shard_inputs
from ethernity.cli.shared.types import MintArgs, MintResult, RecoverArgs
from ethernity.cli.shared.ui.summary import print_mint_summary
from ethernity.cli.shared.ui_api import (
    console,
    panel,
    print_completion_panel,
    prompt_choice,
    prompt_int,
    prompt_yes_no,
    ui_screen_mode,
    wizard_flow,
    wizard_stage,
)
from ethernity.config import apply_template_design, load_app_config
from ethernity.core.models import ShardingConfig
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    LEGACY_SHARD_VERSION,
    ShardPayload,
    mint_replacement_shards,
    split_passphrase,
    split_signing_seed,
)
from ethernity.crypto.signing import derive_public_key
from ethernity.encoding.framing import Frame
from ethernity.formats.envelope_codec import decode_envelope
from ethernity.formats.envelope_types import EnvelopeManifest
from ethernity.render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ethernity.render.service import RenderService

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


@dataclass(frozen=True)
class MintInspectionState:
    recovery: RecoveryInspection
    manifest: EnvelopeManifest | None
    source_summary: dict[str, object] | None
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
        recovery_shard_frames, recovery_shard_fallback_files, recovery_shard_payloads_file = (
            _recovery_shard_inputs_for_plan(
                passphrase=args.passphrase,
                shard_frames=shard_frames,
                shard_fallback_files=list(state.shard_fallback_files),
                shard_payloads_file=list(state.shard_payloads_file),
            )
        )
        plan = build_recovery_plan(
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
            args=state.recover_args,
            quiet=args.quiet,
        )
        if plan.auth_payload is None:
            raise ValueError("minting requires an authenticated backup input with an AUTH payload")

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
    recovery = inspect_recovery_inputs(
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
        quiet=args.quiet,
    )

    blocking_issues = [dict(item) for item in recovery.blocking_issues]
    if recovery.auth_payload is None:
        blocking_issues.append(
            _mint_blocking_issue(
                "AUTH_REQUIRED",
                "minting requires an authenticated backup input with an AUTH payload",
            )
        )

    manifest: EnvelopeManifest | None = None
    source_summary: dict[str, object] | None = None
    if recovery.unlock.satisfied and recovery.unlock.resolved_passphrase is not None:
        try:
            plaintext = decrypt_bytes(
                recovery.ciphertext,
                passphrase=recovery.unlock.resolved_passphrase,
                debug=debug,
            )
            manifest, _payload = decode_envelope(plaintext)
            source_summary = _mint_source_summary(manifest)
        except Exception as exc:
            blocking_issues.append(
                _mint_blocking_issue("UNLOCK_FAILED", str(exc), details={"stage": "decrypt"})
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
    blocking_issues.extend(signing_key_issues)
    blocking_issues.extend(
        _inspect_mint_replacement_blockers(
            args=args,
            recovery=recovery,
            passphrase_shard_frames=list(state.shard_frames),
            signing_key_frames=list(state.signing_key_frames),
        )
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
        signing_key_frame_count=len(state.signing_key_frames),
        signing_key_validated_shard_count=signing_key_validated_shard_count,
        signing_key_required_threshold=signing_key_required_threshold,
        signing_key_satisfied=signing_key_satisfied,
        signing_key_source=signing_key_source,
        mint_capabilities=mint_capabilities,
        blocking_issues=tuple(blocking_issues),
    )


def _should_use_wizard_for_mint(args: MintArgs) -> bool:
    if args.fallback_file or args.payloads_file or args.scan:
        return False
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    return True


def run_mint_wizard(args: MintArgs, *, debug: bool = False, show_header: bool = True) -> int:
    quiet = args.quiet
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return run_mint_command(args, debug=debug)

    config = load_app_config(args.config, paper_size=args.paper)
    config = apply_template_design(config, args.design)
    recover_args = _recover_args_from_mint_args(args)
    extra_auth_frames = _extra_auth_frames_from_args(
        recover_args,
        allow_unsigned=False,
        quiet=quiet,
    )
    working_args = replace(args)
    _validate_wizard_output_args(working_args)

    with ui_screen_mode(quiet=quiet):
        if show_header and not quiet:
            console.print("[title]Ethernity mint wizard[/title]")
            console.print("[subtitle]Guided minting of fresh shard documents.[/subtitle]")

        with wizard_flow(name="Mint", total_steps=4, quiet=quiet):
            frames: list = []
            input_label: str | None = None
            input_detail: str | None = None
            passphrase = working_args.passphrase
            shard_fallback_files = list(working_args.shard_fallback_file or [])
            shard_payloads_file = list(working_args.shard_payloads_file or [])
            collected_shard_frames: list[Frame] = []
            shard_frames: list[Frame] = []
            plan = None
            manifest = None
            signing_key_frames = _signing_key_shard_frames_from_args(working_args, quiet=quiet)
            mint_passphrase_shards = working_args.mint_passphrase_shards
            mint_signing_key_shards = working_args.mint_signing_key_shards
            passphrase_sharding = _configured_passphrase_sharding(working_args)
            signing_key_sharding = _configured_signing_key_sharding(
                working_args,
                passphrase_sharding=passphrase_sharding,
            )
            passphrase_replacement_count = working_args.passphrase_replacement_count
            signing_key_replacement_count = working_args.signing_key_replacement_count
            legacy_advisory_notes: tuple[str, ...] = ()
            stage_index = 0

            while stage_index < 4:
                if stage_index == 0:
                    with wizard_stage("Input", step_number=1):
                        frames, input_label, input_detail = prompt_recovery_input_interactive(
                            allow_unsigned=False,
                            quiet=quiet,
                        )
                    stage_index += 1
                    continue

                if stage_index == 1:
                    with wizard_stage("Keys", step_number=2):
                        (
                            passphrase,
                            shard_fallback_files,
                            shard_payloads_file,
                            collected_shard_frames,
                        ) = _prompt_key_material(
                            recover_args,
                            quiet=quiet,
                            collect_all_shards=True,
                        )
                        shard_frames = (
                            _load_shard_frames(
                                shard_fallback_files,
                                shard_payloads_file,
                                collected_shard_frames,
                                quiet,
                            )
                            if (
                                shard_fallback_files
                                or shard_payloads_file
                                or collected_shard_frames
                                or passphrase is None
                            )
                            else []
                        )
                        working_args.passphrase = passphrase
                        working_args.shard_fallback_file = list(shard_fallback_files)
                        working_args.shard_payloads_file = list(shard_payloads_file or [])
                        if passphrase_replacement_count is not None and not shard_frames:
                            raise ValueError(
                                "passphrase replacement minting requires existing "
                                "passphrase shard inputs"
                            )
                    stage_index += 1
                    continue

                (
                    recovery_shard_frames,
                    recovery_shard_fallback_files,
                    recovery_shard_payloads_file,
                ) = _recovery_shard_inputs_for_plan(
                    passphrase=passphrase,
                    shard_frames=shard_frames,
                    shard_fallback_files=shard_fallback_files,
                    shard_payloads_file=shard_payloads_file,
                )
                plan = build_recovery_plan(
                    frames=frames,
                    extra_auth_frames=extra_auth_frames,
                    shard_frames=recovery_shard_frames,
                    passphrase=passphrase,
                    allow_unsigned=False,
                    input_label=input_label,
                    input_detail=input_detail,
                    shard_fallback_files=recovery_shard_fallback_files,
                    shard_payloads_file=recovery_shard_payloads_file,
                    shard_scan=list(recover_args.shard_scan or []),
                    output_path=None,
                    args=recover_args,
                    quiet=quiet,
                )
                if plan.auth_payload is None:
                    raise ValueError(
                        "minting requires authenticated recovery input; use `ethernity mint` for "
                        "advanced auth-input options"
                    )
                plaintext = decrypt_bytes(plan.ciphertext, passphrase=plan.passphrase, debug=debug)
                manifest, _payload = decode_envelope(plaintext)
                needs_signing_authority = manifest.signing_seed is None

                if stage_index == 2 and needs_signing_authority:
                    with wizard_stage("Signing authority", step_number=3):
                        if not signing_key_frames:
                            (
                                _fallback_files,
                                _payload_files,
                                signing_key_frames,
                            ) = _prompt_shard_inputs(
                                quiet=quiet,
                                key_type=KEY_TYPE_SIGNING_SEED,
                                label="Signing-key shard documents",
                                stop_at_quorum=False,
                            )
                    stage_index += 1
                    continue

                if stage_index == 2:
                    if signing_key_replacement_count is not None and not signing_key_frames:
                        raise ValueError(
                            "signing-key replacement minting requires existing "
                            "signing-key shard inputs"
                        )
                    stage_index += 1
                    continue

                with wizard_stage(
                    "Outputs",
                    step_number=4 if needs_signing_authority else 3,
                ):
                    passphrase_resolution = _ReplacementShardResolution()
                    signing_resolution = _ReplacementShardResolution()
                    if not _passphrase_output_is_preset(working_args):
                        mint_passphrase_shards = prompt_yes_no(
                            "Mint passphrase shard documents",
                            default=True,
                        )
                    if not _signing_key_output_is_preset(working_args):
                        mint_signing_key_shards = prompt_yes_no(
                            "Mint signing-key shard documents",
                            default=True,
                        )
                    if not mint_passphrase_shards and not mint_signing_key_shards:
                        raise ValueError("mint must create at least one shard document type")
                    if mint_passphrase_shards:
                        if passphrase_replacement_count is not None:
                            passphrase_resolution = _replacement_payloads_from_frames(
                                shard_frames,
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
                        elif passphrase_sharding is None:
                            passphrase_resolution = _replacement_payloads_from_frames(
                                shard_frames,
                                doc_id=plan.doc_id,
                                doc_hash=plan.doc_hash,
                                sign_pub=plan.auth_payload.sign_pub,
                                key_type=KEY_TYPE_PASSPHRASE,
                                secret_label="passphrase",
                            )
                            if passphrase_resolution.payloads:
                                missing_count = _missing_replacement_count(
                                    list(passphrase_resolution.payloads)
                                )
                                if missing_count > 0:
                                    mode = _prompt_shard_mint_mode(
                                        label="passphrase",
                                        threshold=passphrase_resolution.payloads[0].threshold,
                                        share_count=passphrase_resolution.payloads[0].share_count,
                                        missing_count=missing_count,
                                    )
                                    if mode == "replacement":
                                        passphrase_replacement_count = (
                                            1
                                            if missing_count == 1
                                            else _prompt_replacement_count(
                                                "passphrase",
                                                maximum=missing_count,
                                            )
                                        )
                            else:
                                _raise_if_under_quorum_replacement_inputs(
                                    passphrase_resolution,
                                    secret_label="passphrase",
                                )
                        if passphrase_replacement_count is None and passphrase_sharding is None:
                            passphrase_sharding = _prompt_quorum_choice(
                                title="Passphrase shard quorum",
                                help_text=(
                                    "Choose how many fresh passphrase shard documents to create "
                                    "and how many are required to recover."
                                ),
                            )

                    if mint_signing_key_shards:
                        if (
                            signing_key_replacement_count is None
                            and signing_key_sharding is None
                            and not signing_key_frames
                            and manifest.signing_seed is not None
                        ):
                            use_existing_signing_key_shards = prompt_yes_no(
                                "Use existing signing-key shards for compatible replacements",
                                default=False,
                                help_text=(
                                    "Choose yes to provide existing signing-key shard documents "
                                    "from this backup so compatible replacements can fill missing "
                                    "slots. Choose no to mint a fresh signing-key shard set."
                                ),
                            )
                            if use_existing_signing_key_shards:
                                (
                                    _fallback_files,
                                    _payload_files,
                                    signing_key_frames,
                                ) = _prompt_shard_inputs(
                                    quiet=quiet,
                                    key_type=KEY_TYPE_SIGNING_SEED,
                                    label="Signing-key shard documents",
                                    stop_at_quorum=False,
                                )
                        if signing_key_replacement_count is not None:
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
                        elif signing_key_sharding is None:
                            signing_resolution = _replacement_payloads_from_frames(
                                signing_key_frames,
                                doc_id=plan.doc_id,
                                doc_hash=plan.doc_hash,
                                sign_pub=plan.auth_payload.sign_pub,
                                key_type=KEY_TYPE_SIGNING_SEED,
                                secret_label="signing key",
                            )
                            if signing_resolution.payloads:
                                missing_count = _missing_replacement_count(
                                    list(signing_resolution.payloads)
                                )
                                if missing_count > 0:
                                    mode = _prompt_shard_mint_mode(
                                        label="signing-key",
                                        threshold=signing_resolution.payloads[0].threshold,
                                        share_count=signing_resolution.payloads[0].share_count,
                                        missing_count=missing_count,
                                    )
                                    if mode == "replacement":
                                        signing_key_replacement_count = (
                                            1
                                            if missing_count == 1
                                            else _prompt_replacement_count(
                                                "signing-key",
                                                maximum=missing_count,
                                            )
                                        )
                            else:
                                _raise_if_under_quorum_replacement_inputs(
                                    signing_resolution,
                                    secret_label="signing key",
                                )
                        if (
                            signing_key_replacement_count is None
                            and signing_key_sharding is None
                            and passphrase_sharding is not None
                        ):
                            use_same = prompt_yes_no(
                                (
                                    "Use same quorum for signing-key shards "
                                    f"({passphrase_sharding.threshold} "
                                    f"of {passphrase_sharding.shares})"
                                ),
                                default=True,
                                help_text=(
                                    "Choose no if you want a different number of signing-key shard "
                                    "documents."
                                ),
                            )
                            signing_key_sharding = (
                                None
                                if use_same
                                else _prompt_quorum_choice(
                                    title="Signing-key shard quorum",
                                    help_text=(
                                        "Choose how many fresh signing-key shard documents "
                                        "to create "
                                        "and how many are required to recover."
                                    ),
                                )
                            )
                        elif signing_key_replacement_count is None and signing_key_sharding is None:
                            signing_key_sharding = _prompt_quorum_choice(
                                title="Signing-key shard quorum",
                                help_text=(
                                    "Choose how many fresh signing-key shard documents to create "
                                    "and how many are required to recover."
                                ),
                            )
                    legacy_advisory_notes = _legacy_replacement_notes(
                        passphrase_resolution=passphrase_resolution,
                        signing_resolution=signing_resolution,
                        args=MintArgs(
                            passphrase_replacement_count=passphrase_replacement_count,
                            signing_key_replacement_count=signing_key_replacement_count,
                        ),
                    )
                    _print_legacy_replacement_warning(legacy_advisory_notes, quiet=quiet)
                break

            plan = cast(Any, plan)
            manifest = cast(Any, manifest)

    wizard_args = MintArgs(
        config=args.config,
        paper=args.paper,
        design=args.design,
        output_dir=working_args.output_dir,
        layout_debug_dir=args.layout_debug_dir,
        shard_threshold=passphrase_sharding.threshold if passphrase_sharding else None,
        shard_count=passphrase_sharding.shares if passphrase_sharding else None,
        signing_key_shard_threshold=(
            signing_key_sharding.threshold if signing_key_sharding is not None else None
        ),
        signing_key_shard_count=(
            signing_key_sharding.shares if signing_key_sharding is not None else None
        ),
        passphrase_replacement_count=passphrase_replacement_count,
        signing_key_replacement_count=signing_key_replacement_count,
        mint_passphrase_shards=mint_passphrase_shards,
        mint_signing_key_shards=mint_signing_key_shards,
        quiet=quiet,
    )
    result = _mint_from_plan(
        plan=plan,
        config=config,
        args=wizard_args,
        passphrase_shard_frames=shard_frames,
        signing_key_frames=signing_key_frames,
        manifest_signing_seed=manifest.signing_seed,
        debug=debug,
    )
    if legacy_advisory_notes:
        result = replace(
            result,
            notes=tuple(note for note in result.notes if note not in legacy_advisory_notes),
        )
    print_mint_summary(result, quiet=quiet)
    _print_completion_actions(result, quiet=quiet)
    return 0


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
    config = apply_template_design(config, args.design)
    recover_args = _recover_args_from_mint_args(args)
    frames, input_label, input_detail = _frames_from_args(
        recover_args,
        allow_unsigned=False,
        quiet=args.quiet,
    )
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

    source = "signing-key shards"
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
                        "backup is sealed; provide signing-key shard inputs "
                        "to mint new shard documents"
                    ),
                )
            ],
        )
    try:
        payloads = _validated_shard_payloads_from_frames(
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
    base_ready = (
        recovery.auth_payload is not None
        and recovery.unlock.satisfied
        and manifest is not None
        and signing_key_satisfied
    )
    if not base_ready:
        return {
            "can_mint_passphrase_shards": False,
            "can_mint_signing_key_shards": False,
        }

    blocker_codes = {
        str(issue.get("code"))
        for issue in blocking_issues
        if isinstance(issue, dict) and issue.get("code") is not None
    }
    return {
        "can_mint_passphrase_shards": args.mint_passphrase_shards
        and not bool(blocker_codes & _PASSPHRASE_MINT_BLOCKER_CODES),
        "can_mint_signing_key_shards": args.mint_signing_key_shards
        and not bool(blocker_codes & _SIGNING_KEY_MINT_BLOCKER_CODES),
    }


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
        auth_fallback_file=args.auth_fallback_file,
        auth_payloads_file=args.auth_payloads_file,
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
            "cannot request signing-key replacement shards when signing-key output is off"
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
            "signing-key replacement minting requires existing signing-key shard inputs"
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
        threshold_label="signing key shard threshold",
        count_label="signing key shard count",
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
                "minting signing-key shards requires a shard quorum or an explicit "
                "signing-key shard quorum"
            )


def _validate_wizard_output_args(args: MintArgs) -> None:
    if not args.mint_passphrase_shards and args.passphrase_replacement_count is not None:
        raise ValueError(
            "cannot request passphrase replacement shards when passphrase output is off"
        )
    if not args.mint_signing_key_shards and args.signing_key_replacement_count is not None:
        raise ValueError(
            "cannot request signing-key replacement shards when signing-key output is off"
        )
    if args.passphrase_replacement_count is not None and args.passphrase_replacement_count < 1:
        raise ValueError("passphrase replacement count must be >= 1")
    if args.signing_key_replacement_count is not None and args.signing_key_replacement_count < 1:
        raise ValueError("signing key replacement count must be >= 1")
    _validate_quorum_pair(
        args.shard_threshold,
        args.shard_count,
        threshold_label="shard threshold",
        count_label="shard count",
        pair_label="--shard-threshold and --shard-count",
        required=False,
    )
    _validate_quorum_pair(
        args.signing_key_shard_threshold,
        args.signing_key_shard_count,
        threshold_label="signing key shard threshold",
        count_label="signing key shard count",
        pair_label="--signing-key-shard-threshold and --signing-key-shard-count",
        required=False,
    )


def _passphrase_output_is_preset(args: MintArgs) -> bool:
    return (
        not args.mint_passphrase_shards
        or args.passphrase_replacement_count is not None
        or (args.shard_threshold is not None and args.shard_count is not None)
    )


def _signing_key_output_is_preset(args: MintArgs) -> bool:
    return (
        not args.mint_signing_key_shards
        or args.signing_key_replacement_count is not None
        or (
            args.signing_key_shard_threshold is not None
            and args.signing_key_shard_count is not None
        )
        or (
            args.mint_signing_key_shards
            and args.shard_threshold is not None
            and args.shard_count is not None
        )
    )


def _configured_passphrase_sharding(args: MintArgs) -> ShardingConfig | None:
    if args.shard_threshold is None or args.shard_count is None:
        return None
    return ShardingConfig(
        threshold=args.shard_threshold,
        shares=args.shard_count,
    )


def _configured_signing_key_sharding(
    args: MintArgs,
    *,
    passphrase_sharding: ShardingConfig | None,
) -> ShardingConfig | None:
    if args.signing_key_shard_threshold is not None and args.signing_key_shard_count is not None:
        return ShardingConfig(
            threshold=args.signing_key_shard_threshold,
            shares=args.signing_key_shard_count,
        )
    if args.mint_signing_key_shards and passphrase_sharding is not None:
        return ShardingConfig(
            threshold=passphrase_sharding.threshold,
            shares=passphrase_sharding.shares,
        )
    return None


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
    if manifest_signing_seed is _UNSET:
        plaintext = decrypt_bytes(plan.ciphertext, passphrase=plan.passphrase, debug=debug)
        manifest, _payload = decode_envelope(plaintext)
        resolved_manifest_signing_seed = manifest.signing_seed
    else:
        resolved_manifest_signing_seed = cast(bytes | None, manifest_signing_seed)
    sign_priv, signing_key_source = _resolve_signing_authority(
        manifest_signing_seed=resolved_manifest_signing_seed,
        signing_key_frames=signing_key_frames,
        doc_id=plan.doc_id,
        doc_hash=plan.doc_hash,
        expected_sign_pub=plan.auth_payload.sign_pub,
    )
    sign_pub = derive_public_key(sign_priv)
    if sign_pub != plan.auth_payload.sign_pub:
        raise ValueError("signing authority does not match the authenticated backup")

    passphrase_resolution = _ReplacementShardResolution()
    signing_resolution = _ReplacementShardResolution()

    shard_payloads: list[ShardPayload] = []
    if args.mint_passphrase_shards:
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
                plan.passphrase,
                threshold=passphrase_sharding.threshold,
                shares=passphrase_sharding.shares,
                doc_hash=plan.doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )

    signing_key_payloads: list[ShardPayload] = []
    if args.mint_signing_key_shards:
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
                doc_hash=plan.doc_hash,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
            )

    output_dir = _ensure_mint_output_dir(
        args.output_dir,
        plan.doc_id.hex(),
        existing_directory_is_parent=args.output_dir_existing_parent,
    )
    staging_output_dir = _prepare_mint_staging_dir(output_dir)
    layout_debug_dir = _resolve_layout_debug_dir(args.layout_debug_dir)
    render_service = RenderService(config)
    qr_payload_codec = config.cli_defaults.backup.qr_payload_codec
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
                    doc_id=plan.doc_id,
                    output_dir=staging_output_dir,
                    render_service=render_service,
                    filename_prefix="shard",
                    template_path=config.shard_template_path,
                    layout_debug_json_path=_layout_debug_json_path(
                        layout_debug_dir,
                        f"shard-{shard.share_index:02d}-of-{shard.share_count:02d}",
                    ),
                    qr_payload_codec=qr_payload_codec,
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
                    doc_id=plan.doc_id,
                    output_dir=staging_output_dir,
                    render_service=render_service,
                    filename_prefix="signing-key-shard",
                    template_path=config.signing_key_shard_template_path,
                    doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
                    layout_debug_json_path=_layout_debug_json_path(
                        layout_debug_dir,
                        f"signing-key-shard-{shard.share_index:02d}-of-{shard.share_count:02d}",
                    ),
                    qr_payload_codec=qr_payload_codec,
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
        doc_id=plan.doc_id,
        output_dir=output_dir,
        shard_paths=final_shard_paths,
        signing_key_shard_paths=final_signing_key_shard_paths,
        signing_key_source=signing_key_source,
        notes=notes,
    )


def _signing_key_shard_frames_from_args(args: MintArgs, *, quiet: bool) -> list[Frame]:
    fallback_files = list(args.signing_key_shard_fallback_file or [])
    payload_files = list(args.signing_key_shard_payloads_file or [])
    scan_files = list(args.signing_key_shard_scan or [])
    if not fallback_files and not payload_files and not scan_files:
        return []
    temp_args = RecoverArgs(
        shard_fallback_file=fallback_files,
        shard_payloads_file=payload_files,
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
        raise ValueError(
            "backup is sealed; provide signing-key shard inputs to mint new shard documents"
        )
    signing_seed = _signing_seed_from_shard_frames(
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
        payloads = _validated_shard_payloads_from_frames(
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
            "Legacy v1 signing-key shards detected. Compatible replacements stay on v1; "
            "prefer minting a full new signing-key shard set to migrate to shard payload v2."
        )
    return tuple(notes)


def _print_legacy_replacement_warning(notes: tuple[str, ...], *, quiet: bool) -> None:
    if quiet or not notes:
        return
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


def _missing_replacement_count(payloads: list[ShardPayload]) -> int:
    if not payloads:
        return 0
    seen = {payload.share_index for payload in payloads}
    return len([index for index in range(1, payloads[0].share_count + 1) if index not in seen])


def _prompt_shard_mint_mode(
    *,
    label: str,
    threshold: int,
    share_count: int,
    missing_count: int,
) -> str:
    shard_label = f"{label} shards"
    replacement_label = f"Mint compatible replacement {shard_label} ({missing_count} available)"
    fresh_label = f"Mint fresh {shard_label} set"
    return prompt_choice(
        f"{label.capitalize()} shard mode",
        {
            "replacement": replacement_label,
            "fresh": fresh_label,
        },
        default="replacement",
        help_text=(
            f"Detected current {threshold} of {share_count} set. "
            "Compatible replacements fill missing shard slots; a fresh set creates a new shard set."
        ),
    )


def _prompt_replacement_count(label: str, *, maximum: int) -> int:
    return prompt_int(
        f"How many replacement {label} shard documents to mint",
        minimum=1,
        maximum=maximum,
        help_text=(
            f"You can mint up to {maximum} compatible replacement {label} shard document(s) "
            "from the current set."
        ),
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
    output_path = Path(output_dir)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_path.name}.tmp-", dir=str(output_path.parent))
    )
    return str(staging_dir)


def _print_completion_actions(result: MintResult, *, quiet: bool) -> None:
    if quiet:
        return
    actions = [f"Saved to {result.output_dir}"]
    if result.shard_paths:
        actions.append(f"Store {len(result.shard_paths)} fresh shard documents separately.")
    if result.signing_key_shard_paths:
        actions.append(
            "Store "
            f"{len(result.signing_key_shard_paths)} fresh signing-key shard documents "
            "separately."
        )
    actions.append("Verify the new shard documents before retiring any older set.")
    print_completion_panel("Mint complete", actions, quiet=quiet)
