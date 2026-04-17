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

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from ethernity.cli.shared.io.fallback_parser import format_fallback_error
from ethernity.cli.shared.io.frames import (
    _frame_from_fallback_lines,
    _frame_from_payload_text,
    _frames_from_payload_lines,
    _frames_from_scan,
    _read_text_lines,
)
from ethernity.cli.shared.text import format_qr_input_error
from ethernity.cli.shared.ui_api import (
    console,
    console_err,
    prompt_choice,
    prompt_optional_path_with_picker,
    prompt_optional_secret,
    prompt_paths_with_picker,
    prompt_required,
    prompt_required_secret,
    prompt_yes_no,
    status,
)
from ethernity.crypto.sharding import (
    KEY_TYPE_PASSPHRASE,
    KEY_TYPE_SIGNING_SEED,
    ShardPayload,
    decode_shard_payload,
)
from ethernity.encoding.framing import Frame, FrameType

ShardTextInputKind = Literal["fallback", "payload", "auto"]


def _resolve_recover_output(
    entries: Sequence[tuple[object, bytes]],
    output_path: str | None,
    *,
    interactive: bool,
    doc_id: bytes | None,
    input_origin: str,
    input_roots: Sequence[str],
) -> str | None:
    if output_path or not interactive:
        return output_path
    if not entries:
        return output_path
    single_entry = len(entries) == 1
    if single_entry and input_origin in {"directory", "mixed"}:
        return _prompt_output_directory(
            doc_id,
            entries=entries,
            input_origin=input_origin,
            input_roots=input_roots,
        )
    if single_entry:
        choice = prompt_choice(
            "Recovered file output",
            {"file": "Save to a file", "stdout": "Print to stdout"},
            default="file",
            help_text="Printing binary data to the terminal may be unreadable.",
        )
        if choice == "stdout":
            return None
        entry = entries[0][0]
        default_name = _infer_recovered_filename(entry)
        destination = prompt_choice(
            "Output file destination",
            {
                "inferred": f"Use inferred filename ({default_name})",
                "custom": "Choose custom file path",
            },
            default="inferred",
            help_text="The inferred name comes from the decrypted envelope manifest.",
        )
        if destination == "inferred":
            return default_name
        help_text = f"Leave blank to use {default_name}."
        path = prompt_optional_path_with_picker(
            "Output file path",
            kind="file",
            help_text=help_text,
            allow_new=True,
            picker_prompt="Select an output file",
        )
        return path or default_name

    return _prompt_output_directory(
        doc_id,
        entries=entries,
        input_origin=input_origin,
        input_roots=input_roots,
    )


def _infer_recovered_filename(entry: object) -> str:
    default_name = "recovered.bin"
    entry_path = getattr(entry, "path", None)
    if entry_path is None:
        return default_name
    candidate = Path(str(entry_path)).name.strip()
    return candidate or default_name


def _prompt_output_directory(
    doc_id: bytes | None,
    *,
    entries: Sequence[tuple[object, bytes]],
    input_origin: str,
    input_roots: Sequence[str],
) -> str:
    default_dir = _infer_recovered_directory(
        doc_id,
        entries=entries,
        input_origin=input_origin,
        input_roots=input_roots,
    )
    destination = prompt_choice(
        "Output directory destination",
        {
            "inferred": f"Use inferred directory ({default_dir})",
            "custom": "Choose custom directory path",
        },
        default="inferred",
        help_text="The inferred directory comes from the decrypted envelope metadata.",
    )
    if destination == "inferred":
        return default_dir
    help_text = f"Leave blank to use {default_dir}. A directory will be created if needed."
    directory = prompt_optional_path_with_picker(
        "Output directory",
        kind="dir",
        help_text=help_text,
        allow_new=True,
        picker_prompt="Select an output directory",
    )
    return directory or default_dir


def _infer_recovered_directory(
    doc_id: bytes | None,
    *,
    entries: Sequence[tuple[object, bytes]],
    input_origin: str,
    input_roots: Sequence[str],
) -> str:
    fallback = f"recovered-{doc_id.hex()}" if doc_id else "recovered-output"
    if input_origin == "mixed":
        return fallback
    if input_origin == "directory" and len(input_roots) == 1:
        candidate = input_roots[0].strip()
        if (
            candidate
            and candidate not in {".", ".."}
            and not _entries_already_include_root(entries, candidate)
        ):
            return candidate
    return fallback


def _entries_already_include_root(
    entries: Sequence[tuple[object, bytes]],
    root_label: str,
) -> bool:
    if not entries:
        return False
    for entry, _data in entries:
        raw_path = getattr(entry, "path", None)
        if raw_path is None:
            return False
        parts = Path(str(raw_path).strip()).parts
        if not parts or parts[0] != root_label:
            return False
    return True


def _format_shard_input_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if "no valid shard data found" in lowered or "unable to parse shard recovery text" in lowered:
        return (
            "No shard data found. Try scanning PDFs/images or paste shard recovery text with '-'."
        )
    return format_qr_input_error(
        message,
        bad_payload_hint=(
            "That doesn't look like a QR payload. Paste one shard payload per line, "
            "or switch to shard recovery text."
        ),
        no_qr_hint=(
            "That doesn't look like a QR payload. Paste one shard payload per line, "
            "or switch to shard recovery text."
        ),
        file_hint="Check the path and try again.",
    )


def _format_shard_payload_error(exc: Exception) -> str:
    message = str(exc)
    return format_qr_input_error(
        message,
        bad_payload_hint=(
            "That doesn't look like a QR payload. Paste one shard payload per line, "
            "or switch to shard recovery text."
        ),
        no_qr_hint=(
            "That doesn't look like a QR payload. Paste one shard payload per line, "
            "or switch to shard recovery text."
        ),
        default_hint="Try scanning images or paste shard recovery text.",
    )


def _prompt_shard_inputs(
    *,
    quiet: bool,
    key_type: str = KEY_TYPE_PASSPHRASE,
    label: str = "Shard documents",
    stop_at_quorum: bool = True,
) -> tuple[list[str], list[str], list[Frame]]:
    state = _ShardPasteState(frames=[], seen_shares=set())
    fallback_files: list[str] = []
    payload_files: list[str] = []
    manual_help_text = "Enter shard files or scan paths; enter '-' to choose what to paste."
    while True:
        if state.expected_threshold is not None:
            remaining = max(state.expected_threshold - len(state.seen_shares), 0)
            if remaining == 1:
                prompt_label = "Recovery shard files (1 remaining)"
            else:
                prompt_label = f"Recovery shard files ({remaining} remaining)"
        else:
            prompt_label = "Recovery shard files (one per line, blank when done)"
        paths = prompt_paths_with_picker(
            prompt_label,
            picker_prompt="Select shard input files",
            kind="file",
            manual_help_text=manual_help_text,
            picker_help_text="Use space to toggle, Enter to confirm.",
            allow_stdin=True,
            empty_message="At least one shard input is required.",
            stdin_message="Enter '-' alone to paste shard recovery text or shard QR payloads.",
        )
        if "-" in paths:
            return (
                fallback_files,
                payload_files,
                _prompt_shard_text_or_payloads_stdin(
                    preferred_kind=_prompt_shard_text_input_kind(),
                    state=state,
                    key_type=key_type,
                    stop_at_quorum=stop_at_quorum,
                    label=label,
                ),
            )

        try:
            with status("Reading shard files...", quiet=quiet):
                frames = _frames_from_shard_text_or_payload_files(paths)
        except ValueError as exc:
            console_err.print(f"[error]{_format_shard_input_error(exc)}[/error]")
            continue
        batch_fallback_files, batch_payload_files = _classify_shard_input_paths(paths)
        _extend_unique_paths(fallback_files, batch_fallback_files)
        _extend_unique_paths(payload_files, batch_payload_files)
        for frame in frames:
            if _ingest_shard_frame(
                frame=frame,
                state=state,
                label=label,
                key_type=key_type,
                stop_at_quorum=stop_at_quorum,
            ):
                return fallback_files, payload_files, state.frames
        if _should_finish_shard_collection(
            state,
            label=label,
            stop_at_quorum=stop_at_quorum,
        ):
            return fallback_files, payload_files, state.frames


def prompt_passphrase_unlock_material(
    *,
    quiet: bool,
    passphrase: str | None = None,
    shard_fallback_files: Sequence[str] | None = None,
    shard_payloads_file: Sequence[str] | None = None,
    shard_scan: Sequence[str] | None = None,
    collect_all_shards: bool = False,
    choice_prompt: str = "How do you want to unlock the backup",
    passphrase_choice_label: str = "I have the passphrase",
    shard_choice_label: str = "I have recovery shard documents",
    choice_help_text: str = "Choose the recovery material you have available.",
    passphrase_prompt: str = "Enter passphrase",
    passphrase_help_text: str = "Enter the recovery passphrase for this backup.",
    allow_existing_review: bool = False,
) -> tuple[str | None, list[str], list[str], list[str], list[Frame]]:
    resolved_passphrase = passphrase
    fallback_files = list(shard_fallback_files or [])
    payload_files = list(shard_payloads_file or [])
    scan_files = list(shard_scan or [])
    shard_frames: list[Frame] = []

    prefilled_unlock_material = bool(
        resolved_passphrase or fallback_files or payload_files or scan_files
    )
    if prefilled_unlock_material and allow_existing_review:
        choice = prompt_choice(
            choice_prompt,
            {
                "keep": "Use the unlock material already provided",
                "passphrase": passphrase_choice_label,
                "shards": shard_choice_label,
            },
            default="keep",
            help_text=("Review or replace the unlock material already provided before continuing."),
        )
        if choice == "keep":
            return resolved_passphrase, fallback_files, payload_files, scan_files, shard_frames
        if choice == "passphrase":
            if resolved_passphrase is not None:
                entered = prompt_optional_secret(
                    passphrase_prompt,
                    help_text="Leave blank to keep the passphrase already provided.",
                )
                resolved_passphrase = entered if entered is not None else resolved_passphrase
            else:
                resolved_passphrase = prompt_required_secret(
                    passphrase_prompt,
                    help_text=passphrase_help_text,
                )
            return resolved_passphrase, [], [], [], shard_frames

        fallback_files = []
        payload_files = []
        scan_files = []
        resolved_passphrase = None

    if not prefilled_unlock_material:
        choice = prompt_choice(
            choice_prompt,
            {
                "passphrase": passphrase_choice_label,
                "shards": shard_choice_label,
            },
            default="passphrase",
            help_text=choice_help_text,
        )
        if choice == "passphrase":
            resolved_passphrase = prompt_required_secret(
                passphrase_prompt,
                help_text=passphrase_help_text,
            )
            return resolved_passphrase, fallback_files, payload_files, scan_files, shard_frames

    fallback_files, payload_inputs, shard_frames = _prompt_shard_inputs(
        quiet=quiet,
        stop_at_quorum=not collect_all_shards,
    )
    scan_files = [path for path in payload_inputs if _is_scan_path(path)]
    payload_files = [path for path in payload_inputs if not _is_scan_path(path)]
    return None, fallback_files, payload_files, scan_files, shard_frames


def _extend_unique_paths(destination: list[str], paths: list[str]) -> None:
    for path in paths:
        if path not in destination:
            destination.append(path)


def _classify_shard_input_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    fallback_files: list[str] = []
    payload_files: list[str] = []
    for path in paths:
        if _is_scan_path(path):
            payload_files.append(path)
            continue
        lines = _read_text_lines(path)
        try:
            _frame_from_fallback_lines(lines, label="shard")
        except ValueError:
            _frames_from_payload_lines(
                lines,
                label="shard QR payloads",
                source=path,
            )
            payload_files.append(path)
            continue
        fallback_files.append(path)
    return fallback_files, payload_files


@dataclass
class _ShardPasteState:
    frames: list[Frame]
    seen_shares: set[int]
    seen_payloads: dict[int, ShardPayload] = field(default_factory=dict)
    expected_version: int | None = None
    expected_threshold: int | None = None
    expected_shares: int | None = None
    expected_secret_len: int | None = None
    expected_doc_hash: bytes | None = None
    expected_sign_pub: bytes | None = None
    expected_shard_set_id: bytes | None = None


def _ingest_shard_frame(
    *,
    frame: Frame,
    state: _ShardPasteState,
    label: str,
    key_type: str = KEY_TYPE_PASSPHRASE,
    stop_at_quorum: bool = True,
) -> bool:
    if frame.frame_type != FrameType.KEY_DOCUMENT:
        console_err.print(
            "[error]That payload isn't a shard document. Use shard recovery text or QR "
            "payloads for passphrase shards only.[/error]"
        )
        return False
    if frame.total != 1 or frame.index != 0:
        console_err.print(
            "[error]Shard QR payloads are single-frame; paste one payload line at a time.[/error]"
        )
        return False

    try:
        payload = decode_shard_payload(frame.data)
    except ValueError as exc:
        console_err.print(f"[error]{_format_shard_payload_error(exc)}[/error]")
        return False
    if payload.key_type != key_type:
        expected_label = _key_type_label(key_type)
        console_err.print(
            f"[error]This shard isn't for the {expected_label}; "
            f"use {expected_label} shard documents only.[/error]"
        )
        return False

    if state.expected_threshold is None:
        state.expected_version = payload.version
        state.expected_threshold = payload.threshold
        state.expected_shares = payload.share_count
        state.expected_secret_len = payload.secret_len
        state.expected_doc_hash = payload.doc_hash
        state.expected_sign_pub = payload.sign_pub
        state.expected_shard_set_id = payload.shard_set_id
    else:
        if state.expected_version is not None and payload.version != state.expected_version:
            console_err.print(
                "[error]This shard uses a different shard-payload version than the previous ones. "
                "Use shards from one shard set.[/error]"
            )
            return False
        if payload.threshold != state.expected_threshold:
            console_err.print(
                "[error]This shard has a different threshold than the previous ones. "
                "Use shards from one shard set.[/error]"
            )
            return False
        if state.expected_shares is not None and payload.share_count != state.expected_shares:
            console_err.print(
                "[error]This shard has a different share count than the previous ones. "
                "Use shards from one shard set.[/error]"
            )
            return False
        if (
            state.expected_secret_len is not None
            and payload.secret_len != state.expected_secret_len
        ):
            console_err.print(
                "[error]This shard has a different secret length than the previous ones. "
                "Use shards from one shard set.[/error]"
            )
            return False
        if state.expected_doc_hash is not None and payload.doc_hash != state.expected_doc_hash:
            console_err.print(
                "[error]This shard is from a different document than the previous ones. "
                "Continue with shards from one backup.[/error]"
            )
            return False
        if state.expected_sign_pub is not None and payload.sign_pub != state.expected_sign_pub:
            console_err.print("[error]This shard is from a different signing key set.[/error]")
            return False
        if payload.shard_set_id != state.expected_shard_set_id:
            console_err.print(
                "[error]This shard is from a different shard set than the previous ones.[/error]"
            )
            return False

    existing_payload = state.seen_payloads.get(payload.share_index)
    if existing_payload is not None:
        if existing_payload != payload:
            console_err.print(
                "[error]This shard conflicts with one you've already provided. "
                "Keep only one shard per share index from the same shard set.[/error]"
            )
        else:
            console.print("[subtitle]Duplicate shard ignored.[/subtitle]")
        return False

    state.seen_shares.add(payload.share_index)
    state.seen_payloads[payload.share_index] = payload
    state.frames.append(frame)

    if state.expected_threshold is None:
        return False
    remaining = state.expected_threshold - len(state.seen_shares)
    label_lower = label.lower()
    if remaining <= 0:
        console.print(f"[success]All required {label_lower} captured.[/success]")
        return stop_at_quorum
    return False


def _should_finish_shard_collection(
    state: _ShardPasteState,
    *,
    label: str,
    stop_at_quorum: bool,
) -> bool:
    if state.expected_threshold is None:
        return False
    if len(state.seen_shares) < state.expected_threshold:
        return False
    if stop_at_quorum:
        return True
    if state.expected_shares is not None and len(state.seen_shares) >= state.expected_shares:
        return True
    return not prompt_yes_no(
        f"Add more {label.lower()}",
        default=False,
        help_text="Select yes if you want to add more shard files from this same shard set.",
    )


def _prompt_shard_fallback_paste(
    *,
    initial_lines: list[str] | None = None,
    state: _ShardPasteState | None = None,
    key_type: str = KEY_TYPE_PASSPHRASE,
    label: str = "Shard documents",
    stop_at_quorum: bool = True,
) -> list[Frame]:
    state = state or _ShardPasteState(frames=[], seen_shares=set())
    if state.expected_threshold is not None:
        remaining = state.expected_threshold - len(state.seen_shares)
        if remaining <= 0 and stop_at_quorum:
            return state.frames
    if stop_at_quorum:
        console.print(
            "[subtitle]"
            "Paste shard recovery text one section at a time until enough shards are decoded."
            "[/subtitle]"
        )
        help_text: str | None = (
            "Paste shard recovery text (headers are fine). "
            "We'll keep asking until it decodes and stop once enough shards are collected."
        )
    else:
        console.print(
            "[subtitle]"
            "Paste shard recovery text one section at a time; after quorum you can add more shards "
            "from the same set."
            "[/subtitle]"
        )
        help_text = (
            "Paste shard recovery text (headers are fine). "
            "We'll keep asking until it decodes, then let you add more shards from the same set."
        )
    first_lines = list(initial_lines or [])
    while True:
        prompt_label = "Paste shard recovery text"
        if state.expected_threshold is not None:
            remaining = max(state.expected_threshold - len(state.seen_shares), 0)
            if remaining == 1:
                prompt_label = "Paste shard recovery text (1 remaining)"
            elif remaining == 0 and not stop_at_quorum:
                prompt_label = "Paste shard recovery text (quorum met)"
            else:
                prompt_label = f"Paste shard recovery text ({remaining} remaining)"
        frame = _prompt_shard_fallback_until_complete(
            help_text=help_text,
            initial_lines=first_lines,
            prompt_label=prompt_label,
        )
        first_lines = []
        if _ingest_shard_frame(
            frame=frame,
            state=state,
            label=label,
            key_type=key_type,
            stop_at_quorum=stop_at_quorum,
        ):
            return state.frames
        if _should_finish_shard_collection(state, label=label, stop_at_quorum=stop_at_quorum):
            return state.frames
        help_text = None


def _prompt_shard_fallback_until_complete(
    *,
    help_text: str | None,
    initial_lines: list[str] | None = None,
    prompt_label: str | None = None,
) -> Frame:
    lines = list(initial_lines or [])
    prompt_label = prompt_label or "Paste shard recovery text"
    if lines:
        try:
            return _frame_from_fallback_lines(lines, label="shard")
        except ValueError as exc:
            message = format_fallback_error(exc, context="Shard recovery text")
            console_err.print(f"[error]{message}[/error]")
            prompt_label = "Paste more shard recovery text"
    while True:
        entry = prompt_required(prompt_label, help_text=help_text)
        help_text = None
        if "\n" in entry or "\r" in entry:
            batch = [line for line in entry.splitlines() if line.strip()]
            lines.extend(batch)
        else:
            lines.append(entry)
        try:
            return _frame_from_fallback_lines(lines, label="shard")
        except ValueError as exc:
            message = format_fallback_error(exc, context="Shard recovery text")
            console_err.print(f"[error]{message}[/error]")
            prompt_label = "Paste more shard recovery text"


def _prompt_shard_text_or_payloads_stdin(
    *,
    preferred_kind: ShardTextInputKind = "auto",
    state: _ShardPasteState | None = None,
    key_type: str = KEY_TYPE_PASSPHRASE,
    label: str = "Shard documents",
    stop_at_quorum: bool = True,
) -> list[Frame]:
    state = state or _ShardPasteState(frames=[], seen_shares=set())
    first_entry = prompt_required(
        _shard_text_stdin_prompt(preferred_kind),
        help_text=_shard_text_stdin_help(preferred_kind),
    )
    lines = _nonempty_prompt_lines(first_entry)

    if preferred_kind == "fallback":
        return _prompt_shard_fallback_paste(
            initial_lines=lines,
            state=state,
            key_type=key_type,
            label=label,
            stop_at_quorum=stop_at_quorum,
        )
    if preferred_kind == "payload":
        return _prompt_shard_payload_paste(
            initial_frames=_parse_initial_shard_payload_frames(lines),
            state=state,
            key_type=key_type,
            label=label,
            stop_at_quorum=stop_at_quorum,
        )

    try:
        first_frame = _frame_from_payload_text(lines[0])
    except ValueError:
        return _prompt_shard_fallback_paste(
            initial_lines=lines,
            state=state,
            key_type=key_type,
            label=label,
            stop_at_quorum=stop_at_quorum,
        )

    if len(lines) > 1:
        try:
            frames = _frames_from_payload_lines(
                lines,
                label="shard QR payloads",
                source="stdin",
            )
        except ValueError as exc:
            console_err.print(f"[error]{_format_shard_payload_error(exc)}[/error]")
            return _prompt_shard_payload_paste(
                initial_frames=[first_frame],
                state=state,
                key_type=key_type,
                label=label,
                stop_at_quorum=stop_at_quorum,
            )
        return _prompt_shard_payload_paste(
            initial_frames=frames,
            state=state,
            key_type=key_type,
            label=label,
            stop_at_quorum=stop_at_quorum,
        )

    return _prompt_shard_payload_paste(
        initial_frames=[first_frame],
        state=state,
        key_type=key_type,
        label=label,
        stop_at_quorum=stop_at_quorum,
    )


def _prompt_shard_text_input_kind() -> ShardTextInputKind:
    selected = prompt_choice(
        "What kind of shard text do you have",
        {
            "fallback": "Shard recovery text",
            "payload": "Shard QR payload lines",
            "auto": "Let Ethernity detect it",
        },
        default="fallback",
        help_text=(
            "Choose the exact artifact when you know it. Use auto-detect only if you're not sure."
        ),
    )
    return cast(ShardTextInputKind, selected)


def _shard_text_stdin_prompt(input_kind: ShardTextInputKind) -> str:
    if input_kind == "fallback":
        return "Shard recovery text"
    if input_kind == "payload":
        return "Shard QR payload lines"
    return "Shard recovery text or QR payload"


def _shard_text_stdin_help(input_kind: ShardTextInputKind) -> str:
    if input_kind == "fallback":
        return "Paste shard recovery text. You can paste one section or a full block."
    if input_kind == "payload":
        return "Paste one shard QR payload per line. You can paste several lines at once."
    return (
        "Paste shard recovery text or shard QR payload lines. If detection is wrong, go back "
        "and choose the exact artifact type."
    )


def _nonempty_prompt_lines(entry: str) -> list[str]:
    lines = [line for line in entry.splitlines() if line.strip()]
    if lines:
        return lines
    return [entry]


def _parse_initial_shard_payload_frames(lines: list[str]) -> list[Frame]:
    try:
        return _frames_from_payload_lines(lines, label="shard QR payloads", source="stdin")
    except ValueError as exc:
        console_err.print(f"[error]{_format_shard_payload_error(exc)}[/error]")
        return []


def _frames_from_shard_text_or_payload_files(paths: list[str]) -> list[Frame]:
    frames: list[Frame] = []
    scan_paths: list[str] = []
    text_paths: list[str] = []
    for path in paths:
        if _is_scan_path(path):
            scan_paths.append(path)
        else:
            text_paths.append(path)
    if scan_paths:
        frames.extend(_frames_from_scan(scan_paths))
    for path in text_paths:
        lines = _read_text_lines(path)
        frames.extend(_frames_from_shard_text_or_payload_lines(lines, source=path))
    if not frames:
        raise ValueError(
            "No valid shard data found in provided files.\n"
            "  - Check that files contain shard recovery text or QR payloads\n"
            "  - PDFs/images are scanned for QR payloads automatically\n"
            "  - Ensure each file has valid content"
        )
    return frames


def _frames_from_shard_text_or_payload_lines(
    lines: list[str],
    *,
    source: str,
) -> list[Frame]:
    errors: list[str] = []
    try:
        frame = _frame_from_fallback_lines(lines, label="shard")
        return [frame]
    except ValueError as exc:
        errors.append(format_fallback_error(exc, context="Shard recovery text"))

    try:
        return _frames_from_payload_lines(
            lines,
            label="shard QR payloads",
            source=source,
        )
    except ValueError as exc:
        errors.append(str(exc))
        detail = "; ".join(errors)
        raise ValueError(
            f"unable to parse shard recovery text or QR payloads from {source}: {detail}"
        ) from exc


def _is_scan_path(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".bmp",
        ".gif",
        ".webp",
    }


def _prompt_shard_payload_paste(
    *,
    initial_frames: list[Frame] | None = None,
    state: _ShardPasteState | None = None,
    key_type: str = KEY_TYPE_PASSPHRASE,
    label: str = "Shard payloads",
    stop_at_quorum: bool = True,
) -> list[Frame]:
    if stop_at_quorum:
        help_text: str | None = (
            "Paste one shard QR payload per line; we'll stop once enough shards are collected."
        )
    else:
        help_text = (
            "Paste one shard QR payload per line; after quorum you can add more shards from the "
            "same set."
        )
    state = state or _ShardPasteState(frames=[], seen_shares=set())
    if state.expected_threshold is not None:
        remaining = state.expected_threshold - len(state.seen_shares)
        if remaining <= 0 and stop_at_quorum:
            return state.frames
    if stop_at_quorum:
        console.print(
            "[subtitle]"
            "Paste one shard QR payload per line. We'll stop once the threshold is met."
            "[/subtitle]"
        )
    else:
        console.print(
            "[subtitle]"
            "Paste one shard QR payload per line. After quorum, you can add more shards from the "
            "same set."
            "[/subtitle]"
        )

    for frame in initial_frames or []:
        if _ingest_shard_frame(
            frame=frame,
            state=state,
            label=label,
            key_type=key_type,
            stop_at_quorum=stop_at_quorum,
        ):
            return state.frames
    if _should_finish_shard_collection(state, label=label, stop_at_quorum=stop_at_quorum):
        return state.frames

    while True:
        if state.expected_threshold is None:
            prompt = "Shard QR payload"
        else:
            remaining = max(state.expected_threshold - len(state.seen_shares), 0)
            if remaining == 1:
                prompt = "Shard QR payload (1 remaining)"
            elif remaining == 0 and not stop_at_quorum:
                prompt = "Shard QR payload (quorum met)"
            else:
                prompt = f"Shard QR payload ({remaining} remaining)"

        payload_text = prompt_required(prompt, help_text=help_text)
        help_text = None

        try:
            frame = _frame_from_payload_text(payload_text)
        except ValueError as exc:
            console_err.print(f"[error]{_format_shard_payload_error(exc)}[/error]")
            continue

        if _ingest_shard_frame(
            frame=frame,
            state=state,
            label=label,
            key_type=key_type,
            stop_at_quorum=stop_at_quorum,
        ):
            return state.frames
        if _should_finish_shard_collection(state, label=label, stop_at_quorum=stop_at_quorum):
            return state.frames


def _key_type_label(key_type: str) -> str:
    if key_type == KEY_TYPE_PASSPHRASE:
        return "passphrase"
    if key_type == KEY_TYPE_SIGNING_SEED:
        return "signing key"
    return "requested key"
