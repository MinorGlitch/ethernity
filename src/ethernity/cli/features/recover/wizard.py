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

"""Interactive recovery wizard orchestration."""

from __future__ import annotations

import sys
from dataclasses import replace

from ethernity.cli.features.recover.execution import (
    RecoverDecryptResult,
    decrypt_manifest_extract_selection,
    write_recovered_outputs,
)
from ethernity.cli.features.recover.input_collection import (
    RECOVERY_QR_TEXT_LABEL,
    RECOVERY_SCAN_LABEL,
    collect_fallback_frames,
    collect_payload_frames,
    prompt_recovery_input_interactive,
)
from ethernity.cli.features.recover.planning import (
    RecoveryPlan,
    build_recovery_plan,
    plan_from_args,
    resolve_recover_config,
    validate_recover_args,
)
from ethernity.cli.shared.io.fallback_parser import format_fallback_error
from ethernity.cli.shared.io.frames import (
    _auth_frames_from_fallback,
    _auth_frames_from_payloads,
    _frame_from_fallback,
    _frames_from_fallback,
    _frames_from_payloads,
    format_shard_input_error,
    recovery_frames_from_scan,
    shard_frames_from_scan,
)
from ethernity.cli.shared.io.outputs import _single_entry_uses_directory_output
from ethernity.cli.shared.log import _warn
from ethernity.cli.shared.recovery_prompts import (
    _resolve_recover_output,
    prompt_passphrase_unlock_material,
)
from ethernity.cli.shared.types import RecoverArgs
from ethernity.cli.shared.ui.debug import print_recover_debug
from ethernity.cli.shared.ui.summary import format_auth_status
from ethernity.cli.shared.ui_api import (
    build_review_table,
    console,
    panel,
    prompt_choice,
    prompt_yes_no,
    status,
    ui_screen_mode,
    wizard_flow,
    wizard_stage,
    wizard_substep,
)
from ethernity.encoding.framing import Frame
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile


def _prompt_recovery_input(
    args: RecoverArgs,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list, str | None, str | None]:
    """Prompt for recovery input. Returns (frames, input_label, input_detail)."""
    frames = None
    input_label: str | None = None
    input_detail: str | None = None

    if args.fallback_file:
        input_label = "Recovery text"
        input_detail = args.fallback_file
        if args.fallback_file == "-" and sys.stdin.isatty():
            input_detail = "stdin"
            frames = collect_fallback_frames(
                allow_unsigned=allow_unsigned,
                quiet=quiet,
                initial_lines=None,
            )
        else:
            try:
                with status("Reading recovery text...", quiet=quiet):
                    frames = _frames_from_fallback(
                        args.fallback_file,
                        allow_invalid_auth=allow_unsigned,
                        quiet=quiet,
                    )
            except ValueError as exc:
                raise ValueError(format_fallback_error(exc, context="Recovery text")) from exc
    elif args.payloads_file:
        input_label = RECOVERY_QR_TEXT_LABEL
        input_detail = args.payloads_file
        if args.payloads_file == "-" and sys.stdin.isatty():
            input_detail = "stdin"
            frames = collect_payload_frames(
                allow_unsigned=allow_unsigned,
                quiet=quiet,
            )
        else:
            with status("Reading backup text lines...", quiet=quiet):
                frames = _frames_from_payloads(
                    args.payloads_file,
                    label="frame",
                )
    elif args.scan:
        input_label = RECOVERY_SCAN_LABEL
        input_detail = ", ".join(args.scan)
        with status("Scanning QR images...", quiet=quiet):
            if args.extension_index == 0:
                frames = recovery_frames_from_scan(
                    args.scan,
                    quiet=quiet,
                    include_extension_carriers=False,
                )
            elif args.extension_index is not None:
                frames = recovery_frames_from_scan(
                    args.scan,
                    quiet=quiet,
                    extension_carrier_max_index=args.extension_index,
                )
            else:
                frames = recovery_frames_from_scan(args.scan, quiet=quiet)
    else:
        frames, input_label, input_detail = prompt_recovery_input_interactive(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
        )
        if input_label == RECOVERY_SCAN_LABEL and input_detail:
            args.scan = [input_detail]

    return frames or [], input_label, input_detail


def _prompt_key_material(
    args: RecoverArgs,
    *,
    quiet: bool,
    collect_all_shards: bool = False,
) -> tuple[str | None, list[str], list[str], list[str], list[Frame]]:
    """Prompt for key material.

    Returns (passphrase, shard_fallback_files, shard_payloads_file, shard_scan, shard_frames).
    """
    return prompt_passphrase_unlock_material(
        quiet=quiet,
        passphrase=args.passphrase,
        shard_fallback_files=args.shard_fallback_file,
        shard_payloads_file=args.shard_payloads_file,
        shard_scan=args.shard_scan,
        collect_all_shards=collect_all_shards,
        allow_existing_review=True,
    )


def _build_recovery_review_rows(
    plan: RecoveryPlan,
    args: RecoverArgs,
) -> list[tuple[str, str | None]]:
    """Build the recovery review table rows."""
    key_method = "printed shard documents" if plan.shard_frames else "passphrase"
    auth_label = format_auth_status(plan.auth_status, allow_unsigned=plan.allow_unsigned)

    review_rows: list[tuple[str, str | None]] = []
    review_rows.append(("Inputs", None))
    if plan.input_label:
        detail = (
            f"{plan.input_label}: {plan.input_detail}" if plan.input_detail else plan.input_label
        )
        review_rows.append(("Input source", detail))
    review_rows.append(("Backup text lines", str(len(plan.main_frames))))
    auth_frames_label = str(len(plan.auth_frames)) if plan.auth_frames else "none"
    review_rows.append(("Verification text lines", auth_frames_label))
    review_rows.append(("Keys", None))
    review_rows.append(("Auth verification", auth_label))
    review_rows.append(("Unlock method", key_method))
    review_rows.extend(_recovery_replay_target_review_rows(plan))

    if plan.shard_frames:
        shard_sources = []
        if plan.shard_fallback_files:
            shard_sources.append(f"{len(plan.shard_fallback_files)} fallback file(s)")
        if plan.shard_payloads_file:
            shard_sources.append(f"{len(plan.shard_payloads_file)} text file(s)")
        if plan.shard_scan:
            shard_sources.append(f"{len(plan.shard_scan)} scan path(s)")
        shard_label = ", ".join(shard_sources) if shard_sources else "provided"
        review_rows.append(
            ("Printed shard documents", f"{len(plan.shard_frames)} shard(s), {shard_label}")
        )

    if plan.allow_unsigned:
        review_rows.append(("Allow unsigned", "yes"))

    review_rows.append(("Output", None))
    output_label = args.output or "prompt after recovery"
    review_rows.append(("Output target", output_label))

    return review_rows


def _recovery_replay_target_review_rows(
    plan: RecoveryPlan,
) -> list[tuple[str, str]]:
    expected_head_doc_hash = plan.expected_head_doc_hash
    rows: list[tuple[str, str]] = []
    extension_index = plan.extension_index
    extension_doc_hash = plan.extension_doc_hash
    import_documents = plan.import_documents

    if extension_index == 0:
        rows.append(("Replay target", "root backup only (extension 0)"))
    elif extension_index is not None:
        rows.append(("Replay target", f"extension {extension_index} (explicit selection)"))
        rows.append(("Freshness scope", "supplied carriers only"))
    elif extension_doc_hash is not None:
        rows.append(("Replay target", "extension doc hash (explicit selection)"))
        rows.append(("Target doc hash", str(extension_doc_hash)))
        rows.append(("Freshness scope", "supplied carriers only"))
    elif len(import_documents) > 1:
        rows.append(
            (
                "Replay target",
                "latest supplied authenticated extension (default; verified after decrypt)",
            )
        )
        rows.append(("Freshness scope", "supplied carriers only"))

    if expected_head_doc_hash:
        rows.append(("Expected head", str(expected_head_doc_hash)))
    return rows


def _recommended_retry_stage(exc: Exception) -> str:
    message = str(exc).lower()
    key_markers = (
        "passphrase",
        "shard",
        "decryption failed",
        "invalid bip-39 mnemonic checksum",
    )
    if any(marker in message for marker in key_markers):
        return "keys"
    return "input"


def _prompt_recovery_retry_stage(exc: Exception) -> str:
    recommended = _recommended_retry_stage(exc)
    choices = {
        "input": "Edit recovery input",
        "keys": "Edit unlock information",
        "cancel": "Cancel recovery",
    }
    return prompt_choice(
        "Recovery needs one more fix",
        choices,
        default=recommended,
        help_text=f"{exc} Choose what you want to fix before continuing.",
    )


def run_recover_wizard(args: RecoverArgs, *, debug: bool = False, show_header: bool = True) -> int:
    """Run the guided recovery workflow or execute directly when non-interactive."""

    quiet = args.quiet
    allow_unsigned = args.allow_unsigned
    assume_yes = args.assume_yes
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if not interactive:
        recovery_plan = plan_from_args(args)
        if recovery_plan.allow_unsigned:
            _warn("Authentication check skipped - ensure you trust the source", quiet=quiet)
        return write_plan_outputs(
            recovery_plan,
            quiet=quiet,
            debug=debug,
            debug_max_bytes=args.debug_max_bytes,
            debug_reveal_secrets=args.debug_reveal_secrets,
        )

    with ui_screen_mode(quiet=quiet):
        if show_header and not quiet:
            console.print("[title]Recover backup[/title]")

        validate_recover_args(args)
        resolve_recover_config(args)
        working_args = replace(args)

        with wizard_flow(name="Recovery", total_steps=4, quiet=quiet):
            frames: list = []
            input_label: str | None = None
            input_detail: str | None = None
            passphrase = working_args.passphrase
            shard_fallback_files = list(working_args.shard_fallback_file or [])
            shard_payloads_file = list(working_args.shard_payloads_file or [])
            shard_scan = list(working_args.shard_scan or [])
            collected_shard_frames: list[Frame] = []
            plan: RecoveryPlan | None = None
            manifest: EnvelopeManifest | None = None
            decrypted: RecoverDecryptResult | None = None
            extracted: list[tuple[ManifestFile, bytes]] = []
            output_path = working_args.output
            stage_index = 0

            while stage_index < 4:
                if stage_index == 0:
                    with wizard_stage("Input", step_number=1, density="dense"):
                        frames, input_label, input_detail = _prompt_recovery_input(
                            working_args, allow_unsigned, quiet
                        )
                    stage_index += 1
                    continue

                if stage_index == 1:
                    with wizard_stage("Keys", step_number=2, density="dense"):
                        (
                            passphrase,
                            shard_fallback_files,
                            shard_payloads_file,
                            shard_scan,
                            collected_shard_frames,
                        ) = _prompt_key_material(working_args, quiet=quiet)
                        working_args.passphrase = passphrase
                        working_args.shard_fallback_file = list(shard_fallback_files)
                        working_args.shard_payloads_file = list(shard_payloads_file)
                        working_args.shard_scan = list(shard_scan)
                    stage_index += 1
                    continue

                extra_auth_frames = _load_extra_auth_frames(working_args, allow_unsigned, quiet)
                try:
                    shard_frames = _load_shard_frames(
                        shard_fallback_files,
                        shard_payloads_file,
                        shard_scan,
                        extra_frames=collected_shard_frames,
                        quiet=quiet,
                    )
                    plan = build_recovery_plan(
                        frames=frames,
                        extra_auth_frames=extra_auth_frames,
                        shard_frames=shard_frames,
                        passphrase=passphrase,
                        allow_unsigned=allow_unsigned,
                        input_label=input_label,
                        input_detail=input_detail,
                        shard_fallback_files=shard_fallback_files,
                        shard_payloads_file=shard_payloads_file,
                        shard_scan=list(shard_scan),
                        output_path=working_args.output,
                        root_dir=None,
                        extension_index=working_args.extension_index,
                        extension_doc_hash=working_args.extension_doc_hash,
                        expected_head_doc_hash=working_args.expected_head_doc_hash,
                        args=working_args,
                        quiet=quiet,
                    )
                    if plan.allow_unsigned:
                        _warn(
                            "Authentication check skipped - ensure you trust the source",
                            quiet=quiet,
                        )
                except ValueError as exc:
                    if quiet:
                        raise
                    retry_stage = _prompt_recovery_retry_stage(exc)
                    if retry_stage == "cancel":
                        console.print("Recovery cancelled.")
                        return 1
                    stage_index = 0 if retry_stage == "input" else 1
                    continue

                if stage_index == 2:
                    with wizard_stage("Review", step_number=3):
                        review_rows = _build_recovery_review_rows(plan, working_args)
                        if not quiet:
                            console.print(panel("Review", build_review_table(review_rows)))
                        if not assume_yes and not prompt_yes_no(
                            "Decrypt and preview recovered files",
                            default=True,
                            help_text="Select no to stop here without decrypting.",
                        ):
                            console.print("Recovery cancelled.")
                            return 1
                    try:
                        decrypted = decrypt_manifest_extract_selection(
                            plan, quiet=quiet, debug=debug
                        )
                        manifest = decrypted.manifest
                        extracted = decrypted.extracted
                    except ValueError as exc:
                        if quiet:
                            raise
                        retry_stage = _prompt_recovery_retry_stage(exc)
                        if retry_stage == "cancel":
                            console.print("Recovery cancelled.")
                            return 1
                        stage_index = 0 if retry_stage == "input" else 1
                        continue
                    if debug:
                        print_recover_debug(
                            manifest=manifest,
                            extracted=extracted,
                            ciphertext=plan.ciphertext,
                            passphrase=plan.passphrase,
                            auth_status=plan.auth_status,
                            allow_unsigned=plan.allow_unsigned,
                            output_path=working_args.output,
                            debug_max_bytes=args.debug_max_bytes,
                            reveal_secrets=args.debug_reveal_secrets,
                        )
                    stage_index += 1
                    continue

                with wizard_stage("Output", step_number=4, density="dense"):
                    assert plan is not None
                    assert manifest is not None
                    with wizard_substep("Choose output"):
                        output_path = _resolve_recover_output(
                            extracted,
                            working_args.output,
                            interactive=True,
                            doc_id=plan.doc_id,
                            input_origin=manifest.input_origin,
                            input_roots=manifest.input_roots,
                        )
                    working_args.output = output_path
                    with wizard_substep("Confirm"):
                        should_write = assume_yes or prompt_yes_no(
                            "Write recovered files",
                            default=True,
                            help_text="Select no to stop here without writing files.",
                        )
                    if not should_write:
                        console.print("Recovery cancelled.")
                        return 1
                break

            assert plan is not None
            assert manifest is not None
            assert decrypted is not None

            single_entry_output_is_directory = (
                output_path is not None
                and len(extracted) == 1
                and manifest.input_origin in {"directory", "mixed"}
            )
            single_entry_output_is_directory = _single_entry_uses_directory_output(
                output_path,
                single_entry_output_is_directory=single_entry_output_is_directory,
            )
            write_recovered_outputs(
                extracted,
                output_path=output_path,
                auth_status=plan.auth_status,
                allow_unsigned=plan.allow_unsigned,
                quiet=quiet,
                single_entry_output_is_directory=single_entry_output_is_directory,
                requested_extension_index=plan.extension_index,
                requested_extension_doc_hash=plan.extension_doc_hash,
                expected_head_doc_hash=plan.expected_head_doc_hash,
                selected_extension_index=decrypted.selected_extension_index,
                selected_extension_doc_hash=decrypted.selected_extension_doc_hash,
            )
            return 0


def _load_extra_auth_frames(args: RecoverArgs, allow_unsigned: bool, quiet: bool) -> list:
    """Load extra auth frames from files."""
    extra_auth_frames = []
    if args.auth_fallback_file:
        try:
            extra_auth_frames.extend(
                _auth_frames_from_fallback(
                    args.auth_fallback_file,
                    allow_invalid_auth=allow_unsigned,
                    quiet=quiet,
                )
            )
        except ValueError as exc:
            raise ValueError(format_fallback_error(exc, context="Auth recovery text")) from exc
    if args.auth_payloads_file:
        extra_auth_frames.extend(_auth_frames_from_payloads(args.auth_payloads_file))
    return extra_auth_frames


def _load_shard_frames(
    shard_fallback_files: list[str],
    shard_payloads_file: list[str],
    shard_scan: list[str],
    extra_frames: list[Frame] | None,
    quiet: bool,
) -> list[Frame]:
    """Load shard frames from files or pasted input."""
    if not shard_fallback_files and not shard_payloads_file and not shard_scan and not extra_frames:
        return []
    shard_frames = list(extra_frames or [])
    if shard_frames and (shard_fallback_files or shard_payloads_file or shard_scan):
        return shard_frames
    total_files = len(shard_fallback_files) + len(shard_payloads_file) + len(shard_scan)
    if total_files:
        with status(f"Reading {total_files} shard file(s)...", quiet=quiet):
            for path in shard_fallback_files:
                try:
                    shard_frames.append(_frame_from_fallback(path, quiet=quiet))
                except ValueError as exc:
                    raise ValueError(
                        format_fallback_error(exc, context="Shard recovery text")
                    ) from exc
            for path in shard_payloads_file:
                try:
                    shard_frames.extend(_frames_from_payloads(path, label="shard text lines"))
                except ValueError as exc:
                    raise ValueError(format_shard_input_error(exc)) from exc
            if shard_scan:
                try:
                    shard_frames.extend(shard_frames_from_scan(shard_scan, quiet=quiet))
                except ValueError as exc:
                    raise ValueError(format_shard_input_error(exc)) from exc
    if not shard_frames:
        raise ValueError(
            "No valid shard data found in provided files.\n"
            "  - Check that files contain shard recovery text or shard text lines\n"
            "  - PDFs/images are scanned for shard text lines automatically\n"
            "  - Ensure each shard file has valid content"
        )
    return shard_frames


def write_plan_outputs(
    plan,
    *,
    quiet: bool,
    debug: bool = False,
    debug_max_bytes: int = 0,
    debug_reveal_secrets: bool = False,
) -> int:
    """Decrypt and write outputs for an already reviewed recovery plan."""

    decrypted = decrypt_manifest_extract_selection(plan, quiet=quiet, debug=debug)
    manifest = decrypted.manifest
    extracted = decrypted.extracted
    if debug:
        print_recover_debug(
            manifest=manifest,
            extracted=extracted,
            ciphertext=plan.ciphertext,
            passphrase=plan.passphrase,
            auth_status=plan.auth_status,
            allow_unsigned=plan.allow_unsigned,
            output_path=plan.output_path,
            debug_max_bytes=debug_max_bytes,
            reveal_secrets=debug_reveal_secrets,
        )
    single_entry_output_is_directory = (
        plan.output_path is not None
        and len(extracted) == 1
        and manifest.input_origin in {"directory", "mixed"}
    )
    single_entry_output_is_directory = _single_entry_uses_directory_output(
        plan.output_path,
        single_entry_output_is_directory=single_entry_output_is_directory,
    )
    write_recovered_outputs(
        extracted,
        output_path=plan.output_path,
        auth_status=plan.auth_status,
        allow_unsigned=plan.allow_unsigned,
        quiet=quiet,
        single_entry_output_is_directory=single_entry_output_is_directory,
        requested_extension_index=getattr(plan, "extension_index", None),
        requested_extension_doc_hash=getattr(plan, "extension_doc_hash", None),
        expected_head_doc_hash=getattr(plan, "expected_head_doc_hash", None),
        selected_extension_index=decrypted.selected_extension_index,
        selected_extension_doc_hash=decrypted.selected_extension_doc_hash,
    )
    return 0
