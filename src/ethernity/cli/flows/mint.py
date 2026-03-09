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

from ...config import apply_template_design, load_app_config
from ...core.models import ShardingConfig, SigningSeedMode
from ...crypto import decrypt_bytes
from ...crypto.sharding import KEY_TYPE_SIGNING_SEED, split_passphrase, split_signing_seed
from ...crypto.signing import derive_public_key
from ...encoding.framing import Frame
from ...formats.envelope_codec import decode_envelope
from ...render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ...render.service import RenderService
from ..api import (
    console,
    print_completion_panel,
    prompt_optional_path_with_picker,
    prompt_yes_no,
    ui_screen_mode,
    wizard_flow,
    wizard_stage,
)
from ..core.types import MintArgs, MintResult, RecoverArgs
from ..io.outputs import _ensure_directory
from ..keys.recover_keys import _signing_seed_from_shard_frames
from ..ui.summary import print_mint_summary
from .backup_flow import _layout_debug_json_path, _render_shard, _resolve_layout_debug_dir
from .backup_wizard import (
    _prompt_quorum_choice,
    resolve_passphrase_sharding,
    resolve_signing_seed_sharding,
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
    plan = build_recovery_plan(
        frames=frames,
        extra_auth_frames=extra_auth_frames,
        shard_frames=shard_frames,
        passphrase=args.passphrase,
        allow_unsigned=False,
        input_label=input_label,
        input_detail=input_detail,
        shard_fallback_files=shard_fallback_files,
        shard_payloads_file=shard_payloads_file,
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
        signing_key_frames=signing_key_frames,
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

    with ui_screen_mode(quiet=quiet):
        if show_header and not quiet:
            console.print("[title]Ethernity mint wizard[/title]")
            console.print("[subtitle]Guided minting of fresh shard documents.[/subtitle]")

        with wizard_flow(name="Mint", total_steps=4, quiet=quiet):
            with wizard_stage("Input"):
                frames, input_label, input_detail = prompt_recovery_input_interactive(
                    allow_unsigned=False,
                    quiet=quiet,
                )

            with wizard_stage("Keys"):
                (
                    passphrase,
                    shard_fallback_files,
                    shard_payloads_file,
                    pasted_shard_frames,
                ) = _prompt_key_material(recover_args, quiet=quiet)
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

            plan = build_recovery_plan(
                frames=frames,
                extra_auth_frames=[],
                shard_frames=shard_frames,
                passphrase=passphrase,
                allow_unsigned=False,
                input_label=input_label,
                input_detail=input_detail,
                shard_fallback_files=shard_fallback_files,
                shard_payloads_file=shard_payloads_file,
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

            signing_key_frames: list[Frame] = []
            if manifest.signing_seed is None:
                with wizard_stage("Signing authority"):
                    _fallback_files, _payload_files, signing_key_frames = _prompt_shard_inputs(
                        quiet=quiet,
                        key_type=KEY_TYPE_SIGNING_SEED,
                        label="Signing-key shard documents",
                    )

            with wizard_stage("Outputs"):
                mint_passphrase_shards = prompt_yes_no(
                    "Mint fresh passphrase shard documents",
                    default=True,
                )
                mint_signing_key_shards = prompt_yes_no(
                    "Mint fresh signing-key shard documents",
                    default=True,
                )
                if not mint_passphrase_shards and not mint_signing_key_shards:
                    raise ValueError("mint must create at least one shard document type")
                passphrase_sharding = (
                    resolve_passphrase_sharding(
                        args=None,
                        confirm_existing=False,
                        prompt_when_missing=True,
                    )
                    if mint_passphrase_shards
                    else None
                )
                if mint_signing_key_shards:
                    if passphrase_sharding is not None:
                        signing_key_sharding = resolve_signing_seed_sharding(
                            args=None,
                            signing_seed_mode=SigningSeedMode.SHARDED,
                            passphrase_sharding=passphrase_sharding,
                            confirm_existing=False,
                            prompt_when_missing=True,
                        )
                    else:
                        signing_key_sharding = _prompt_quorum_choice()
                else:
                    signing_key_sharding = None
                output_dir = prompt_optional_path_with_picker(
                    "Output directory",
                    kind="dir",
                    allow_new=True,
                    help_text="Leave blank to use mint-<doc_id> in the current directory.",
                    picker_prompt="Select an output directory",
                )

    wizard_args = MintArgs(
        config=args.config,
        paper=args.paper,
        design=args.design,
        output_dir=output_dir,
        layout_debug_dir=args.layout_debug_dir,
        shard_threshold=passphrase_sharding.threshold if passphrase_sharding else None,
        shard_count=passphrase_sharding.shares if passphrase_sharding else None,
        signing_key_shard_threshold=(
            signing_key_sharding.threshold if signing_key_sharding is not None else None
        ),
        signing_key_shard_count=(
            signing_key_sharding.shares if signing_key_sharding is not None else None
        ),
        mint_passphrase_shards=mint_passphrase_shards,
        mint_signing_key_shards=mint_signing_key_shards,
        quiet=quiet,
    )
    result = _mint_from_plan(
        plan=plan,
        config=config,
        args=wizard_args,
        signing_key_frames=signing_key_frames,
        debug=debug,
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
        shard_dir=args.shard_dir,
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
    _recover_args_from_mint_args(args)
    _validate_quorum_pair(
        args.shard_threshold,
        args.shard_count,
        threshold_label="shard threshold",
        count_label="shard count",
        pair_label="--shard-threshold and --shard-count",
        required=args.mint_passphrase_shards,
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


def _mint_from_plan(
    *,
    plan,
    config,
    args: MintArgs,
    signing_key_frames: list[Frame],
    debug: bool,
) -> MintResult:
    plaintext = decrypt_bytes(plan.ciphertext, passphrase=plan.passphrase, debug=debug)
    manifest, _payload = decode_envelope(plaintext)
    sign_priv, signing_key_source = _resolve_signing_authority(
        manifest_signing_seed=manifest.signing_seed,
        signing_key_frames=signing_key_frames,
        doc_id=plan.doc_id,
        doc_hash=plan.doc_hash,
        expected_sign_pub=plan.auth_payload.sign_pub,
    )
    sign_pub = derive_public_key(sign_priv)
    if sign_pub != plan.auth_payload.sign_pub:
        raise ValueError("signing authority does not match the authenticated backup")

    output_dir = _ensure_mint_output_dir(args.output_dir, plan.doc_id.hex())
    layout_debug_dir = _resolve_layout_debug_dir(args.layout_debug_dir)
    render_service = RenderService(config)
    qr_payload_codec = config.cli_defaults.backup.qr_payload_codec

    shard_paths: list[str] = []
    if args.mint_passphrase_shards:
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
    if args.mint_signing_key_shards:
        signing_key_sharding = _resolve_signing_key_output_sharding(args)
        signing_key_payloads = split_signing_seed(
            sign_priv,
            threshold=signing_key_sharding.threshold,
            shares=signing_key_sharding.shares,
            doc_hash=plan.doc_hash,
            sign_priv=sign_priv,
            sign_pub=sign_pub,
        )
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

    return MintResult(
        doc_id=plan.doc_id,
        output_dir=output_dir,
        shard_paths=tuple(shard_paths),
        signing_key_shard_paths=tuple(signing_key_shard_paths),
        signing_key_source=signing_key_source,
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
