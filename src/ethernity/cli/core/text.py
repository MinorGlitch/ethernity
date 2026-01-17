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


def append_hint(message: str, hint: str) -> str:
    if not hint:
        return message
    if message.endswith((".", "!", "?")):
        return f"{message} {hint}"
    return f"{message}. {hint}"


def format_qr_input_error(
    message: str,
    *,
    bad_payload_hint: str,
    no_qr_hint: str | None = None,
    scan_failed_hint: str | None = None,
    file_hint: str | None = None,
    default_hint: str | None = None,
) -> str:
    lowered = message.lower()
    if (
        "invalid qr payload" in lowered
        or "bad magic" in lowered
        or "frame length mismatch" in lowered
        or "crc mismatch" in lowered
    ):
        return bad_payload_hint
    if "no qr payloads found" in lowered:
        return no_qr_hint or bad_payload_hint
    if "scan failed" in lowered and scan_failed_hint:
        return append_hint(message, scan_failed_hint)
    if ("file not found" in lowered or "unable to read file" in lowered) and file_hint:
        return append_hint(message, file_hint)
    if default_hint:
        return append_hint(message, default_hint)
    return message
