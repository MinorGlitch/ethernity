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

import os
import sys

from ...core.bounds import MAX_QR_PAYLOAD_CHARS, MAX_RECOVERY_TEXT_BYTES
from ...encoding.framing import Frame, FrameType, decode_frame
from ...encoding.qr_payloads import decode_qr_payload
from ...qr.scan import QrScanError, scan_qr_payloads
from ..core.log import _warn
from ..core.text import format_qr_input_error
from .fallback_parser import (
    contains_fallback_markers as _contains_fallback_markers,
    filter_fallback_lines as _filter_fallback_lines,
    parse_fallback_frame as _parse_fallback_frame,
    split_fallback_sections as _split_fallback_sections,
)


def format_recovery_input_error(exc: Exception) -> str:
    message = str(exc)
    return format_qr_input_error(
        message,
        bad_payload_hint=(
            "That doesn't look like a QR payload. Try scanning images or paste recovery text."
        ),
        no_qr_hint="No QR data found. Try a clearer scan or paste recovery text.",
        scan_failed_hint="Check the scan path and try again.",
        file_hint="Check the path and try again.",
        default_hint="Try scanning images or paste recovery text.",
    )


def _read_text_lines(path: str) -> list[str]:
    if path == "-":
        text = sys.stdin.read()
        text_bytes = len(text.encode("utf-8"))
        if text_bytes > MAX_RECOVERY_TEXT_BYTES:
            raise ValueError(
                "recovery input exceeds "
                f"MAX_RECOVERY_TEXT_BYTES ({MAX_RECOVERY_TEXT_BYTES}): {text_bytes} bytes"
            )
    else:
        try:
            file_bytes = os.path.getsize(path)
        except OSError:
            file_bytes = None
        if file_bytes is not None and file_bytes > MAX_RECOVERY_TEXT_BYTES:
            raise ValueError(
                "recovery input exceeds "
                f"MAX_RECOVERY_TEXT_BYTES ({MAX_RECOVERY_TEXT_BYTES}): {file_bytes} bytes"
            )
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"file is not UTF-8 text: {path}. "
                "If this is a PDF or image, scan it for QR payloads instead."
            ) from exc
        except FileNotFoundError as exc:
            raise ValueError(f"file not found: {path}") from exc
        except OSError as exc:
            raise ValueError(f"unable to read file: {path}") from exc
        text_bytes = len(text.encode("utf-8"))
        if text_bytes > MAX_RECOVERY_TEXT_BYTES:
            raise ValueError(
                "recovery input exceeds "
                f"MAX_RECOVERY_TEXT_BYTES ({MAX_RECOVERY_TEXT_BYTES}): {text_bytes} bytes"
            )
    return text.splitlines()


def _frame_from_fallback(path: str) -> Frame:
    lines = _read_text_lines(path)
    return _frame_from_fallback_lines(lines, label="fallback")


def _parse_fallback_section(
    lines: list[str],
    section_key: str,
    *,
    allow_invalid: bool,
    quiet: bool,
    missing_error: str,
) -> Frame | None:
    """Parse a specific section from fallback lines, returning None if invalid and allowed."""
    if not _contains_fallback_markers(lines):
        return _frame_from_fallback_lines(lines, label=section_key)

    sections = _split_fallback_sections(lines)
    section_lines = sections.get(section_key)

    if not section_lines:
        raise ValueError(missing_error)

    try:
        return _frame_from_fallback_lines(section_lines, label=section_key)
    except ValueError as exc:
        if allow_invalid:
            _warn(f"invalid {section_key} fallback ignored: {exc}", quiet=quiet)
            return None
        raise


def _frames_from_fallback_lines(
    lines: list[str],
    *,
    allow_invalid_auth: bool,
    quiet: bool,
) -> list[Frame]:
    if not _contains_fallback_markers(lines):
        return [_frame_from_fallback_lines(lines, label="fallback")]

    sections = _split_fallback_sections(lines)
    if not sections["main"]:
        raise ValueError("missing MAIN fallback section; include the MAIN section from recovery")

    frames: list[Frame] = [_frame_from_fallback_lines(sections["main"], label="main")]
    if sections["auth"]:
        try:
            frames.append(_frame_from_fallback_lines(sections["auth"], label="auth"))
        except ValueError as exc:
            if allow_invalid_auth:
                _warn(f"invalid auth fallback ignored: {exc}", quiet=quiet)
            else:
                raise
    return frames


def _frames_from_fallback(path: str, *, allow_invalid_auth: bool, quiet: bool) -> list[Frame]:
    lines = _read_text_lines(path)
    return _frames_from_fallback_lines(lines, allow_invalid_auth=allow_invalid_auth, quiet=quiet)


def _non_empty_lines(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def _all_payload_lines_decode(lines: list[str]) -> bool:
    non_empty = _non_empty_lines(lines)
    if not non_empty:
        return False
    for line in non_empty:
        try:
            _frame_from_payload_text(line)
        except ValueError:
            return False
    return True


def _all_lines_match_fallback_text(lines: list[str]) -> bool:
    non_empty = _non_empty_lines(lines)
    if not non_empty:
        return False
    filtered, skipped = _filter_fallback_lines(non_empty)
    return skipped == 0 and len(filtered) == len(non_empty)


def _detect_recovery_input_mode(lines: list[str]) -> str:
    if _contains_fallback_markers(lines):
        return "fallback_marked"
    if _all_payload_lines_decode(lines):
        return "payload"
    if _all_lines_match_fallback_text(lines):
        return "fallback"
    raise ValueError(
        "input is neither a valid QR payload list nor valid fallback text; "
        "provide one format per input"
    )


def _auth_frames_from_fallback_lines(
    lines: list[str],
    *,
    allow_invalid_auth: bool,
    quiet: bool,
) -> list[Frame]:
    frame = _parse_fallback_section(
        lines,
        "auth",
        allow_invalid=allow_invalid_auth,
        quiet=quiet,
        missing_error=(
            "missing AUTH fallback section; include AUTH or use "
            "--rescue-mode (or --skip-auth-check)"
        ),
    )
    return [frame] if frame else []


def _auth_frames_from_fallback(path: str, *, allow_invalid_auth: bool, quiet: bool) -> list[Frame]:
    lines = _read_text_lines(path)
    return _auth_frames_from_fallback_lines(
        lines,
        allow_invalid_auth=allow_invalid_auth,
        quiet=quiet,
    )


def _frame_from_fallback_lines(lines: list[str], *, label: str) -> Frame:
    frame, skipped = _parse_fallback_frame(lines, label=label)
    if skipped:
        _warn(f"skipped {skipped} non-fallback lines ({label})", quiet=False)
    return frame


def _frames_from_payload_lines(
    lines: list[str],
    *,
    label: str = "QR payloads",
    source: str = "input",
) -> list[Frame]:
    frames: list[Frame] = []
    for idx, line in enumerate(lines, start=1):
        payload_text = line.strip()
        if not payload_text:
            continue
        try:
            frames.append(_frame_from_payload_text(payload_text))
        except ValueError as exc:
            raise ValueError(f"invalid QR payload on line {idx}: {exc}") from exc
    if not frames:
        raise ValueError(f"no {label} found in {source}; check the payload data")
    return frames


def _frames_from_payloads(path: str, *, label: str = "QR payloads") -> list[Frame]:
    lines = _read_text_lines(path)
    return _frames_from_payload_lines(lines, label=label, source=path)


def _auth_frames_from_payloads(path: str) -> list[Frame]:
    frames = _frames_from_payloads(path, label="auth QR payloads")
    for frame in frames:
        if frame.frame_type != FrameType.AUTH:
            raise ValueError("auth QR payloads file must contain AUTH payloads only")
    return frames


def _frames_from_shard_inputs(
    fallback_files: list[str],
    frame_files: list[str],
) -> list[Frame]:
    frames: list[Frame] = []
    for path in fallback_files:
        frames.append(_frame_from_fallback(path))
    for path in frame_files:
        frames.extend(_frames_from_payloads(path, label="shard QR payloads"))
    return frames


def _frames_from_scan(paths: list[str]) -> list[Frame]:
    try:
        payloads = scan_qr_payloads(paths)
    except QrScanError as exc:
        raise ValueError(f"scan failed: {exc}") from exc
    if not payloads:
        raise ValueError("no QR payloads found; check the scan path and image quality")
    frames: list[Frame] = []
    errors: list[str] = []
    for idx, payload in enumerate(payloads, start=1):
        try:
            frames.append(_frame_from_payload_text(payload))
        except ValueError as exc:
            errors.append(f"#{idx}: {exc}")
            continue
    if not frames:
        if errors:
            detail = "; ".join(errors[:3])
            raise ValueError(f"invalid QR payloads ({len(errors)}): {detail}")
        raise ValueError("no QR payloads found; check the scan path and image quality")
    return frames


def _dedupe_frames(frames: list[Frame]) -> list[Frame]:
    seen: dict[tuple[int, int, bytes], Frame] = {}
    deduped: list[Frame] = []
    for frame in frames:
        key = (int(frame.frame_type), int(frame.index), frame.doc_id)
        existing = seen.get(key)
        if existing:
            if existing.data != frame.data or existing.total != frame.total:
                raise ValueError("conflicting duplicate frames detected")
            continue
        seen[key] = frame
        deduped.append(frame)
    return deduped


def _dedupe_auth_frames(frames: list[Frame]) -> list[Frame]:
    if not frames:
        return []
    deduped = _dedupe_frames(frames)
    for frame in deduped:
        if frame.frame_type != FrameType.AUTH:
            raise ValueError("auth payloads must be AUTH type")
    return deduped


def _split_main_and_auth_frames(frames: list[Frame]) -> tuple[list[Frame], list[Frame]]:
    main_frames: list[Frame] = []
    auth_frames: list[Frame] = []
    for frame in frames:
        if frame.frame_type == FrameType.MAIN_DOCUMENT:
            main_frames.append(frame)
        elif frame.frame_type == FrameType.AUTH:
            auth_frames.append(frame)
        else:
            raise ValueError("unexpected frame type in main document QR payloads")
    if not main_frames:
        raise ValueError(
            "no main document payloads provided; check the MAIN QR payloads or recovery text"
        )
    return main_frames, auth_frames


def _decode_payload(text: bytes | str) -> bytes:
    if isinstance(text, bytes):
        try:
            decoded_text = text.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("QR payload text must be ASCII") from exc
    else:
        decoded_text = text
    cleaned = "".join(decoded_text.split())
    if len(cleaned) > MAX_QR_PAYLOAD_CHARS:
        raise ValueError(
            f"QR payload exceeds MAX_QR_PAYLOAD_CHARS ({MAX_QR_PAYLOAD_CHARS}): "
            f"{len(cleaned)} chars"
        )
    return decode_qr_payload(cleaned)


def _frame_from_payload_text(payload_text: bytes | str) -> Frame:
    payload = _decode_payload(payload_text)
    return decode_frame(payload)
