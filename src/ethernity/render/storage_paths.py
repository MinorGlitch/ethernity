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

from pathlib import Path
from typing import Literal

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

STORAGE_ROOT = _PACKAGE_ROOT / "storage"
ENVELOPE_C6_TEMPLATE_PATH = STORAGE_ROOT / "envelope_c6.html.j2"
ENVELOPE_C5_TEMPLATE_PATH = STORAGE_ROOT / "envelope_c5.html.j2"
ENVELOPE_C4_TEMPLATE_PATH = STORAGE_ROOT / "envelope_c4.html.j2"
ENVELOPE_DL_TEMPLATE_PATH = STORAGE_ROOT / "envelope_dl.html.j2"
DEFAULT_LOGO_PATH = STORAGE_ROOT / "logo.png"

C6_PORTRAIT_WIDTH_MM = 114.0
C6_PORTRAIT_HEIGHT_MM = 162.0
C5_PORTRAIT_WIDTH_MM = 162.0
C5_PORTRAIT_HEIGHT_MM = 229.0
C4_PORTRAIT_WIDTH_MM = 229.0
C4_PORTRAIT_HEIGHT_MM = 324.0
DL_PORTRAIT_WIDTH_MM = 110.0
DL_PORTRAIT_HEIGHT_MM = 220.0

EnvelopeKind = Literal["c6", "c5", "c4", "dl"]
EnvelopeOrientation = Literal["portrait", "landscape"]

_ENVELOPE_PORTRAIT_SIZES_MM: dict[EnvelopeKind, tuple[float, float]] = {
    "c6": (C6_PORTRAIT_WIDTH_MM, C6_PORTRAIT_HEIGHT_MM),
    "c5": (C5_PORTRAIT_WIDTH_MM, C5_PORTRAIT_HEIGHT_MM),
    "c4": (C4_PORTRAIT_WIDTH_MM, C4_PORTRAIT_HEIGHT_MM),
    "dl": (DL_PORTRAIT_WIDTH_MM, DL_PORTRAIT_HEIGHT_MM),
}

_ENVELOPE_TEMPLATE_PATHS: dict[EnvelopeKind, Path] = {
    "c6": ENVELOPE_C6_TEMPLATE_PATH,
    "c5": ENVELOPE_C5_TEMPLATE_PATH,
    "c4": ENVELOPE_C4_TEMPLATE_PATH,
    "dl": ENVELOPE_DL_TEMPLATE_PATH,
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


def envelope_template_path(kind: EnvelopeKind) -> Path:
    return _ENVELOPE_TEMPLATE_PATHS[kind]


__all__ = [
    "C4_PORTRAIT_HEIGHT_MM",
    "C4_PORTRAIT_WIDTH_MM",
    "C5_PORTRAIT_HEIGHT_MM",
    "C5_PORTRAIT_WIDTH_MM",
    "C6_PORTRAIT_HEIGHT_MM",
    "C6_PORTRAIT_WIDTH_MM",
    "DL_PORTRAIT_HEIGHT_MM",
    "DL_PORTRAIT_WIDTH_MM",
    "DEFAULT_LOGO_PATH",
    "ENVELOPE_C4_TEMPLATE_PATH",
    "ENVELOPE_C5_TEMPLATE_PATH",
    "ENVELOPE_C6_TEMPLATE_PATH",
    "ENVELOPE_DL_TEMPLATE_PATH",
    "EnvelopeKind",
    "EnvelopeOrientation",
    "STORAGE_ROOT",
    "c6_page_size_mm",
    "envelope_page_size_mm",
    "envelope_template_path",
]
