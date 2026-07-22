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

"""Stable adapter-neutral envelope summaries."""

from __future__ import annotations

from ethernity.formats.envelope_types import EnvelopeManifest


def manifest_summary_payload(manifest: EnvelopeManifest) -> dict[str, object]:
    """Build the stable envelope manifest summary used by inspection APIs."""

    return {
        "format_version": manifest.format_version,
        "input_origin": manifest.input_origin,
        "input_roots": list(manifest.input_roots),
        "sealed": manifest.sealed,
        "payload_codec": manifest.payload_codec,
        "payload_raw_len": manifest.payload_raw_len,
        "file_count": len(manifest.files),
    }


__all__ = ["manifest_summary_payload"]
