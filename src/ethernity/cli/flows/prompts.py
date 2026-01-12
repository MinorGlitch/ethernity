#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ...crypto.sharding import KEY_TYPE_PASSPHRASE, decode_shard_payload
from ...encoding.framing import Frame, FrameType
from ..api import (
    console,
    console_err,
    prompt_choice,
    prompt_optional,
    prompt_required,
    prompt_required_paths,
    status,
)
from ..io.fallback_parser import format_fallback_error
from ..io.frames import (
    _frame_from_fallback_lines,
    _frame_from_payload_text,
    _frames_from_payload_lines,
    _read_text_lines,
)


def _resolve_recover_output(
    entries: Sequence[tuple[object, bytes]],
    output_path: str | None,
    *,
    interactive: bool,
    doc_id: bytes | None,
) -> str | None:
    if output_path or not interactive:
        return output_path
    if not entries:
        return output_path
    if len(entries) == 1:
        choice = prompt_choice(
            "Recovered file output",
            {"file": "Save to a file", "stdout": "Print to stdout"},
            default="file",
            help_text="Printing binary data to the terminal may be unreadable.",
        )
        if choice == "stdout":
            return None
        entry = entries[0][0]
        default_name = "recovered.bin"
        entry_path = getattr(entry, "path", None)
        if entry_path:
            default_name = Path(entry_path).name
        help_text = f"Leave blank to use {default_name}."
        path = prompt_optional("Output file path", help_text=help_text)
        return path or default_name

    default_dir = f"recovered-{doc_id.hex()}" if doc_id else "recovered-output"
    help_text = f"Leave blank to use {default_dir}. A directory will be created if needed."
    directory = prompt_optional("Output directory", help_text=help_text)
    return directory or default_dir


def _prompt_shard_inputs(*, quiet: bool) -> tuple[list[str], list[str], list[Frame]]:
    state = _ShardPasteState(frames=[], seen_shares={})
    help_text: str | None = (
        "Enter shard recovery text or QR payload files (mixing is ok). "
        "We'll detect the format. Enter '-' alone to paste."
    )
    while True:
        if state.expected_threshold is not None:
            remaining = max(state.expected_threshold - len(state.seen_shares), 0)
            if remaining == 1:
                prompt_label = "Shard inputs (1 remaining)"
            else:
                prompt_label = f"Shard inputs ({remaining} remaining)"
        else:
            prompt_label = "Shard inputs (one per line, blank when done)"
        paths = prompt_required_paths(
            prompt_label,
            help_text=help_text,
            kind="file",
            allow_stdin=True,
            empty_message="At least one shard input is required.",
        )
        help_text = None
        if "-" in paths:
            return [], [], _prompt_shard_text_or_payloads_stdin(state=state)

        try:
            with status("Reading shard files...", quiet=quiet):
                frames = _frames_from_shard_text_or_payload_files(paths)
        except ValueError as exc:
            console_err.print(f"[error]{exc}[/error]")
            continue
        for frame in frames:
            if _ingest_shard_frame(frame=frame, state=state, label="Shard documents"):
                return [], [], state.frames
        if state.expected_threshold is not None:
            if len(state.seen_shares) >= state.expected_threshold:
                return [], [], state.frames


@dataclass
class _ShardPasteState:
    frames: list[Frame]
    seen_shares: dict[int, bytes]
    expected_threshold: int | None = None
    expected_shares: int | None = None
    expected_doc_hash: bytes | None = None
    expected_sign_pub: bytes | None = None


def _ingest_shard_frame(*, frame: Frame, state: _ShardPasteState, label: str) -> bool:
    if frame.frame_type != FrameType.KEY_DOCUMENT:
        console_err.print(
            "[error]Unexpected frame type; provide shard recovery text or QR payloads.[/error]"
        )
        return False
    if frame.total != 1 or frame.index != 0:
        console_err.print("[error]Shard payloads must be single-frame entries.[/error]")
        return False

    try:
        payload = decode_shard_payload(frame.data)
    except ValueError as exc:
        console_err.print(f"[error]{exc}[/error]")
        return False
    if payload.key_type != KEY_TYPE_PASSPHRASE:
        console_err.print(
            "[error]This shard is not a passphrase shard; use passphrase shards only.[/error]"
        )
        return False

    if state.expected_threshold is None:
        state.expected_threshold = payload.threshold
        state.expected_shares = payload.shares
        state.expected_doc_hash = payload.doc_hash
        state.expected_sign_pub = payload.sign_pub
    else:
        if payload.threshold != state.expected_threshold:
            console_err.print("[error]Shard threshold does not match previous shards.[/error]")
            return False
        if state.expected_shares is not None and payload.shares != state.expected_shares:
            console_err.print("[error]Shard share count does not match previous shards.[/error]")
            return False
        if state.expected_doc_hash is not None and payload.doc_hash != state.expected_doc_hash:
            console_err.print("[error]Shard document hash does not match previous shards.[/error]")
            return False
        if state.expected_sign_pub is not None and payload.sign_pub != state.expected_sign_pub:
            console_err.print("[error]Shard signing key does not match previous shards.[/error]")
            return False

    existing_share = state.seen_shares.get(payload.index)
    if existing_share is not None:
        if existing_share != payload.share:
            console_err.print("[error]Duplicate shard index with mismatched data.[/error]")
        else:
            console.print("[subtitle]Duplicate shard ignored.[/subtitle]")
        return False

    state.seen_shares[payload.index] = payload.share
    state.frames.append(frame)

    if state.expected_threshold is None:
        return False
    remaining = state.expected_threshold - len(state.seen_shares)
    label_lower = label.lower()
    if remaining <= 0:
        console.print(f"[success]All required {label_lower} captured.[/success]")
        return True
    console.print(
        "[subtitle]"
        f"{label}: {len(state.seen_shares)}/{state.expected_threshold}. Remaining: {remaining}"
        "[/subtitle]"
    )
    return False


def _prompt_shard_fallback_paste(
    *,
    initial_lines: list[str] | None = None,
    state: _ShardPasteState | None = None,
) -> list[Frame]:
    state = state or _ShardPasteState(frames=[], seen_shares={})
    if state.expected_threshold is not None:
        remaining = state.expected_threshold - len(state.seen_shares)
        if remaining <= 0:
            return state.frames
    help_text: str | None = (
        "Paste shard recovery text (headers are ok). "
        "We'll keep asking until it decodes and stop once enough shards are collected."
    )
    first_lines = list(initial_lines or [])
    while True:
        prompt_label = "Paste shard recovery text"
        if state.expected_threshold is not None:
            remaining = max(state.expected_threshold - len(state.seen_shares), 0)
            if remaining == 1:
                prompt_label = "Paste shard recovery text (1 remaining)"
            else:
                prompt_label = f"Paste shard recovery text ({remaining} remaining)"
        frame = _prompt_shard_fallback_until_complete(
            help_text=help_text,
            initial_lines=first_lines,
            prompt_label=prompt_label,
        )
        first_lines = []
        if _ingest_shard_frame(frame=frame, state=state, label="Shard documents"):
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
    state: _ShardPasteState | None = None,
) -> list[Frame]:
    state = state or _ShardPasteState(frames=[], seen_shares={})
    first_line = prompt_required(
        "Shard recovery text or QR payload (first line or block)",
        help_text=(
            "Paste shard recovery text or a QR payload. "
            "We'll detect the format and keep asking until it decodes."
        ),
    )
    if "\n" in first_line or "\r" in first_line:
        lines = [line for line in first_line.splitlines() if line.strip()]
    else:
        lines = [first_line]

    try:
        first_frame = _frame_from_payload_text(lines[0], "auto")
    except ValueError:
        return _prompt_shard_fallback_paste(initial_lines=lines, state=state)

    if len(lines) > 1:
        try:
            frames = _frames_from_payload_lines(
                lines,
                "auto",
                label="shard QR payloads",
                source="stdin",
            )
        except ValueError as exc:
            console_err.print(f"[error]{exc}[/error]")
            return _prompt_shard_payload_paste(initial_frames=[first_frame], state=state)
        return _prompt_shard_payload_paste(initial_frames=frames, state=state)

    return _prompt_shard_payload_paste(initial_frames=[first_frame], state=state)


def _frames_from_shard_text_or_payload_files(paths: list[str]) -> list[Frame]:
    frames: list[Frame] = []
    for path in paths:
        lines = _read_text_lines(path)
        frames.extend(_frames_from_shard_text_or_payload_lines(lines, source=path))
    if not frames:
        raise ValueError(
            "No valid shard data found in provided files.\n"
            "  - Check that files contain shard recovery text or QR payloads\n"
            "  - Mixing shard recovery text and QR payload files is supported\n"
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
            "auto",
            label="shard QR payloads",
            source=source,
        )
    except ValueError as exc:
        errors.append(str(exc))
        detail = "; ".join(errors)
        raise ValueError(
            f"unable to parse shard recovery text or QR payloads from {source}: {detail}"
        ) from exc


def _prompt_shard_payload_paste(
    *,
    initial_frames: list[Frame] | None = None,
    state: _ShardPasteState | None = None,
) -> list[Frame]:
    help_text: str | None = (
        "Paste one shard QR payload per line; we'll stop once enough shards are collected."
    )
    state = state or _ShardPasteState(frames=[], seen_shares={})
    if state.expected_threshold is not None:
        remaining = state.expected_threshold - len(state.seen_shares)
        if remaining <= 0:
            return state.frames

    for frame in initial_frames or []:
        if _ingest_shard_frame(frame=frame, state=state, label="Shard payloads"):
            return state.frames

    while True:
        if state.expected_threshold is None:
            prompt = "Shard QR payload"
        else:
            remaining = max(state.expected_threshold - len(state.seen_shares), 0)
            if remaining == 1:
                prompt = "Shard QR payload (1 remaining)"
            else:
                prompt = f"Shard QR payload ({remaining} remaining)"

        payload_text = prompt_required(prompt, help_text=help_text)
        help_text = None

        try:
            frame = _frame_from_payload_text(payload_text, "auto")
        except ValueError as exc:
            console_err.print(f"[error]{exc}[/error]")
            continue

        if _ingest_shard_frame(frame=frame, state=state, label="Shard payloads"):
            return state.frames
