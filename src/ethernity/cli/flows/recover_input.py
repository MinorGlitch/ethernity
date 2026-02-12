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

from dataclasses import dataclass, field

from ...encoding.framing import Frame, FrameType
from ..api import (
    console,
    console_err,
    prompt_choice,
    prompt_multiline,
    prompt_path_with_picker,
    prompt_required,
    status,
)
from ..io.fallback_parser import format_fallback_error
from ..io.frames import (
    _detect_recovery_input_mode,
    _frame_from_payload_text,
    _frames_from_fallback_lines,
    _frames_from_payload_lines,
    _frames_from_scan,
    _read_text_lines,
    format_recovery_input_error,
)


def prompt_recovery_input_interactive(
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list[Frame], str, str]:
    """Prompt for recovery source and return (frames, input_label, input_detail)."""
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
                    frames, input_label = prompt_text_or_payloads_stdin(
                        allow_unsigned=allow_unsigned,
                        quiet=quiet,
                    )
                else:
                    with status("Reading recovery input...", quiet=quiet):
                        lines = _read_text_lines(path)
                        frames, input_label = parse_recovery_lines(
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
                    frames = _frames_from_scan([path])
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
        return frames, "Recovery text"

    try:
        frames = _frames_from_payload_lines(lines, label="QR payloads", source=source)
        return frames, "QR payloads"
    except ValueError as exc:
        raise ValueError(f"invalid QR payloads in {source}: {exc}") from exc


def prompt_text_or_payloads_stdin(
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list[Frame], str]:
    first_line = prompt_required(
        "Recovery text or QR payload (first line or block)",
        help_text="Paste recovery text or a QR payload; we'll keep asking until it decodes.",
    )
    initial_lines = [line for line in first_line.splitlines() if line.strip()]
    if not initial_lines:
        initial_lines = [first_line]

    try:
        mode = _detect_recovery_input_mode(initial_lines)
    except ValueError:
        frames = collect_fallback_frames(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            initial_lines=initial_lines,
        )
        return frames, "Recovery text"

    if mode in {"fallback_marked", "fallback"}:
        frames = collect_fallback_frames(
            allow_unsigned=allow_unsigned,
            quiet=quiet,
            initial_lines=initial_lines,
        )
        return frames, "Recovery text"

    first_payload = initial_lines[0].strip()
    first_frame = _frame_from_payload_text(first_payload)
    frames = collect_payload_frames(
        allow_unsigned=allow_unsigned,
        quiet=quiet,
        first_frame=first_frame,
    )
    return frames, "QR payloads"


def collect_fallback_frames(
    *,
    allow_unsigned: bool,
    quiet: bool,
    initial_lines: list[str] | None,
) -> list[Frame]:
    lines = list(initial_lines or [])
    if not quiet:
        console.print(
            "[subtitle]"
            "Paste fallback recovery text in batches; submit a batch with a blank line."
            "[/subtitle]"
        )
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


@dataclass
class _PayloadCollectionState:
    allow_unsigned: bool
    quiet: bool
    frames: list[Frame] = field(default_factory=list)
    seen: dict[tuple[int, int, bytes], Frame] = field(default_factory=dict)
    main_indices: set[int] = field(default_factory=set)
    main_total: int | None = None
    auth_present: bool = False
    expected_doc_id: bytes | None = None

    def next_prompt(self) -> str:
        if self.main_total is None:
            return "QR payload"
        remaining_main = max(self.main_total - len(self.main_indices), 0)
        remaining_auth = 0 if self.allow_unsigned or self.auth_present else 1
        remaining_total = remaining_main + remaining_auth
        if remaining_main == 0 and remaining_auth == 1:
            return "Auth QR payload (1 remaining)"
        return f"QR payload ({remaining_total} remaining)"

    def ingest(self, frame: Frame) -> bool:
        if frame.frame_type not in (FrameType.MAIN_DOCUMENT, FrameType.AUTH):
            console_err.print(
                "[error]Only MAIN or AUTH QR payloads are accepted here. "
                "Paste a MAIN/AUTH payload for this document.[/error]"
            )
            return False

        if self.expected_doc_id is None:
            self.expected_doc_id = frame.doc_id
        elif frame.doc_id != self.expected_doc_id:
            console_err.print(
                "[error]These payloads are from different documents. "
                "Continue with payloads from a single backup.[/error]"
            )
            return False

        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            if self.main_total is None:
                self.main_total = frame.total
            elif frame.total != self.main_total:
                console_err.print(
                    "[error]Frame count doesn't match earlier payloads. "
                    "Use payloads from the same frame set.[/error]"
                )
                return False

        key = (int(frame.frame_type), int(frame.index), frame.doc_id)
        existing = self.seen.get(key)
        if existing is not None:
            if existing.data != frame.data or existing.total != frame.total:
                console_err.print(
                    "[error]That payload conflicts with one you've already provided. "
                    "Keep only one version of each frame index.[/error]"
                )
            elif not self.quiet:
                console.print("[subtitle]Duplicate payload ignored.[/subtitle]")
            return False

        self.seen[key] = frame
        self.frames.append(frame)
        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            self.main_indices.add(frame.index)
        else:
            self.auth_present = True

        return self._is_complete()

    def _is_complete(self) -> bool:
        if self.main_total is None:
            return False

        remaining_main = max(self.main_total - len(self.main_indices), 0)
        remaining_auth = 0 if self.allow_unsigned or self.auth_present else 1
        if remaining_main == 0 and remaining_auth == 0:
            if not self.quiet:
                console.print("[success]All required QR payloads captured.[/success]")
            return True
        return False


def collect_payload_frames(
    *,
    allow_unsigned: bool,
    quiet: bool,
    first_frame: Frame | None = None,
) -> list[Frame]:
    if not quiet:
        console.print(
            "[subtitle]"
            "Paste one QR payload per line. Include auth payload when requested."
            "[/subtitle]"
        )
    help_text: str | None = (
        "Paste one QR payload per line; we'll stop once all required payloads are collected."
    )
    state = _PayloadCollectionState(allow_unsigned=allow_unsigned, quiet=quiet)
    if first_frame is not None and state.ingest(first_frame):
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
