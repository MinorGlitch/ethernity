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

from __future__ import annotations

import sys

from ...encoding.framing import Frame
from ..api import (
    build_review_table,
    console,
    panel,
    prompt_choice,
    prompt_required_secret,
    prompt_yes_no,
    status,
    ui_screen_mode,
    wizard_flow,
    wizard_stage,
)
from ..core.log import _warn
from ..core.types import RecoverArgs
from ..io.fallback_parser import format_fallback_error
from ..io.frames import (
    _auth_frames_from_fallback,
    _auth_frames_from_payloads,
    _frames_from_fallback,
    _frames_from_payloads,
    _frames_from_scan,
    _frames_from_shard_inputs,
)
from ..ui.debug import print_recover_debug
from ..ui.summary import format_auth_status
from .prompts import _prompt_shard_inputs, _resolve_recover_output
from .recover_flow import decrypt_manifest_and_extract, write_recovered_outputs
from .recover_input import (
    collect_fallback_frames,
    collect_payload_frames,
    prompt_recovery_input_interactive,
)
from .recover_plan import (
    build_recovery_plan,
    plan_from_args,
    resolve_recover_config,
    validate_recover_args,
)


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
        input_label = "QR payloads"
        input_detail = args.payloads_file
        if args.payloads_file == "-" and sys.stdin.isatty():
            input_detail = "stdin"
            frames = collect_payload_frames(
                allow_unsigned=allow_unsigned,
                quiet=quiet,
            )
        else:
            with status("Reading QR payloads...", quiet=quiet):
                frames = _frames_from_payloads(
                    args.payloads_file,
                    label="frame",
                )
    elif args.scan:
        input_label = "Scan"
        input_detail = ", ".join(args.scan)
        with status("Scanning QR images...", quiet=quiet):
            frames = _frames_from_scan(args.scan)
    else:
        frames, input_label, input_detail = prompt_recovery_input_interactive(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
        )

    return frames or [], input_label, input_detail


def _prompt_key_material(
    args: RecoverArgs,
    *,
    quiet: bool,
) -> tuple[str | None, list[str], list[str], list[Frame]]:
    """Prompt for key material.

    Returns (passphrase, shard_fallback_files, shard_payloads_file, pasted_shard_frames).
    """
    passphrase = args.passphrase
    shard_fallback_files = list(args.shard_fallback_file or [])
    shard_payloads_file = list(args.shard_payloads_file or [])
    pasted_shard_frames: list[Frame] = []

    if not shard_fallback_files and not shard_payloads_file and not passphrase:
        while True:
            key_choice = prompt_choice(
                "How will you decrypt",
                {
                    "passphrase": "I have the passphrase",
                    "shards": "I have shard documents",
                },
                default="passphrase",
                help_text="Choose based on what key material you have available.",
            )
            if key_choice == "passphrase":
                passphrase = prompt_required_secret(
                    "Enter passphrase",
                    help_text="This is the passphrase used to encrypt the backup.",
                )
                break
            (
                shard_fallback_files,
                shard_payloads_file,
                pasted_shard_frames,
            ) = _prompt_shard_inputs(quiet=quiet)
            break

    return (
        passphrase,
        shard_fallback_files,
        shard_payloads_file,
        pasted_shard_frames,
    )


def _build_recovery_review_rows(
    plan,
    args: RecoverArgs,
) -> list[tuple[str, str | None]]:
    """Build the recovery review table rows."""
    key_method = "shard documents" if plan.shard_frames else "passphrase"
    auth_label = format_auth_status(plan.auth_status, allow_unsigned=plan.allow_unsigned)

    review_rows: list[tuple[str, str | None]] = []
    review_rows.append(("Inputs", None))
    if plan.input_label:
        detail = (
            f"{plan.input_label}: {plan.input_detail}" if plan.input_detail else plan.input_label
        )
        review_rows.append(("Input source", detail))
    review_rows.append(("Main QR payloads", str(len(plan.main_frames))))
    auth_frames_label = str(len(plan.auth_frames)) if plan.auth_frames else "none"
    review_rows.append(("Auth QR payloads", auth_frames_label))
    review_rows.append(("Keys", None))
    review_rows.append(("Auth verification", auth_label))
    review_rows.append(("Key material", key_method))

    if plan.shard_frames:
        shard_sources = []
        if plan.shard_fallback_files:
            shard_sources.append(f"{len(plan.shard_fallback_files)} fallback file(s)")
        if plan.shard_payloads_file:
            shard_sources.append(f"{len(plan.shard_payloads_file)} payload file(s)")
        shard_label = ", ".join(shard_sources) if shard_sources else "provided"
        review_rows.append(("Shard inputs", f"{len(plan.shard_frames)} payload(s), {shard_label}"))

    if plan.allow_unsigned:
        review_rows.append(("Allow unsigned", "yes"))

    review_rows.append(("Output", None))
    output_label = args.output or "prompt after recovery"
    review_rows.append(("Output target", output_label))

    return review_rows


def run_recover_wizard(args: RecoverArgs, *, debug: bool = False, show_header: bool = True) -> int:
    quiet = args.quiet
    allow_unsigned = args.allow_unsigned
    assume_yes = args.assume_yes
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if not interactive:
        if (
            not args.fallback_file
            and not args.payloads_file
            and not (args.scan or [])
            and not sys.stdin.isatty()
        ):
            args.fallback_file = "-"
        plan = plan_from_args(args)
        if plan.allow_unsigned:
            _warn("Authentication check skipped - ensure you trust the source", quiet=quiet)
        return write_plan_outputs(
            plan,
            quiet=quiet,
            debug=debug,
            debug_max_bytes=args.debug_max_bytes,
            debug_reveal_secrets=args.debug_reveal_secrets,
        )

    with ui_screen_mode(quiet=quiet):
        if show_header and not quiet:
            console.print("[title]Ethernity recovery wizard[/title]")
            console.print("[subtitle]Guided recovery of backup documents.[/subtitle]")

        validate_recover_args(args)
        resolve_recover_config(args)

        with wizard_flow(name="Recovery", total_steps=4, quiet=quiet):
            with wizard_stage("Input"):
                frames, input_label, input_detail = _prompt_recovery_input(
                    args, allow_unsigned, quiet
                )

            extra_auth_frames = _load_extra_auth_frames(args, allow_unsigned, quiet)

            with wizard_stage("Keys"):
                (
                    passphrase,
                    shard_fallback_files,
                    shard_payloads_file,
                    pasted_shard_frames,
                ) = _prompt_key_material(args, quiet=quiet)

            shard_frames = _load_shard_frames(
                shard_fallback_files,
                shard_payloads_file,
                extra_frames=pasted_shard_frames,
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
                output_path=args.output,
                args=args,
                quiet=quiet,
            )
            if plan.allow_unsigned:
                _warn("Authentication check skipped - ensure you trust the source", quiet=quiet)

            if not quiet:
                with wizard_stage("Review"):
                    review_rows = _build_recovery_review_rows(plan, args)
                    console.print(panel("Review", build_review_table(review_rows)))
                    if not assume_yes and not prompt_yes_no(
                        "Proceed with recovery",
                        default=True,
                        help_text="Select no to cancel.",
                    ):
                        console.print("Recovery cancelled.")
                        return 1

            manifest, extracted = decrypt_manifest_and_extract(plan, quiet=quiet, debug=debug)
            if debug:
                print_recover_debug(
                    manifest=manifest,
                    extracted=extracted,
                    ciphertext=plan.ciphertext,
                    passphrase=plan.passphrase,
                    auth_status=plan.auth_status,
                    allow_unsigned=plan.allow_unsigned,
                    output_path=args.output,
                    debug_max_bytes=args.debug_max_bytes,
                    reveal_secrets=args.debug_reveal_secrets,
                )

            with wizard_stage("Output"):
                output_path = _resolve_recover_output(
                    extracted,
                    args.output,
                    interactive=True,
                    doc_id=plan.doc_id,
                    input_origin=manifest.input_origin,
                    input_roots=manifest.input_roots,
                )
                if not assume_yes and not prompt_yes_no(
                    "Proceed with writing files",
                    default=True,
                    help_text="Select no to cancel.",
                ):
                    console.print("Recovery cancelled.")
                    return 1

            single_entry_output_is_directory = (
                output_path is not None
                and len(extracted) == 1
                and manifest.input_origin in {"directory", "mixed"}
            )
            write_recovered_outputs(
                extracted,
                output_path=output_path,
                auth_status=plan.auth_status,
                allow_unsigned=plan.allow_unsigned,
                quiet=quiet,
                single_entry_output_is_directory=single_entry_output_is_directory,
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
    extra_frames: list[Frame] | None,
    quiet: bool,
) -> list[Frame]:
    """Load shard frames from files or pasted input."""
    if not shard_fallback_files and not shard_payloads_file and not extra_frames:
        return []
    shard_frames = list(extra_frames or [])
    total_files = len(shard_fallback_files) + len(shard_payloads_file)
    if total_files:
        with status(f"Reading {total_files} shard file(s)...", quiet=quiet):
            try:
                shard_frames.extend(
                    _frames_from_shard_inputs(
                        shard_fallback_files,
                        shard_payloads_file,
                    )
                )
            except ValueError as exc:
                raise ValueError(format_fallback_error(exc, context="Shard recovery text")) from exc
    if not shard_frames:
        raise ValueError(
            "No valid shard data found in provided files.\n"
            "  - Check that files contain shard recovery text or QR payloads\n"
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
    manifest, extracted = decrypt_manifest_and_extract(plan, quiet=quiet, debug=debug)
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
    write_recovered_outputs(
        extracted,
        output_path=plan.output_path,
        auth_status=plan.auth_status,
        allow_unsigned=plan.allow_unsigned,
        quiet=quiet,
        single_entry_output_is_directory=single_entry_output_is_directory,
    )
    return 0
