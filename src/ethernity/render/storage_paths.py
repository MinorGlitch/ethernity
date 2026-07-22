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

from typing import Literal

from ethernity.config.paths import STORAGE_RESOURCE_ROOT

STORAGE_ROOT = STORAGE_RESOURCE_ROOT
DEFAULT_LOGO_PATH = STORAGE_ROOT / "logo.png"

C6_PORTRAIT_WIDTH_MM = 114.0
C6_PORTRAIT_HEIGHT_MM = 162.0
C5_PORTRAIT_WIDTH_MM = 162.0
C5_PORTRAIT_HEIGHT_MM = 229.0
DL_PORTRAIT_WIDTH_MM = 110.0
DL_PORTRAIT_HEIGHT_MM = 220.0

EnvelopeKind = Literal["c6", "c5", "dl"]
EnvelopeOrientation = Literal["portrait", "landscape"]

_ENVELOPE_PORTRAIT_SIZES_MM: dict[EnvelopeKind, tuple[float, float]] = {
    "c6": (C6_PORTRAIT_WIDTH_MM, C6_PORTRAIT_HEIGHT_MM),
    "c5": (C5_PORTRAIT_WIDTH_MM, C5_PORTRAIT_HEIGHT_MM),
    "dl": (DL_PORTRAIT_WIDTH_MM, DL_PORTRAIT_HEIGHT_MM),
}


def c6_page_size_mm(orientation: EnvelopeOrientation) -> tuple[float, float]:
    return envelope_page_size_mm("c6", orientation)


def envelope_page_size_mm(
    kind: EnvelopeKind,
    orientation: EnvelopeOrientation,
) -> tuple[float, float]:
    width, height = _ENVELOPE_PORTRAIT_SIZES_MM[kind]
    if orientation == "landscape":
        width, height = height, width
    return width, height


__all__ = [
    "C5_PORTRAIT_HEIGHT_MM",
    "C5_PORTRAIT_WIDTH_MM",
    "C6_PORTRAIT_HEIGHT_MM",
    "C6_PORTRAIT_WIDTH_MM",
    "DL_PORTRAIT_HEIGHT_MM",
    "DL_PORTRAIT_WIDTH_MM",
    "DEFAULT_LOGO_PATH",
    "EnvelopeKind",
    "EnvelopeOrientation",
    "STORAGE_ROOT",
    "c6_page_size_mm",
    "envelope_page_size_mm",
]
