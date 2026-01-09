#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def run_recover_wizard(args: argparse.Namespace, *, show_header: bool = True) -> int:
    quiet = bool(getattr(args, "quiet", False))
    allow_unsigned = bool(getattr(args, "allow_unsigned", False))
    assume_yes = bool(getattr(args, "assume_yes", False))
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
        _warn("allow-unsigned disables auth verification", quiet=quiet)

    frames = None
    input_label: str | None = None
    input_detail: str | None = None

    auth_fallback_file = getattr(args, "auth_fallback_file", None)
    auth_frames_file = getattr(args, "auth_frames_file", None)
    auth_frames_encoding = getattr(args, "auth_frames_encoding", "auto")

    shard_fallback_files = list(getattr(args, "shard_fallback_file", []) or [])
    shard_frame_files = list(getattr(args, "shard_frames_file", []) or [])
    shard_frames_encoding = getattr(args, "shard_frames_encoding", "auto")

    passphrase = getattr(args, "passphrase", None)

    with wizard_flow(name="Recovery", total_steps=4, quiet=quiet):
        with wizard_stage(
            "Recovery input",
            help_text="Choose how to provide the recovery data.",
        ):
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
                while True:
                    choice = prompt_choice(
                        "Recovery input",
                        {
                            "fallback": "Text fallback (z-base-32)",
                            "frames": "QR frame payloads",
                            "scan": "Scan QR images/PDFs",
                        },
                        default="fallback",
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
                    except (OSError, ValueError) as exc:
                        console_err.print(f"[error]{exc}[/error]")
                        frames = None
                        continue
                    break

        extra_auth_frames = []
        if auth_fallback_file:
            extra_auth_frames.extend(
                _auth_frames_from_fallback(
                    auth_fallback_file,
                    allow_invalid_auth=allow_unsigned,
                    quiet=quiet,
                )
            )
        if auth_frames_file:
            extra_auth_frames.extend(
                _auth_frames_from_payloads(auth_frames_file, auth_frames_encoding)
            )

        with wizard_stage(
            "Key material",
            help_text="Select the key material needed to decrypt the backup.",
        ):
            if not shard_fallback_files and not shard_frame_files and not passphrase:
                while True:
                    key_choice = prompt_choice(
                        "Decryption method",
                        {
                            "passphrase": "Passphrase",
                            "shards": "Shard documents (passphrase shares)",
                        },
                        default="passphrase",
                        help_text="Pick the key material available for this backup.",
                    )
                    if key_choice == "passphrase":
                        passphrase = prompt_required_secret(
                            "Enter passphrase",
                            help_text="This is the passphrase used to encrypt the backup.",
                        )
                        break
                    shard_fallback_files, shard_frame_files, shard_frames_encoding = (
                        _prompt_shard_inputs()
                    )
                    break

        shard_frames = []
        if shard_fallback_files or shard_frame_files:
            with status("Reading shard inputs...", quiet=quiet):
                shard_frames = _frames_from_shard_inputs(
                    shard_fallback_files,
                    shard_frame_files,
                    shard_frames_encoding,
                )
            if not shard_frames:
                raise ValueError("no shard frames found; check shard inputs and try again")

        plan = build_recovery_plan(
            frames=frames or [],
            extra_auth_frames=extra_auth_frames,
            shard_frames=shard_frames,
            passphrase=passphrase,
            allow_unsigned=allow_unsigned,
            input_label=input_label,
            input_detail=input_detail,
            shard_fallback_files=shard_fallback_files,
            shard_frame_files=shard_frame_files,
            output_path=getattr(args, "output", None),
            args=args,
            quiet=quiet,
        )

        if not quiet:
            with wizard_stage(
                "Review & confirm",
                help_text="Confirm the recovery plan before decrypting.",
            ):
                key_method = "shard documents" if plan.shard_frames else "passphrase"
                auth_label = format_auth_status(
                    plan.auth_status,
                    allow_unsigned=plan.allow_unsigned,
                )
                review_rows: list[tuple[str, str]] = []
                if plan.input_label:
                    detail = (
                        f"{plan.input_label}: {plan.input_detail}"
                        if plan.input_detail
                        else plan.input_label
                    )
                    review_rows.append(("Input", detail))
                review_rows.append(("Main frames", str(len(plan.main_frames))))
                review_rows.append(
                    ("Auth frames", str(len(plan.auth_frames)) if plan.auth_frames else "none")
                )
                review_rows.append(("Auth verification", auth_label))
                review_rows.append(("Key material", key_method))
                if plan.shard_frames:
                    shard_sources = []
                    if plan.shard_fallback_files:
                        shard_sources.append(f"{len(plan.shard_fallback_files)} fallback file(s)")
                    if plan.shard_frame_files:
                        shard_sources.append(f"{len(plan.shard_frame_files)} frame file(s)")
                    shard_label = ", ".join(shard_sources) if shard_sources else "provided"
                    review_rows.append(
                        ("Shard inputs", f"{len(plan.shard_frames)} frame(s), {shard_label}")
                    )
                output_label = getattr(args, "output", None) or "prompt after recovery"
                review_rows.append(("Output", output_label))
                if plan.allow_unsigned:
                    review_rows.append(("Allow unsigned", "yes"))
                console.print(panel("Review", build_review_table(review_rows)))
                if not assume_yes:
                    if not prompt_yes_no(
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
                extracted,
                getattr(args, "output", None),
                interactive=True,
                doc_id=plan.doc_id,
            )
            if not quiet:
                output_rows = [
                    ("Recovered", f"{len(extracted)} file(s)"),
                    ("Output", output_path or "stdout"),
                ]
                console.print(panel("Output", build_review_table(output_rows)))
            if not assume_yes:
                if not prompt_yes_no(
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
