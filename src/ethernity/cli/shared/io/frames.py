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

"""CLI compatibility facade for adapter-neutral recovery frame inputs."""

from __future__ import annotations

from ethernity.cli.shared.log import warn
from ethernity.encoding.framing import Frame
from ethernity.workflows.recovery import frame_inputs as _frame_inputs

NoQrFramesError = _frame_inputs.NoQrFramesError

__all__ = [
    "NoQrFramesError",
    "auth_frames_from_fallback",
    "auth_frames_from_payloads",
    "frame_from_fallback",
    "format_recovery_input_error",
    "format_shard_input_error",
    "frames_from_fallback",
    "frames_from_fallback_text",
    "frames_from_payloads",
    "frames_from_scan",
    "recovery_frames_from_scan",
    "shard_frames_from_scan",
]


def _notice_sink(quiet: bool) -> _frame_inputs.FrameInputNoticeSink:
    def emit(notice: _frame_inputs.FrameInputNotice) -> None:
        warn(
            notice.message,
            quiet=quiet,
            code=notice.code,
            details=dict(notice.details),
        )

    return emit


def format_recovery_input_error(exc: Exception) -> str:
    """Format recovery input errors with actionable user hints."""

    return _frame_inputs.format_recovery_input_error(exc)


def format_shard_input_error(exc: Exception) -> str:
    """Format shard QR input errors with shard-specific actionable hints."""

    return _frame_inputs.format_shard_input_error(exc)


def frame_from_fallback(path: str) -> Frame:
    """Decode a single fallback file into one frame."""

    return _frame_inputs.frame_from_fallback(path)


def frames_from_fallback(path: str, *, allow_invalid_auth: bool, quiet: bool) -> list[Frame]:
    """Read fallback text from a path and decode frames."""

    result = _frame_inputs.frames_from_fallback(
        path,
        allow_invalid_auth=allow_invalid_auth,
        notice_sink=_notice_sink(quiet),
    )
    return list(result.frames)


def frames_from_fallback_text(
    text: str,
    *,
    allow_invalid_auth: bool = False,
    quiet: bool = True,
) -> list[Frame]:
    """Decode pasted recovery text into MAIN and optional AUTH frames."""

    result = _frame_inputs.frames_from_fallback_text(
        text,
        allow_invalid_auth=allow_invalid_auth,
        notice_sink=_notice_sink(quiet),
    )
    return list(result.frames)


def auth_frames_from_fallback(path: str, *, allow_invalid_auth: bool, quiet: bool) -> list[Frame]:
    """Read and decode AUTH fallback frames from a file."""

    result = _frame_inputs.auth_frames_from_fallback(
        path,
        allow_invalid_auth=allow_invalid_auth,
        notice_sink=_notice_sink(quiet),
    )
    return list(result.frames)


def frames_from_payloads(path: str, *, label: str = "QR payloads") -> list[Frame]:
    """Read and decode QR payload lines from a text file."""

    return _frame_inputs.frames_from_payloads(path, label=label)


def auth_frames_from_payloads(path: str) -> list[Frame]:
    """Read and validate AUTH-only payload files."""

    return _frame_inputs.auth_frames_from_payloads(path)


def frames_from_scan(
    paths: list[str],
    *,
    include_extension_carriers: bool = True,
    extension_carrier_max_index: int | None = None,
) -> list[Frame]:
    """Scan PDFs/images for QR payloads and decode valid frames."""

    return _frame_inputs.frames_from_scan(
        paths,
        include_extension_carriers=include_extension_carriers,
        extension_carrier_max_index=extension_carrier_max_index,
    )


def recovery_frames_from_scan(
    paths: list[str],
    *,
    quiet: bool = False,
    include_extension_carriers: bool = True,
    extension_carrier_max_index: int | None = None,
) -> list[Frame]:
    """Scan recovery input and keep only MAIN/AUTH frames."""

    result = _frame_inputs.recovery_frames_from_scan(
        paths,
        include_extension_carriers=include_extension_carriers,
        extension_carrier_max_index=extension_carrier_max_index,
        notice_sink=_notice_sink(quiet),
    )
    return list(result.frames)


def shard_frames_from_scan(paths: list[str], *, quiet: bool = False) -> list[Frame]:
    """Scan shard input and keep only KEY_DOCUMENT frames."""

    result = _frame_inputs.shard_frames_from_scan(paths, notice_sink=_notice_sink(quiet))
    return list(result.frames)
