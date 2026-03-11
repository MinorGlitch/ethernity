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
from dataclasses import dataclass, replace
from typing import Any, cast

from ...config import apply_template_design, load_app_config
from ...core.models import ShardingConfig
from ...crypto import decrypt_bytes
from ...crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    LEGACY_SHARD_VERSION,
    ShardPayload,
    mint_replacement_shards,
    split_passphrase,
    split_signing_seed,
)
from ...crypto.signing import derive_public_key
from ...encoding.framing import Frame
from ...formats.envelope_codec import decode_envelope
from ...render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ...render.service import RenderService
from ..api import (
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
from ..core.types import MintArgs, MintResult, RecoverArgs
from ..io.outputs import _ensure_directory
from ..keys.recover_keys import (
    InsufficientShardError,
    _signing_seed_from_shard_frames,
    _validated_shard_payloads_from_frames,
)
from ..ui.summary import print_mint_summary
from .backup_flow import _layout_debug_json_path, _render_shard, _resolve_layout_debug_dir
from .backup_wizard import (
    _prompt_quorum_choice,
)
from .prompts import _prompt_shard_inputs
from .recover_input import prompt_recovery_input_interactive
from .recover_plan import (
    _extra_auth_frames_from_args,
    _frames_from_args,
    _shard_frames_from_args,
    build_recovery_plan,
    validate_recover_args,
)
from .recover_wizard import _load_shard_frames, _prompt_key_material

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


def run_mint_command(args: MintArgs, *, debug: bool = False) -> int:
    """Mint fresh shard documents from an existing backup."""

    _validate_mint_args(args)
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
    shard_frames, shard_fallback_files, shard_payloads_file = _shard_frames_from_args(
        recover_args,
        quiet=args.quiet,
    )
    recovery_shard_frames, recovery_shard_fallback_files, recovery_shard_payloads_file = (
        _recovery_shard_inputs_for_plan(
            passphrase=args.passphrase,
            shard_frames=shard_frames,
            shard_fallback_files=shard_fallback_files,
            shard_payloads_file=shard_payloads_file,
        )
    )
    plan = build_recovery_plan(
        frames=frames,
        extra_auth_frames=extra_auth_frames,
        shard_frames=recovery_shard_frames,
        passphrase=args.passphrase,
        allow_unsigned=False,
        input_label=input_label,
        input_detail=input_detail,
        shard_fallback_files=recovery_shard_fallback_files,
        shard_payloads_file=recovery_shard_payloads_file,
        output_path=None,
        args=recover_args,
        quiet=args.quiet,
    )
    if plan.auth_payload is None:
        raise ValueError("minting requires an authenticated backup input with an AUTH payload")

    signing_key_frames = _signing_key_shard_frames_from_args(args, quiet=args.quiet)
    result = _mint_from_plan(
        plan=plan,
        config=config,
        args=args,
        passphrase_shard_frames=shard_frames,
        signing_key_frames=signing_key_frames,
        manifest_signing_seed=_UNSET,
        debug=debug,
    )
    print_mint_summary(result, quiet=args.quiet)
    _print_completion_actions(result, quiet=args.quiet)
    return 0


def run_mint_wizard(args: MintArgs, *, debug: bool = False, show_header: bool = True) -> int:
    quiet = args.quiet
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return run_mint_command(args, debug=debug)

    config = load_app_config(args.config, paper_size=args.paper)
    config = apply_template_design(config, args.design)
    recover_args = _recover_args_from_mint_args(args)
    working_args = replace(args)

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
            pasted_shard_frames: list[Frame] = []
            shard_frames: list[Frame] = []
            plan = None
            manifest = None
            signing_key_frames = _signing_key_shard_frames_from_args(working_args, quiet=quiet)
            mint_passphrase_shards = True
            mint_signing_key_shards = True
            passphrase_sharding = None
            signing_key_sharding = None
            passphrase_replacement_count = None
            signing_key_replacement_count = None
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
                            pasted_shard_frames,
                        ) = _prompt_key_material(
                            recover_args,
                            quiet=quiet,
                            collect_all_shards=True,
                        )
                        shard_frames = (
                            _load_shard_frames(
                                shard_fallback_files,
                                shard_payloads_file,
                                pasted_shard_frames,
                                quiet,
                            )
                            if (
                                shard_fallback_files
                                or shard_payloads_file
                                or pasted_shard_frames
                                or passphrase is None
                            )
                            else []
                        )
                        working_args.passphrase = passphrase
                        working_args.shard_fallback_file = list(shard_fallback_files)
                        working_args.shard_payloads_file = list(shard_payloads_file or [])
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
                    extra_auth_frames=[],
                    shard_frames=recovery_shard_frames,
                    passphrase=passphrase,
                    allow_unsigned=False,
                    input_label=input_label,
                    input_detail=input_detail,
                    shard_fallback_files=recovery_shard_fallback_files,
                    shard_payloads_file=recovery_shard_payloads_file,
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
                        _fallback_files, _payload_files, signing_key_frames = _prompt_shard_inputs(
                            quiet=quiet,
                            key_type=KEY_TYPE_SIGNING_SEED,
                            label="Signing-key shard documents",
                            stop_at_quorum=False,
                        )
                    stage_index += 1
                    continue

                if stage_index == 2:
                    stage_index += 1
                    continue

                with wizard_stage(
                    "Outputs",
                    step_number=4 if needs_signing_authority else 3,
                ):
                    passphrase_resolution = _ReplacementShardResolution()
                    signing_resolution = _ReplacementShardResolution()
                    mint_passphrase_shards = prompt_yes_no(
                        "Mint passphrase shard documents",
                        default=True,
                    )
                    mint_signing_key_shards = prompt_yes_no(
                        "Mint signing-key shard documents",
                        default=True,
                    )
                    if not mint_passphrase_shards and not mint_signing_key_shards:
                        raise ValueError("mint must create at least one shard document type")
                    passphrase_sharding = None
                    signing_key_sharding = None
                    passphrase_replacement_count = None
                    if mint_passphrase_shards:
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
                        if passphrase_replacement_count is None:
                            passphrase_sharding = _prompt_quorum_choice(
                                title="Passphrase shard quorum",
                                help_text=(
                                    "Choose how many fresh passphrase shard documents to create "
                                    "and how many are required to recover."
                                ),
                            )

                    signing_key_replacement_count = None
                    if mint_signing_key_shards:
                        if not signing_key_frames and manifest.signing_seed is not None:
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
                        elif signing_key_replacement_count is None:
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


def _validate_mint_args(args: MintArgs) -> None:
    if not args.mint_passphrase_shards and not args.mint_signing_key_shards:
        raise ValueError("mint must create at least one shard document type")
    if args.passphrase_replacement_count is not None and not args.mint_passphrase_shards:
        raise ValueError(
            "cannot request passphrase replacement shards when passphrase output is off"
        )
    if args.signing_key_replacement_count is not None and not args.mint_signing_key_shards:
        raise ValueError(
            "cannot request signing-key replacement shards when signing-key output is off"
        )
    if args.passphrase_replacement_count is not None and args.passphrase_replacement_count < 1:
        raise ValueError("passphrase replacement count must be >= 1")
    if args.signing_key_replacement_count is not None and args.signing_key_replacement_count < 1:
        raise ValueError("signing key replacement count must be >= 1")
    if args.passphrase_replacement_count is not None and not _has_existing_shard_inputs(
        args.shard_fallback_file,
        args.shard_payloads_file,
    ):
        raise ValueError("passphrase replacement minting requires existing passphrase shard inputs")
    if args.signing_key_replacement_count is not None and not _has_existing_shard_inputs(
        args.signing_key_shard_fallback_file,
        args.signing_key_shard_payloads_file,
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
        required=args.mint_passphrase_shards and args.passphrase_replacement_count is None,
    )
    _validate_quorum_pair(
        args.signing_key_shard_threshold,
        args.signing_key_shard_count,
        threshold_label="signing key shard threshold",
        count_label="signing key shard count",
        pair_label=("--signing-key-shard-threshold and --signing-key-shard-count"),
        required=False,
    )
    if args.mint_signing_key_shards:
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
) -> bool:
    return bool(fallback_files or payload_files)


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

    passphrase_resolution = _replacement_payloads_from_frames(
        passphrase_shard_frames,
        doc_id=plan.doc_id,
        doc_hash=plan.doc_hash,
        sign_pub=plan.auth_payload.sign_pub,
        key_type=KEY_TYPE_PASSPHRASE,
        secret_label="passphrase",
    )
    signing_resolution = _replacement_payloads_from_frames(
        signing_key_frames,
        doc_id=plan.doc_id,
        doc_hash=plan.doc_hash,
        sign_pub=plan.auth_payload.sign_pub,
        key_type=KEY_TYPE_SIGNING_SEED,
        secret_label="signing key",
    )

    shard_payloads: list[ShardPayload] = []
    if args.mint_passphrase_shards:
        if args.passphrase_replacement_count is not None:
            _require_replacement_payloads(
                passphrase_resolution,
                secret_label="passphrase",
            )
            shard_payloads = mint_replacement_shards(
                list(passphrase_resolution.payloads),
                count=args.passphrase_replacement_count,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
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
            _require_replacement_payloads(
                signing_resolution,
                secret_label="signing key",
            )
            signing_key_payloads = mint_replacement_shards(
                list(signing_resolution.payloads),
                count=args.signing_key_replacement_count,
                sign_priv=sign_priv,
                sign_pub=sign_pub,
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

    output_dir = _ensure_mint_output_dir(args.output_dir, plan.doc_id.hex())
    layout_debug_dir = _resolve_layout_debug_dir(args.layout_debug_dir)
    render_service = RenderService(config)
    qr_payload_codec = config.cli_defaults.backup.qr_payload_codec

    shard_paths: list[str] = []
    for shard in sorted(shard_payloads, key=lambda item: item.share_index):
        shard_paths.append(
            _render_shard(
                shard,
                doc_id=plan.doc_id,
                output_dir=output_dir,
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

    signing_key_shard_paths: list[str] = []
    for shard in sorted(signing_key_payloads, key=lambda item: item.share_index):
        signing_key_shard_paths.append(
            _render_shard(
                shard,
                doc_id=plan.doc_id,
                output_dir=output_dir,
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

    notes = _legacy_replacement_notes(
        passphrase_resolution=passphrase_resolution,
        signing_resolution=signing_resolution,
        args=args,
    )

    return MintResult(
        doc_id=plan.doc_id,
        output_dir=output_dir,
        shard_paths=tuple(shard_paths),
        signing_key_shard_paths=tuple(signing_key_shard_paths),
        signing_key_source=signing_key_source,
        notes=notes,
    )


def _signing_key_shard_frames_from_args(args: MintArgs, *, quiet: bool) -> list[Frame]:
    fallback_files = list(args.signing_key_shard_fallback_file or [])
    payload_files = list(args.signing_key_shard_payloads_file or [])
    if not fallback_files and not payload_files:
        return []
    temp_args = RecoverArgs(
        shard_fallback_file=fallback_files,
        shard_payloads_file=payload_files,
        quiet=quiet,
    )
    frames, _fallback_files, _payload_files = _shard_frames_from_args(temp_args, quiet=quiet)
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


def _ensure_mint_output_dir(output_dir: str | None, doc_id_hex: str) -> str:
    directory = output_dir or f"mint-{doc_id_hex}"
    try:
        resolved = _ensure_directory(directory, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError(
            f"output directory already exists: {directory}; "
            "use a different --output-dir path or remove the existing directory"
        ) from exc
    return str(resolved)


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
