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

"""Interactive recovery input collection for fallback text, payloads, and scans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

from ethernity.cli.shared.io.fallback_parser import format_fallback_error
from ethernity.cli.shared.io.frames import (
    _detect_recovery_input_mode,
    _frame_from_payload_text,
    _frames_from_fallback_lines,
    _frames_from_payload_lines,
    _read_text_lines,
    _recovery_frames_from_scan,
    format_recovery_input_error,
)
from ethernity.cli.shared.ui_api import (
    console,
    console_err,
    prompt_choice,
    prompt_multiline,
    prompt_path_with_picker,
    prompt_required,
    status,
    wizard_substep,
)
from ethernity.encoding.framing import Frame, FrameType

RecoveryTextInputKind = Literal["fallback", "payload", "auto"]

RECOVERY_TEXT_LABEL = "Recovery text"
RECOVERY_QR_TEXT_LABEL = "Backup text lines"
RECOVERY_SCAN_LABEL = "Backup PDF or images"


def prompt_recovery_input_interactive(
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list[Frame], str, str]:
    """Prompt for recovery source and return (frames, input_label, input_detail)."""
    while True:
        with wizard_substep("Choose source"):
            choice = prompt_choice(
                "How do you want to provide the backup",
                {
                    "scan": "Scan a backup PDF or images (recommended)",
                    "text": "I only have text instead",
                },
                default="scan",
                help_text=(
                    "Most people should scan the backup PDF or images. Choose text only if you do "
                    "not have scannable backup documents."
                ),
            )
        try:
            if choice == "text":
                with wizard_substep("Choose text type"):
                    input_kind = _prompt_recovery_text_input_kind()
                with wizard_substep("Choose text file"):
                    path = prompt_path_with_picker(
                        _recovery_text_path_prompt(input_kind),
                        help_text=_recovery_text_path_help(input_kind),
                        kind="file",
                        allow_stdin=True,
                        picker_prompt=_recovery_text_picker_prompt(input_kind),
                    )
                input_detail = "stdin" if path == "-" else path
                if path == "-":
                    with wizard_substep("Paste text"):
                        frames, input_label = prompt_text_or_payloads_stdin(
                            allow_unsigned=allow_unsigned,
                            quiet=quiet,
                            preferred_kind=input_kind,
                        )
                else:
                    with status(_recovery_text_status_label(input_kind), quiet=quiet):
                        lines = _read_text_lines(path)
                        frames, input_label = parse_recovery_lines_for_kind(
                            lines,
                            allow_unsigned=allow_unsigned,
                            quiet=quiet,
                            source=path,
                            input_kind=input_kind,
                        )
            else:
                with wizard_substep("Choose scan path"):
                    path = prompt_path_with_picker(
                        "Scan path (file or directory)",
                        help_text="Point at a PDF, image, or directory of scans.",
                        kind="path",
                        picker_prompt="Select a scan file or folder",
                    )
                input_label = RECOVERY_SCAN_LABEL
                input_detail = path
                with status("Scanning QR images...", quiet=quiet):
                    frames = _recovery_frames_from_scan([path], quiet=quiet)
            return frames, input_label, input_detail
        except (OSError, ValueError) as exc:
            console_err.print(f"[error]{format_recovery_input_error(exc)}[/error]")
            continue


def parse_recovery_lines(
    lines: list[str],
    *,
    allow_unsigned: bool,
    quiet: bool,
    source: str,
) -> tuple[list[Frame], str]:
    """Parse pasted/file recovery lines as fallback text or QR payload lines."""

    try:
        mode = _detect_recovery_input_mode(lines)
    except ValueError as exc:
        raise ValueError(f"unable to parse recovery text from {source}: {exc}") from exc

    if mode in {"fallback_marked", "fallback"}:
        try:
            frames = _frames_from_fallback_lines(
                lines,
                allow_invalid_auth=allow_unsigned,
                quiet=quiet,
            )
        except ValueError as exc:
            message = format_fallback_error(exc, context="Recovery text")
            raise ValueError(f"invalid recovery text in {source}: {message}") from exc
        return frames, RECOVERY_TEXT_LABEL

    try:
        frames = _frames_from_payload_lines(lines, label="backup text lines", source=source)
        return frames, RECOVERY_QR_TEXT_LABEL
    except ValueError as exc:
        raise ValueError(f"invalid backup text lines in {source}: {exc}") from exc


def parse_recovery_lines_for_kind(
    lines: list[str],
    *,
    allow_unsigned: bool,
    quiet: bool,
    source: str,
    input_kind: RecoveryTextInputKind,
) -> tuple[list[Frame], str]:
    if input_kind == "fallback":
        return _parse_recovery_fallback_lines(
            lines,
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            source=source,
        )
    if input_kind == "payload":
        return _parse_recovery_payload_lines(lines, source=source)
    return parse_recovery_lines(
        lines,
        allow_unsigned=allow_unsigned,
        quiet=quiet,
        source=source,
    )


def _parse_recovery_fallback_lines(
    lines: list[str],
    *,
    allow_unsigned: bool,
    quiet: bool,
    source: str,
) -> tuple[list[Frame], str]:
    try:
        frames = _frames_from_fallback_lines(
            lines,
            allow_invalid_auth=allow_unsigned,
            quiet=quiet,
        )
    except ValueError as exc:
        message = format_fallback_error(exc, context="Recovery text")
        raise ValueError(f"invalid recovery text in {source}: {message}") from exc
    return frames, RECOVERY_TEXT_LABEL


def _parse_recovery_payload_lines(
    lines: list[str],
    *,
    source: str,
) -> tuple[list[Frame], str]:
    try:
        frames = _frames_from_payload_lines(lines, label="backup text lines", source=source)
    except ValueError as exc:
        raise ValueError(f"invalid backup text lines in {source}: {exc}") from exc
    return frames, RECOVERY_QR_TEXT_LABEL


def prompt_text_or_payloads_stdin(
    *,
    allow_unsigned: bool,
    quiet: bool,
    preferred_kind: RecoveryTextInputKind = "auto",
) -> tuple[list[Frame], str]:
    """Read stdin-style interactive input and branch into fallback or payload collection."""

    first_entry = prompt_required(
        _recovery_text_stdin_prompt(preferred_kind),
        help_text=_recovery_text_stdin_help(preferred_kind),
    )
    initial_lines = _nonempty_input_lines(first_entry)

    if preferred_kind == "fallback":
        frames = collect_fallback_frames(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            initial_lines=initial_lines,
        )
        return frames, RECOVERY_TEXT_LABEL
    if preferred_kind == "payload":
        initial_frames = _parse_initial_payload_frames(initial_lines)
        frames = collect_payload_frames(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            initial_frames=initial_frames,
        )
        return frames, RECOVERY_QR_TEXT_LABEL

    try:
        mode = _detect_recovery_input_mode(initial_lines)
    except ValueError:
        frames = collect_fallback_frames(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            initial_lines=initial_lines,
        )
        return frames, RECOVERY_TEXT_LABEL

    if mode in {"fallback_marked", "fallback"}:
        frames = collect_fallback_frames(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            initial_lines=initial_lines,
        )
        return frames, RECOVERY_TEXT_LABEL

    initial_frames = _parse_initial_payload_frames(initial_lines)
    frames = collect_payload_frames(
        allow_unsigned=allow_unsigned,
        quiet=quiet,
        initial_frames=initial_frames,
    )
    return frames, RECOVERY_QR_TEXT_LABEL


def collect_fallback_frames(
    *,
    allow_unsigned: bool,
    quiet: bool,
    initial_lines: list[str] | None,
) -> list[Frame]:
    """Collect fallback recovery text until it decodes into frames."""

    lines = list(initial_lines or [])
    if not quiet:
        console.print(
            "[subtitle]"
            "Paste recovery text one section at a time. Press Enter on a blank line to finish "
            "each section."
            "[/subtitle]"
        )
    help_text: str | None = (
        "Paste recovery text. You can paste it in sections, and we'll keep asking until it decodes."
    )
    prompt_label = "Paste recovery text (blank line ends this section)"

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
            prompt_label = "Paste more recovery text (blank line ends this section)"

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
            prompt_label = "Paste more recovery text (blank line ends this section)"


@dataclass
class _PayloadCollectionState:
    """Track incremental QR payload collection and completion state."""

    allow_unsigned: bool
    quiet: bool
    frames: list[Frame] = field(default_factory=list)
    seen: dict[tuple[int, int, bytes], Frame] = field(default_factory=dict)
    main_indices_by_doc_id: dict[bytes, set[int]] = field(default_factory=dict)
    main_total_by_doc_id: dict[bytes, int] = field(default_factory=dict)
    auth_doc_ids: set[bytes] = field(default_factory=set)

    def next_prompt(self) -> str:
        """Return the next prompt label based on remaining payloads."""

        if not self.main_total_by_doc_id:
            return "Backup text line"
        remaining_main = sum(
            max(total - len(self.main_indices_by_doc_id.get(doc_id, set())), 0)
            for doc_id, total in self.main_total_by_doc_id.items()
        )
        remaining_auth = (
            0
            if self.allow_unsigned
            else sum(1 for doc_id in self.main_total_by_doc_id if doc_id not in self.auth_doc_ids)
        )
        remaining_total = remaining_main + remaining_auth
        if remaining_main == 0 and remaining_auth:
            plural = "s" if remaining_auth != 1 else ""
            return f"Verification text line{plural} ({remaining_auth} remaining)"
        return f"Backup text line ({remaining_total} remaining)"

    def ingest(self, frame: Frame) -> bool:
        """Validate and store a QR frame, returning whether collection is complete."""

        if frame.frame_type not in (FrameType.MAIN_DOCUMENT, FrameType.AUTH):
            console_err.print(
                "[error]Only backup text lines for this backup belong here. "
                "If you have recovery text instead, go back and choose Recovery text.[/error]"
            )
            return False

        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            main_total = self.main_total_by_doc_id.get(frame.doc_id)
            if main_total is None:
                self.main_total_by_doc_id[frame.doc_id] = frame.total
            elif frame.total != main_total:
                console_err.print(
                    "[error]Frame count doesn't match earlier text lines. "
                    "Use text lines from the same backup.[/error]"
                )
                return False

        key = (int(frame.frame_type), int(frame.index), frame.doc_id)
        existing = self.seen.get(key)
        if existing is not None:
            if existing.data != frame.data or existing.total != frame.total:
                console_err.print(
                    "[error]That text line conflicts with one you've already provided. "
                    "Keep only one version of each frame index.[/error]"
                )
            elif not self.quiet:
                console.print("[subtitle]Duplicate text line ignored.[/subtitle]")
            return False

        self.seen[key] = frame
        self.frames.append(frame)
        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            self.main_indices_by_doc_id.setdefault(frame.doc_id, set()).add(frame.index)
        else:
            self.auth_doc_ids.add(frame.doc_id)

        return self._is_complete()

    def _is_complete(self) -> bool:
        """Return whether the required MAIN/AUTH payload set has been collected."""

        if not self.main_total_by_doc_id:
            return False

        remaining_main = sum(
            max(total - len(self.main_indices_by_doc_id.get(doc_id, set())), 0)
            for doc_id, total in self.main_total_by_doc_id.items()
        )
        remaining_auth = (
            0
            if self.allow_unsigned
            else sum(1 for doc_id in self.main_total_by_doc_id if doc_id not in self.auth_doc_ids)
        )
        if remaining_main == 0 and remaining_auth == 0:
            if not self.quiet:
                console.print("[success]All required backup text lines captured.[/success]")
            return True
        return False


def collect_payload_frames(
    *,
    allow_unsigned: bool,
    quiet: bool,
    first_frame: Frame | None = None,
    initial_frames: list[Frame] | None = None,
) -> list[Frame]:
    """Collect QR payload lines interactively until the required set is complete."""

    if not quiet:
        console.print(
            "[subtitle]"
            "Paste one backup text line per line. Include the extra verification line if asked."
            "[/subtitle]"
        )
    help_text: str | None = (
        "Paste one backup text line per line. We'll stop once everything needed is collected."
    )
    state = _PayloadCollectionState(allow_unsigned=allow_unsigned, quiet=quiet)
    for frame in initial_frames or []:
        state.ingest(frame)
    if initial_frames and state._is_complete():
        return state.frames
    if first_frame is not None:
        state.ingest(first_frame)
    if first_frame is not None and state._is_complete():
        return state.frames

    while True:
        payload_text = prompt_required(state.next_prompt(), help_text=help_text)
        help_text = None
        try:
            frame = _frame_from_payload_text(payload_text)
        except ValueError as exc:
            console_err.print(f"[error]{format_recovery_input_error(exc)}[/error]")
            continue

        if state.ingest(frame):
            return state.frames


def _prompt_recovery_text_input_kind() -> RecoveryTextInputKind:
    selected = prompt_choice(
        "What kind of text do you have",
        {
            "fallback": "Recovery text",
            "payload": "Backup text lines",
            "auto": "I'm not sure",
        },
        default="fallback",
        help_text=(
            "Choose the exact text type when you know it. Use 'I'm not sure' only if you need "
            "Ethernity to figure it out."
        ),
    )
    return cast(RecoveryTextInputKind, selected)


def _recovery_text_path_prompt(input_kind: RecoveryTextInputKind) -> str:
    if input_kind == "fallback":
        return "Recovery text file (or '-' to paste)"
    if input_kind == "payload":
        return "Backup text file (QR lines, or '-' to paste)"
    return "Recovery text or backup text file (QR lines, or '-' to paste)"


def _recovery_text_path_help(input_kind: RecoveryTextInputKind) -> str:
    if input_kind == "fallback":
        return "Choose a text file with recovery text, or enter '-' to paste it."
    if input_kind == "payload":
        return (
            "Choose a text file with backup text lines copied from QR codes, "
            "or enter '-' to paste them."
        )
    return (
        "Choose a text file with recovery text or backup text lines copied from QR codes, "
        "or enter '-' to paste. Ethernity will auto-detect the format."
    )


def _recovery_text_picker_prompt(input_kind: RecoveryTextInputKind) -> str:
    if input_kind == "fallback":
        return "Select a recovery text file"
    if input_kind == "payload":
        return "Select a backup text file"
    return "Select a recovery text or backup text file"


def _recovery_text_status_label(input_kind: RecoveryTextInputKind) -> str:
    if input_kind == "fallback":
        return "Reading recovery text..."
    if input_kind == "payload":
        return "Reading backup text lines..."
    return "Reading recovery input..."


def _recovery_text_stdin_prompt(input_kind: RecoveryTextInputKind) -> str:
    if input_kind == "fallback":
        return RECOVERY_TEXT_LABEL
    if input_kind == "payload":
        return "Backup text lines"
    return "Recovery text or backup text"


def _recovery_text_stdin_help(input_kind: RecoveryTextInputKind) -> str:
    if input_kind == "fallback":
        return "Paste recovery text. You can paste one section or a full block."
    if input_kind == "payload":
        return "Paste one backup text line per line. You can paste several lines at once."
    return (
        "Paste recovery text or backup text lines. If detection is wrong, go back and choose the "
        "exact artifact type."
    )


def _nonempty_input_lines(entry: str) -> list[str]:
    lines = [line for line in entry.splitlines() if line.strip()]
    if lines:
        return lines
    return [entry]


def _parse_initial_payload_frames(initial_lines: list[str]) -> list[Frame]:
    try:
        return _frames_from_payload_lines(initial_lines, label="backup text lines", source="stdin")
    except ValueError as exc:
        console_err.print(f"[error]invalid backup text lines in stdin: {exc}[/error]")
        return []
