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

from ...encoding.framing import Frame, FrameType
from ..api import (
    build_review_table,
    console,
    console_err,
    panel,
    prompt_choice,
    prompt_multiline,
    prompt_path_with_picker,
    prompt_required,
    prompt_required_secret,
    prompt_yes_no,
    status,
    wizard_flow,
    wizard_stage,
)
from ..core.log import _warn
from ..core.types import RecoverArgs
from ..io.fallback_parser import contains_fallback_markers, format_fallback_error
from ..io.frames import (
    _auth_frames_from_fallback,
    _auth_frames_from_payloads,
    _frame_from_payload_text,
    _frames_from_fallback,
    _frames_from_fallback_lines,
    _frames_from_payload_lines,
    _frames_from_payloads,
    _frames_from_scan,
    _frames_from_shard_inputs,
    _read_text_lines,
    format_recovery_input_error,
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
        input_label = "Recovery text"
        input_detail = args.fallback_file
        if args.fallback_file == "-" and sys.stdin.isatty():
            input_detail = "stdin"
            frames = _prompt_fallback_lines_until_complete(
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
            frames = _prompt_frame_payloads_until_complete(
                allow_unsigned=allow_unsigned,
                quiet=quiet,
            )
        else:
            with status("Reading QR payloads...", quiet=quiet):
                frames = _frames_from_payloads(
                    args.payloads_file,
                    "auto",
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
                "scan": "Recovery PDF or images (recommended)",
                "text": "Recovery text or QR payloads (file or paste)",
            },
            default="scan",
            help_text="Choose how you want to provide the recovery data.",
        )
        try:
            if choice == "text":
                path = prompt_path_with_picker(
                    "Recovery text or QR payloads file path (or '-' to paste)",
                    help_text="Provide recovery text or QR payloads; enter '-' to paste.",
                    kind="file",
                    allow_stdin=True,
                    picker_prompt="Select a recovery text or payload file",
                )
                input_detail = "stdin" if path == "-" else path
                if path == "-":
                    frames, input_label = _prompt_text_or_payloads_stdin(
                        allow_unsigned=allow_unsigned,
                        quiet=quiet,
                    )
                else:
                    with status("Reading recovery input...", quiet=quiet):
                        lines = _read_text_lines(path)
                        frames, input_label = _frames_from_recovery_lines(
                            lines,
                            allow_unsigned=allow_unsigned,
                            quiet=quiet,
                            source=path,
                        )
            else:
                path = prompt_path_with_picker(
                    "Scan path (file or directory)",
                    help_text="Point at a PDF, image, or directory of scans.",
                    kind="path",
                    picker_prompt="Select a scan file or folder",
                )
                input_label = "Scan"
                input_detail = path
                with status("Scanning QR images...", quiet=quiet):
                    frames = _frames_from_scan([path], qr_payload_encoding)
            return frames, input_label, input_detail
        except (OSError, ValueError) as exc:
            console_err.print(f"[error]{format_recovery_input_error(exc)}[/error]")
            continue


def _frames_from_recovery_lines(
    lines: list[str],
    *,
    allow_unsigned: bool,
    quiet: bool,
    source: str,
) -> tuple[list[Frame], str]:
    if contains_fallback_markers(lines):
        try:
            frames = _frames_from_fallback_lines(
                lines,
                allow_invalid_auth=allow_unsigned,
                quiet=quiet,
            )
        except ValueError as exc:
            message = format_fallback_error(exc, context="Recovery text")
            raise ValueError(f"invalid recovery text in {source}: {message}") from exc
        return frames, "Recovery text"

    errors: list[str] = []
    try:
        frames = _frames_from_fallback_lines(
            lines,
            allow_invalid_auth=allow_unsigned,
            quiet=quiet,
        )
        return frames, "Recovery text"
    except ValueError as exc:
        errors.append(format_fallback_error(exc, context="Recovery text"))

    try:
        frames = _frames_from_payload_lines(lines, "auto", label="QR payloads", source=source)
        return frames, "QR payloads"
    except ValueError as exc:
        errors.append(str(exc))
        detail = "; ".join(errors)
        raise ValueError(f"unable to parse recovery text from {source}: {detail}") from exc


def _prompt_text_or_payloads_stdin(
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list[Frame], str]:
    first_line = prompt_required(
        "Recovery text or QR payload (first line or block)",
        help_text="Paste recovery text or a QR payload; we'll keep asking until it decodes.",
    )
    if "\n" in first_line or "\r" in first_line:
        lines = [line for line in first_line.splitlines() if line.strip()]
        frames = _prompt_fallback_lines_until_complete(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            initial_lines=lines,
        )
        return frames, "Recovery text"

    if contains_fallback_markers([first_line]):
        frames = _prompt_fallback_lines_until_complete(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            initial_lines=[first_line],
        )
        return frames, "Recovery text"

    try:
        first_frame = _frame_from_payload_text(first_line, "auto")
    except ValueError:
        frames = _prompt_fallback_lines_until_complete(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            initial_lines=[first_line],
        )
        return frames, "Recovery text"

    frames = _prompt_frame_payloads_until_complete(
        allow_unsigned=allow_unsigned,
        quiet=quiet,
        first_frame=first_frame,
    )
    return frames, "QR payloads"


def _prompt_fallback_lines_until_complete(
    *,
    allow_unsigned: bool,
    quiet: bool,
    initial_lines: list[str] | None,
) -> list[Frame]:
    lines = list(initial_lines or [])
    help_text: str | None = (
        "Paste recovery text (fallback). "
        "You can paste in batches; we'll keep asking until it decodes."
    )
    prompt_label = "Paste recovery text (blank line ends a batch)"

    if lines:
        try:
            with status("Reading recovery text...", quiet=quiet):
                return _frames_from_fallback_lines(
                    lines,
                    allow_invalid_auth=allow_unsigned,
                    quiet=quiet,
                )
        except ValueError as exc:
            message = format_fallback_error(exc, context="Recovery text")
            console_err.print(f"[error]{message}[/error]")
            prompt_label = "Paste more recovery text (blank line ends a batch)"

    while True:
        batch = prompt_multiline(prompt_label, help_text=help_text)
        help_text = None
        if batch:
            lines.extend(batch)
        if not lines:
            console_err.print("[error]No recovery text provided.[/error]")
            continue

        try:
            with status("Reading recovery text...", quiet=quiet):
                return _frames_from_fallback_lines(
                    lines,
                    allow_invalid_auth=allow_unsigned,
                    quiet=quiet,
                )
        except ValueError as exc:
            message = format_fallback_error(exc, context="Recovery text")
            console_err.print(f"[error]{message}[/error]")
            prompt_label = "Paste more recovery text (blank line ends a batch)"


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


def _prompt_frame_payloads_until_complete(
    *,
    allow_unsigned: bool,
    quiet: bool,
    first_frame: Frame | None = None,
) -> list[Frame]:
    help_text: str | None = (
        "Paste one QR payload per line; we'll stop once all required payloads are collected."
    )
    frames: list[Frame] = []
    seen: dict[tuple[int, int, bytes], Frame] = {}
    main_indices: set[int] = set()
    main_total: int | None = None
    auth_present = False
    expected_doc_id: bytes | None = None

    def _ingest_frame(frame: Frame) -> bool:
        nonlocal main_total, auth_present, expected_doc_id

        if frame.frame_type not in (FrameType.MAIN_DOCUMENT, FrameType.AUTH):
            console_err.print("[error]Only main or auth QR payloads are accepted here.[/error]")
            return False

        if expected_doc_id is None:
            expected_doc_id = frame.doc_id
        elif frame.doc_id != expected_doc_id:
            console_err.print("[error]These payloads are from different documents.[/error]")
            return False

        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            if main_total is None:
                main_total = frame.total
            elif frame.total != main_total:
                console_err.print("[error]Frame count doesn't match earlier payloads.[/error]")
                return False

        key = (int(frame.frame_type), int(frame.index), frame.doc_id)
        existing = seen.get(key)
        if existing is not None:
            if existing.data != frame.data or existing.total != frame.total:
                console_err.print(
                    "[error]That payload conflicts with one you've already provided.[/error]"
                )
            elif not quiet:
                console.print("[subtitle]Duplicate payload ignored.[/subtitle]")
            return False

        seen[key] = frame
        frames.append(frame)

        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            main_indices.add(frame.index)
        else:
            auth_present = True

        if main_total is None:
            if not quiet:
                console.print(
                    "[subtitle]"
                    "Waiting for a MAIN frame so we can count how many are needed."
                    "[/subtitle]"
                )
            return False

        remaining_main = max(main_total - len(main_indices), 0)
        remaining_auth = 0 if allow_unsigned or auth_present else 1
        if remaining_main == 0 and remaining_auth == 0:
            if not quiet:
                console.print("[success]All required QR payloads captured.[/success]")
            return True
        if not quiet:
            auth_label = "ok" if auth_present else "missing"
            if allow_unsigned:
                auth_label = "optional"
            console.print(
                "[subtitle]"
                f"Main QR payloads: {len(main_indices)}/{main_total}. "
                f"Auth payload: {auth_label}. "
                f"Remaining: {remaining_main + remaining_auth}"
                "[/subtitle]"
            )
        return False

    if first_frame is not None and _ingest_frame(first_frame):
        return frames

    while True:
        if main_total is None:
            prompt = "QR payload"
        else:
            remaining_main = max(main_total - len(main_indices), 0)
            remaining_auth = 0 if allow_unsigned or auth_present else 1
            remaining_total = remaining_main + remaining_auth
            if remaining_main == 0 and remaining_auth == 1:
                prompt = "Auth QR payload (1 remaining)"
            else:
                prompt = f"QR payload ({remaining_total} remaining)"

        payload_text = prompt_required(prompt, help_text=help_text)
        help_text = None

        try:
            frame = _frame_from_payload_text(payload_text, "auto")
        except ValueError as exc:
            console_err.print(f"[error]{format_recovery_input_error(exc)}[/error]")
            continue

        if _ingest_frame(frame):
            return frames


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
        return write_plan_outputs(plan, quiet=quiet, debug=debug)

    if show_header and not quiet:
        console.print("[title]Ethernity recovery wizard[/title]")
        console.print("[subtitle]Guided recovery of backup documents.[/subtitle]")

    validate_recover_args(args)
    _, qr_payload_encoding = resolve_recover_config(args)
    if allow_unsigned:
        _warn("Authentication check skipped - ensure you trust the source", quiet=quiet)

    with wizard_flow(name="Recovery", total_steps=4, quiet=quiet):
        with wizard_stage("Input"):
            frames, input_label, input_detail = _prompt_recovery_input(
                args, qr_payload_encoding, allow_unsigned, quiet
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

        extracted = decrypt_and_extract(plan, quiet=quiet, debug=debug)

        with wizard_stage("Output"):
            output_path = _resolve_recover_output(
                extracted, args.output, interactive=True, doc_id=plan.doc_id
            )
            if not assume_yes and not prompt_yes_no(
                "Proceed with writing files",
                default=True,
                help_text="Select no to cancel.",
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
        extra_auth_frames.extend(_auth_frames_from_payloads(args.auth_payloads_file, "auto"))
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
                        "auto",
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


def write_plan_outputs(plan, *, quiet: bool, debug: bool = False) -> int:
    extracted = decrypt_and_extract(plan, quiet=quiet, debug=debug)
    write_recovered_outputs(
        extracted,
        output_path=plan.output_path,
        auth_status=plan.auth_status,
        allow_unsigned=plan.allow_unsigned,
        quiet=quiet,
    )
    return 0
