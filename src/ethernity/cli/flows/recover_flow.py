#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from ...config import load_app_config
from ...crypto import decrypt_bytes
from ...encoding.chunking import reassemble_payload
from ...encoding.framing import Frame, FrameType
from ...formats.envelope_codec import decode_envelope, extract_payloads
from ...qr.scan import QrScanError
from ..api import (
    build_review_table,
    console,
    console_err,
    panel,
    print_completion_panel,
    prompt_choice,
    prompt_required_path,
    prompt_required_secret,
    prompt_yes_no,
    status,
    wizard_flow,
    wizard_stage,
)
from ..core.crypto import _doc_hash_from_ciphertext, _doc_id_from_ciphertext
from ..core.log import _warn
from ..io.frames import (
    _auth_frames_from_fallback,
    _auth_frames_from_payloads,
    _dedupe_auth_frames,
    _dedupe_frames,
    _frames_from_fallback,
    _frames_from_payloads,
    _frames_from_scan,
    _frames_from_shard_inputs,
    _split_main_and_auth_frames,
)
from ..io.outputs import _write_recovered_outputs
from ..keys.recover_keys import (
    _passphrase_from_shard_frames,
    _resolve_auth_payload,
    _resolve_recovery_keys,
)
from ..ui.summary import format_auth_status, print_recover_summary
from .prompts import _prompt_shard_inputs, _resolve_recover_output


def run_recover_command(args: argparse.Namespace) -> int:
    config_path = getattr(args, "config", None)
    paper = getattr(args, "paper", None)
    if config_path and paper:
        raise ValueError("use either --config or --paper, not both")
    config = load_app_config(config_path, paper_size=paper)
    qr_payload_encoding = config.qr_payload_encoding

    if args.fallback_file and args.frames_file:
        raise ValueError("use either --fallback-file or --frames-file, not both")
    if args.scan and (args.fallback_file or args.frames_file):
        raise ValueError("use either --scan or --fallback-file/--frames-file, not both")

    shard_fallback_files = list(getattr(args, "shard_fallback_file", []) or [])
    shard_frame_files = list(getattr(args, "shard_frames_file", []) or [])
    shard_frames_encoding = getattr(args, "shard_frames_encoding", "auto")

    quiet = bool(getattr(args, "quiet", False))
    allow_unsigned = bool(getattr(args, "allow_unsigned", False))
    if allow_unsigned:
        _warn("allow-unsigned disables auth verification", quiet=quiet)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    assume_yes = bool(getattr(args, "assume_yes", False))
    frames: list[Frame] | None = None
    input_label: str | None = None
    input_detail: str | None = None

    auth_fallback_file = getattr(args, "auth_fallback_file", None)
    auth_frames_file = getattr(args, "auth_frames_file", None)
    auth_frames_encoding = getattr(args, "auth_frames_encoding", "auto")

    if auth_fallback_file and auth_frames_file:
        raise ValueError("use either --auth-fallback-file or --auth-frames-file, not both")

    flow_quiet = quiet or not interactive
    with wizard_flow(name="Recovery", total_steps=4, quiet=flow_quiet):
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
            elif interactive:
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
                    except (OSError, ValueError, QrScanError) as exc:
                        console_err.print(f"[error]{exc}[/error]")
                        frames = None
                        continue
                    break
            else:
                raise ValueError("either --fallback-file, --frames-file, or --scan is required")

        if not frames:
            hint = "Check the input path and try again."
            if input_label == "Scan":
                hint = "Check the scan path and image quality, then try again."
            raise ValueError(f"no frames found. {hint}")

        frames = _dedupe_frames(frames)
        main_frames, auth_frames = _split_main_and_auth_frames(frames)
        extra_auth_frames: list[Frame] = []
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
        if extra_auth_frames:
            auth_frames = _dedupe_auth_frames([*auth_frames, *extra_auth_frames])
        ciphertext = reassemble_payload(main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
        doc_id = _doc_id_from_ciphertext(ciphertext)
        doc_hash = _doc_hash_from_ciphertext(ciphertext)
        prompted_for_keys = False
        passphrase: str | None = None

        with wizard_stage(
            "Key material",
            help_text="Select the key material needed to decrypt the backup.",
        ):
            if (
                interactive
                and not shard_fallback_files
                and not shard_frame_files
                and not args.passphrase
            ):
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
                    prompted_for_keys = True
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
        shard_frames: list[Frame] = []
        if shard_fallback_files or shard_frame_files:
            with status("Reading shard inputs...", quiet=quiet):
                shard_frames = _frames_from_shard_inputs(
                    shard_fallback_files,
                    shard_frame_files,
                    shard_frames_encoding,
                )
            if not shard_frames:
                raise ValueError("no shard frames found; check shard inputs and try again")

        if shard_frames and args.passphrase:
            raise ValueError("use either shard inputs or passphrase, not both")

        with status("Verifying auth payload...", quiet=quiet):
            auth_payload, authstatus = _resolve_auth_payload(
                auth_frames,
                doc_id=doc_id,
                doc_hash=doc_hash,
                allow_unsigned=allow_unsigned,
                require_auth=not allow_unsigned and not shard_frames,
                quiet=quiet,
            )
        sign_pub = auth_payload.sign_pub if auth_payload else None

        if shard_frames:
            with status("Reconstructing passphrase from shards...", quiet=quiet):
                passphrase = _passphrase_from_shard_frames(
                    shard_frames,
                    expected_doc_id=doc_id,
                    expected_doc_hash=doc_hash,
                    expected_sign_pub=sign_pub,
                    allow_unsigned=allow_unsigned,
                )
        elif not prompted_for_keys:
            passphrase = _resolve_recovery_keys(args)

        if interactive and not quiet:
            with wizard_stage(
                "Review & confirm",
                help_text="Confirm the recovery plan before decrypting.",
            ):
                key_method = "passphrase" if passphrase else "missing"
                if shard_frames:
                    key_method = "shard documents"
                auth_label = format_auth_status(authstatus, allow_unsigned=allow_unsigned)
                review_rows: list[tuple[str, str]] = []
                if input_label:
                    detail = f"{input_label}: {input_detail}" if input_detail else input_label
                    review_rows.append(("Input", detail))
                review_rows.append(("Main frames", str(len(main_frames))))
                review_rows.append(
                    ("Auth frames", str(len(auth_frames)) if auth_frames else "none")
                )
                review_rows.append(("Auth verification", auth_label))
                review_rows.append(("Key material", key_method))
                if shard_frames:
                    shard_count = len(shard_frames)
                    shard_sources = []
                    if shard_fallback_files:
                        shard_sources.append(f"{len(shard_fallback_files)} fallback file(s)")
                    if shard_frame_files:
                        shard_sources.append(f"{len(shard_frame_files)} frame file(s)")
                    shard_label = ", ".join(shard_sources) if shard_sources else "provided"
                    review_rows.append(("Shard inputs", f"{shard_count} frame(s), {shard_label}"))
                output_label = args.output or ("prompt after recovery" if interactive else "stdout")
                review_rows.append(("Output", output_label))
                if allow_unsigned:
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

    with status("Decrypting and unpacking payload...", quiet=quiet):
        if not passphrase:
            raise ValueError("passphrase is required for recovery")
        plaintext = decrypt_bytes(ciphertext, passphrase=passphrase)

        manifest, payload = decode_envelope(plaintext)
        extracted = extract_payloads(manifest, payload)
    if interactive:
        with wizard_stage(
            "Output",
            help_text="Choose where recovered files should be written.",
        ):
            output_path = _resolve_recover_output(
                extracted,
                args.output,
                interactive=interactive,
                doc_id=doc_id,
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
    else:
        output_path = _resolve_recover_output(
            extracted,
            args.output,
            interactive=interactive,
            doc_id=doc_id,
        )
    _write_recovered_outputs(output_path, extracted, quiet=quiet)
    auth_label = format_auth_status(authstatus, allow_unsigned=allow_unsigned)
    print_recover_summary(extracted, output_path, auth_status=auth_label, quiet=quiet)
    if not quiet:
        actions = ["Verify recovered files match your originals."]
        if output_path:
            actions.append("Store the recovered files somewhere secure.")
        else:
            actions.append("Save stdout output if you need to keep the recovered data.")
        print_completion_panel("Recovery complete", actions, quiet=quiet, use_err=True)
    return 0
