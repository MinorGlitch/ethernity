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

"""Load recovery, authentication, and shard frames from workflow inputs."""

from __future__ import annotations

from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE, decode_shard_payload
from ethernity.encoding.fallback_text import format_fallback_error
from ethernity.encoding.framing import Frame, FrameType
from ethernity.workflows.recovery import frame_inputs
from ethernity.workflows.recovery.constants import (
    RECOVERY_QR_TEXT_LABEL,
    RECOVERY_SCAN_LABEL,
)
from ethernity.workflows.shared.events import emit_phase
from ethernity.workflows.shared.notices import WorkflowNotice, WorkflowNoticeSink, warn
from ethernity.workflows.shared.paths import expanduser_cli_path, expanduser_cli_paths
from ethernity.workflows.shared.requests import RecoveryRequest


def _notice_sink(quiet: bool) -> WorkflowNoticeSink:
    def emit(notice: WorkflowNotice) -> None:
        warn(
            notice.message,
            quiet=quiet,
            code=notice.code,
            details=dict(notice.details),
        )

    return emit


def load_recovery_frames(
    args: RecoveryRequest,
    *,
    allow_unsigned: bool,
    quiet: bool,
    include_recovery_sheets: bool = False,
) -> tuple[list[Frame], str | None, str | None]:
    """Load primary recovery frames from fallback text, payload lists, scans, or mixed inputs."""

    emit_phase(phase="source", label="Reading backup documents")
    fallback_file = expanduser_cli_path(args.recovery_text_file)
    payloads_file = expanduser_cli_path(args.payloads_file)
    scan = expanduser_cli_paths(args.scan_paths)
    sources: list[tuple[str, str, list[Frame]]] = []

    if args.frames:
        sources.append(
            (
                "Pasted recovery text",
                "in memory",
                list(args.frames),
            )
        )
    if fallback_file:
        sources.append(
            (
                "Recovery text",
                fallback_file,
                _load_recovery_fallback(fallback_file, allow_unsigned=allow_unsigned, quiet=quiet),
            )
        )
    if payloads_file:
        try:
            sources.append(
                (
                    RECOVERY_QR_TEXT_LABEL,
                    payloads_file,
                    frame_inputs.frames_from_payloads(payloads_file),
                )
            )
        except ValueError as exc:
            raise ValueError(frame_inputs.format_recovery_input_error(exc)) from exc
    if scan:
        sources.append(
            (
                RECOVERY_SCAN_LABEL,
                ", ".join(scan),
                _load_recovery_scan(
                    scan, include_recovery_sheets=include_recovery_sheets, quiet=quiet
                ),
            )
        )
    if not sources:
        raise ValueError("either --fallback-file, --payloads-file, or --scan is required")
    if len(sources) == 1:
        input_label, input_detail, frames = sources[0]
    else:
        input_label = "Recovery inputs"
        input_detail = "; ".join(f"{label}: {detail}" for label, detail, _frames in sources)
        frames = [frame for _label, _detail, source_frames in sources for frame in source_frames]
    return frames, input_label, input_detail


def _load_recovery_fallback(path: str, *, allow_unsigned: bool, quiet: bool) -> list[Frame]:
    try:
        return list(
            frame_inputs.frames_from_fallback(
                path,
                allow_invalid_auth=allow_unsigned,
                notice_sink=_notice_sink(quiet),
            ).frames
        )
    except ValueError as exc:
        if path == "-" and "no recovery lines found" in str(exc).lower():
            raise ValueError(
                "No recovery input found on stdin. Use --fallback-file, --payloads-file, "
                "--scan, or provide non-empty stdin."
            ) from exc
        raise ValueError(format_fallback_error(exc, context="Recovery text")) from exc


def _load_recovery_scan(
    paths: list[str], *, include_recovery_sheets: bool, quiet: bool
) -> list[Frame]:
    try:
        if include_recovery_sheets:
            return frame_inputs.frames_from_scan(paths)
        return list(
            frame_inputs.recovery_frames_from_scan(paths, notice_sink=_notice_sink(quiet)).frames
        )
    except ValueError as exc:
        raise ValueError(frame_inputs.format_recovery_input_error(exc)) from exc


def route_document_frames(
    frames: list[Frame],
    shard_frames: list[Frame],
    *,
    passphrase: str | None,
) -> tuple[list[Frame], list[Frame]]:
    """Route decoded document roles while retaining normal shard binding validation.

    An explicit passphrase remains the chosen unlock method. Sheets discovered in a
    collection are used when no passphrase was supplied; explicit conflicting unlock
    inputs still reach the existing mutual-exclusion checks.
    """

    recovery_frames = [frame for frame in frames if frame.frame_type != FrameType.KEY_DOCUMENT]
    detected_shards = (
        document_sheet_frames(frames, key_type=KEY_TYPE_PASSPHRASE) if not passphrase else []
    )
    return recovery_frames, [*shard_frames, *detected_shards]


def document_sheet_frames(frames: list[Frame], *, key_type: str) -> list[Frame]:
    """Identify decoded sheet roles without treating their contents as authenticated."""

    return [
        frame
        for frame in frames
        if frame.frame_type == FrameType.KEY_DOCUMENT
        and decode_shard_payload(frame.data).key_type == key_type
    ]


def load_extra_auth_frames(
    args: RecoveryRequest,
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> list[Frame]:
    """Load extra AUTH frames from optional auth-specific inputs."""

    emit_phase(phase="authentication", label="Reading authentication inputs")
    auth_fallback_file = expanduser_cli_path(args.auth_text_file)
    auth_payloads_file = expanduser_cli_path(args.auth_payloads_file)
    if auth_fallback_file and auth_payloads_file:
        raise ValueError("use either --auth-fallback-file or --auth-payloads-file, not both")
    extra_auth_frames: list[Frame] = list(args.auth_frames or [])
    if auth_fallback_file:
        try:
            extra_auth_frames.extend(
                frame_inputs.auth_frames_from_fallback(
                    auth_fallback_file,
                    allow_invalid_auth=allow_unsigned,
                    notice_sink=_notice_sink(quiet),
                ).frames
            )
        except ValueError as exc:
            raise ValueError(format_fallback_error(exc, context="Auth recovery text")) from exc
    if auth_payloads_file:
        extra_auth_frames.extend(frame_inputs.auth_frames_from_payloads(auth_payloads_file))
    return extra_auth_frames


def load_shard_frames(
    args: RecoveryRequest,
    *,
    quiet: bool,
) -> tuple[list[Frame], list[str], list[str], list[str]]:
    """Load shard frames from shard fallback, payload, and scan inputs."""

    emit_phase(phase="unlock", label="Reading recovery sheets")
    shard_fallback_files = expanduser_cli_paths(args.shard_text_files)
    shard_payloads_file = expanduser_cli_paths(args.shard_payload_files)
    shard_scan = expanduser_cli_paths(args.shard_scan_paths)
    shard_frames: list[Frame] = list(args.shard_frames or [])
    for path in shard_fallback_files:
        try:
            shard_frames.append(frame_inputs.frame_from_fallback(path))
        except ValueError as exc:
            raise ValueError(format_fallback_error(exc, context="Shard recovery text")) from exc
    for path in shard_payloads_file:
        try:
            shard_frames.extend(frame_inputs.frames_from_payloads(path, label="shard text lines"))
        except ValueError as exc:
            raise ValueError(frame_inputs.format_shard_input_error(exc)) from exc
    if shard_scan:
        try:
            shard_frames.extend(
                frame_inputs.shard_frames_from_scan(
                    shard_scan,
                    notice_sink=_notice_sink(quiet),
                ).frames
            )
        except ValueError as exc:
            raise ValueError(frame_inputs.format_shard_input_error(exc)) from exc
    if (
        args.shard_frames or shard_fallback_files or shard_payloads_file or shard_scan
    ) and not shard_frames:
        raise ValueError("no shard text lines found; check shard inputs and try again")
    return shard_frames, shard_fallback_files, shard_payloads_file, shard_scan


__all__ = [
    "load_extra_auth_frames",
    "load_recovery_frames",
    "load_shard_frames",
    "route_document_frames",
    "document_sheet_frames",
]
