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

from pathlib import Path

from ethernity.encoding.fallback_text import format_fallback_error
from ethernity.encoding.framing import Frame
from ethernity.workflows.recovery import frame_inputs
from ethernity.workflows.recovery.constants import (
    RECOVERY_QR_TEXT_LABEL,
    RECOVERY_SCAN_LABEL,
)
from ethernity.workflows.shared.notices import warn
from ethernity.workflows.shared.operation_types import RecoverArgs
from ethernity.workflows.shared.paths import expanduser_cli_path, expanduser_cli_paths


def _notice_sink(quiet: bool) -> frame_inputs.FrameInputNoticeSink:
    def emit(notice: frame_inputs.FrameInputNotice) -> None:
        warn(
            notice.message,
            quiet=quiet,
            code=notice.code,
            details=dict(notice.details),
        )

    return emit


def load_recovery_frames(
    args: RecoverArgs,
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> tuple[list[Frame], str | None, str | None, Path | None]:
    """Load primary recovery frames from fallback text, payload lists, scans, or mixed inputs."""

    fallback_file = expanduser_cli_path(args.fallback_file)
    payloads_file = expanduser_cli_path(args.payloads_file)
    scan = expanduser_cli_paths(list(args.scan or []))
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
        try:
            sources.append(
                (
                    "Recovery text",
                    fallback_file,
                    list(
                        frame_inputs.frames_from_fallback(
                            fallback_file,
                            allow_invalid_auth=allow_unsigned,
                            notice_sink=_notice_sink(quiet),
                        ).frames
                    ),
                )
            )
        except ValueError as exc:
            message = str(exc).lower()
            if fallback_file == "-" and "no recovery lines found" in message:
                raise ValueError(
                    "No recovery input found on stdin. Use --fallback-file, --payloads-file, "
                    "--scan, or provide non-empty stdin."
                ) from exc
            raise ValueError(format_fallback_error(exc, context="Recovery text")) from exc
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
        scan_detail = ", ".join(scan)
        try:
            if args.extension_index == 0:
                scan_result = frame_inputs.recovery_frames_from_scan(
                    scan,
                    include_extension_carriers=False,
                    notice_sink=_notice_sink(quiet),
                )
            elif args.extension_index is not None:
                scan_result = frame_inputs.recovery_frames_from_scan(
                    scan,
                    extension_carrier_max_index=args.extension_index,
                    notice_sink=_notice_sink(quiet),
                )
            else:
                scan_result = frame_inputs.recovery_frames_from_scan(
                    scan,
                    notice_sink=_notice_sink(quiet),
                )
            scan_frames = list(scan_result.frames)
            sources.append(
                (
                    RECOVERY_SCAN_LABEL,
                    scan_detail,
                    scan_frames,
                )
            )
        except ValueError as exc:
            raise ValueError(frame_inputs.format_recovery_input_error(exc)) from exc
    if not sources:
        raise ValueError("either --fallback-file, --payloads-file, or --scan is required")
    if len(sources) == 1:
        input_label, input_detail, frames = sources[0]
    else:
        input_label = "Recovery inputs"
        input_detail = "; ".join(f"{label}: {detail}" for label, detail, _frames in sources)
        frames = [frame for _label, _detail, source_frames in sources for frame in source_frames]
    return frames, input_label, input_detail, None


def load_extra_auth_frames(
    args: RecoverArgs,
    *,
    allow_unsigned: bool,
    quiet: bool,
) -> list[Frame]:
    """Load extra AUTH frames from optional auth-specific inputs."""

    auth_fallback_file = expanduser_cli_path(args.auth_fallback_file)
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
    args: RecoverArgs,
    *,
    quiet: bool,
) -> tuple[list[Frame], list[str], list[str], list[str]]:
    """Load shard frames from shard fallback, payload, and scan inputs."""

    shard_fallback_files = expanduser_cli_paths(list(args.shard_fallback_file or []))
    shard_payloads_file = expanduser_cli_paths(list(args.shard_payloads_file or []))
    shard_scan = expanduser_cli_paths(list(args.shard_scan or []))
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
]
