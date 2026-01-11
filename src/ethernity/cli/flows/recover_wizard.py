#!/usr/bin/env python3
from __future__ import annotations

import sys

from ..api import (
    build_review_table,
    console,
    console_err,
    panel,
    prompt_choice,
    prompt_required_path,
    prompt_required_secret,
    prompt_yes_no,
    status,
    wizard_flow,
    wizard_stage,
)
from ..core.log import _warn
from ..core.types import RecoverArgs
from ..io.frames import (
    _auth_frames_from_fallback,
    _auth_frames_from_payloads,
    _frames_from_fallback,
    _frames_from_payloads,
    _frames_from_scan,
    _frames_from_shard_inputs,
)
from ..ui.summary import format_auth_status
from .prompts import _prompt_shard_inputs, _resolve_recover_output
from .recover_flow import decrypt_and_extract, write_recovered_outputs
from .recover_plan import (
    build_recovery_plan,
    plan_from_args,
    resolve_recover_config,
    validate_recover_args,
)


def _prompt_recovery_input(
    args: RecoverArgs,
    qr_payload_encoding: str,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list, str | None, str | None]:
    """Prompt for recovery input. Returns (frames, input_label, input_detail)."""
    frames = None
    input_label: str | None = None
    input_detail: str | None = None

    if args.fallback_file:
        input_label = "Fallback text"
        input_detail = args.fallback_file
        with status("Reading fallback text...", quiet=quiet):
            frames = _frames_from_fallback(
                args.fallback_file,
                allow_invalid_auth=allow_unsigned,
                quiet=quiet,
            )
    elif args.frames_file:
        input_label = "Frame payloads"
        input_detail = args.frames_file
        with status("Reading frame payloads...", quiet=quiet):
            frames = _frames_from_payloads(
                args.frames_file,
                args.frames_encoding,
                label="frame",
            )
    elif args.scan:
        input_label = "Scan"
        input_detail = ", ".join(args.scan)
        with status("Scanning QR images...", quiet=quiet):
            frames = _frames_from_scan(args.scan, qr_payload_encoding)
    else:
        frames, input_label, input_detail = _prompt_recovery_input_interactive(
            qr_payload_encoding, allow_unsigned, quiet
        )

    return frames or [], input_label, input_detail


def _prompt_recovery_input_interactive(
    qr_payload_encoding: str,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list, str | None, str | None]:
    """Interactive prompt for recovery input method."""
    while True:
        choice = prompt_choice(
            "What do you have",
            {
                "scan": "Recovery PDF or images (Recommended - easiest)",
                "fallback": "Text copied from recovery document",
                "frames": "Extracted QR payload files",
            },
            default="scan",
            help_text="Choose how you want to provide the recovery data.",
        )
        try:
            if choice == "fallback":
                path = prompt_required_path(
                    "Fallback text file path (use - for stdin)",
                    help_text="This is the text fallback saved from the backup.",
                    kind="file",
                    allow_stdin=True,
                )
                input_label = "Fallback text"
                input_detail = path
                with status("Reading fallback text...", quiet=quiet):
                    frames = _frames_from_fallback(
                        path,
                        allow_invalid_auth=allow_unsigned,
                        quiet=quiet,
                    )
            elif choice == "frames":
                path = prompt_required_path(
                    "Frames file path (use - for stdin)",
                    help_text="Provide a file with one QR payload per line.",
                    kind="file",
                    allow_stdin=True,
                )
                encoding = prompt_choice(
                    "Frames encoding",
                    {
                        "auto": "Auto",
                        "base64": "Base64",
                        "base64url": "Base64 URL-safe",
                        "hex": "Hex",
                    },
                    default="auto",
                    help_text="How the payloads are encoded in the file.",
                )
                input_label = "Frame payloads"
                input_detail = path
                with status("Reading frame payloads...", quiet=quiet):
                    frames = _frames_from_payloads(path, encoding, label="frame")
            else:
                path = prompt_required_path(
                    "Scan path (file or directory)",
                    help_text="Point at a PDF, image, or directory of scans.",
                    kind="path",
                )
                input_label = "Scan"
                input_detail = path
                with status("Scanning QR images...", quiet=quiet):
                    frames = _frames_from_scan([path], qr_payload_encoding)
            return frames, input_label, input_detail
        except (OSError, ValueError) as exc:
            console_err.print(f"[error]{exc}[/error]")
            continue


def _prompt_key_material(
    args: RecoverArgs,
) -> tuple[str | None, list[str], list[str], str]:
    """Prompt for key material.

    Returns (passphrase, shard_fallback_files, shard_frame_files, shard_frames_encoding).
    """
    passphrase = args.passphrase
    shard_fallback_files = list(args.shard_fallback_file or [])
    shard_frame_files = list(args.shard_frames_file or [])
    shard_frames_encoding: str = args.shard_frames_encoding

    if not shard_fallback_files and not shard_frame_files and not passphrase:
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
            shard_fallback_files, shard_frame_files, shard_frames_encoding = _prompt_shard_inputs()
            break

    return passphrase, shard_fallback_files, shard_frame_files, shard_frames_encoding


def _build_recovery_review_rows(
    plan,
    args: RecoverArgs,
) -> list[tuple[str, str]]:
    """Build the recovery review table rows."""
    key_method = "shard documents" if plan.shard_frames else "passphrase"
    auth_label = format_auth_status(plan.auth_status, allow_unsigned=plan.allow_unsigned)

    review_rows: list[tuple[str, str]] = []
    if plan.input_label:
        detail = (
            f"{plan.input_label}: {plan.input_detail}" if plan.input_detail else plan.input_label
        )
        review_rows.append(("Input", detail))
    review_rows.append(("Main frames", str(len(plan.main_frames))))
    auth_frames_label = str(len(plan.auth_frames)) if plan.auth_frames else "none"
    review_rows.append(("Auth frames", auth_frames_label))
    review_rows.append(("Auth verification", auth_label))
    review_rows.append(("Key material", key_method))

    if plan.shard_frames:
        shard_sources = []
        if plan.shard_fallback_files:
            shard_sources.append(f"{len(plan.shard_fallback_files)} fallback file(s)")
        if plan.shard_frame_files:
            shard_sources.append(f"{len(plan.shard_frame_files)} frame file(s)")
        shard_label = ", ".join(shard_sources) if shard_sources else "provided"
        review_rows.append(("Shard inputs", f"{len(plan.shard_frames)} frame(s), {shard_label}"))

    output_label = args.output or "prompt after recovery"
    review_rows.append(("Output", output_label))
    if plan.allow_unsigned:
        review_rows.append(("Allow unsigned", "yes"))

    return review_rows


def run_recover_wizard(args: RecoverArgs, *, show_header: bool = True) -> int:
    quiet = args.quiet
    allow_unsigned = args.allow_unsigned
    assume_yes = args.assume_yes
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if not interactive:
        plan = plan_from_args(args)
        return write_plan_outputs(plan, quiet=quiet)

    if show_header and not quiet:
        console.print("[title]Ethernity recovery wizard[/title]")
        console.print("[subtitle]Interactive recovery of backup documents.[/subtitle]")

    validate_recover_args(args)
    _, qr_payload_encoding = resolve_recover_config(args)
    if allow_unsigned:
        _warn("Authentication check skipped - ensure you trust the source", quiet=quiet)

    with wizard_flow(name="Recovery", total_steps=4, quiet=quiet):
        with wizard_stage(
            "Recovery input",
            help_text="Choose how to provide the recovery data.",
        ):
            frames, input_label, input_detail = _prompt_recovery_input(
                args, qr_payload_encoding, allow_unsigned, quiet
            )

        extra_auth_frames = _load_extra_auth_frames(args, allow_unsigned, quiet)

        with wizard_stage(
            "Key material",
            help_text="Select the key material needed to decrypt the backup.",
        ):
            passphrase, shard_fallback_files, shard_frame_files, shard_frames_encoding = (
                _prompt_key_material(args)
            )

        shard_frames = _load_shard_frames(
            shard_fallback_files,
            shard_frame_files,
            shard_frames_encoding,
            quiet,
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
            shard_frame_files=shard_frame_files,
            output_path=args.output,
            args=args,
            quiet=quiet,
        )

        if not quiet:
            with wizard_stage(
                "Review & confirm",
                help_text="Confirm the recovery plan before decrypting.",
            ):
                review_rows = _build_recovery_review_rows(plan, args)
                console.print(panel("Review", build_review_table(review_rows)))
                if not assume_yes and not prompt_yes_no(
                    "Proceed with recovery",
                    default=True,
                    help_text="Select no to exit without writing any files.",
                ):
                    console.print("Recovery cancelled.")
                    return 1

        extracted = decrypt_and_extract(plan, quiet=quiet)

        with wizard_stage(
            "Output",
            help_text="Choose where recovered files should be written.",
        ):
            output_path = _resolve_recover_output(
                extracted, args.output, interactive=True, doc_id=plan.doc_id
            )
            if not quiet:
                output_rows = [
                    ("Recovered", f"{len(extracted)} file(s)"),
                    ("Output", output_path or "stdout"),
                ]
                console.print(panel("Output", build_review_table(output_rows)))
            if not assume_yes and not prompt_yes_no(
                "Write recovered files now",
                default=True,
                help_text="Select no to exit without writing any files.",
            ):
                console.print("Recovery cancelled.")
                return 1

        write_recovered_outputs(
            extracted,
            output_path=output_path,
            auth_status=plan.auth_status,
            allow_unsigned=plan.allow_unsigned,
            quiet=quiet,
        )
        return 0


def _load_extra_auth_frames(args: RecoverArgs, allow_unsigned: bool, quiet: bool) -> list:
    """Load extra auth frames from files."""
    extra_auth_frames = []
    if args.auth_fallback_file:
        extra_auth_frames.extend(
            _auth_frames_from_fallback(
                args.auth_fallback_file,
                allow_invalid_auth=allow_unsigned,
                quiet=quiet,
            )
        )
    if args.auth_frames_file:
        extra_auth_frames.extend(
            _auth_frames_from_payloads(args.auth_frames_file, args.auth_frames_encoding)
        )
    return extra_auth_frames


def _load_shard_frames(
    shard_fallback_files: list[str],
    shard_frame_files: list[str],
    shard_frames_encoding: str,
    quiet: bool,
) -> list:
    """Load shard frames from files."""
    if not shard_fallback_files and not shard_frame_files:
        return []
    total_files = len(shard_fallback_files) + len(shard_frame_files)
    with status(f"Reading {total_files} shard file(s)...", quiet=quiet):
        shard_frames = _frames_from_shard_inputs(
            shard_fallback_files, shard_frame_files, shard_frames_encoding
        )
    if not shard_frames:
        raise ValueError(
            "No valid shard data found in provided files.\n"
            "  - Check that files contain shard text or payload data\n"
            "  - Verify encoding matches how files were saved\n"
            "  - Ensure each shard file has valid content"
        )
    return shard_frames


def write_plan_outputs(plan, *, quiet: bool) -> int:
    extracted = decrypt_and_extract(plan, quiet=quiet)
    write_recovered_outputs(
        extracted,
        output_path=plan.output_path,
        auth_status=plan.auth_status,
        allow_unsigned=plan.allow_unsigned,
        quiet=quiet,
    )
    return 0
