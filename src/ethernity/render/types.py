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

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from ..encoding.framing import Frame
from ..qr.codec import QrConfig

if TYPE_CHECKING:
    from .spec import DocumentSpec


@dataclass(frozen=True)
class FallbackSection:
    label: str | None
    frame: Frame


@dataclass(frozen=True)
class RenderInputs:
    frames: Sequence[Frame]
    template_path: str | Path
    output_path: str | Path
    context: dict[str, object]
    doc_type: str | None = None
    qr_config: QrConfig | None = None
    qr_payloads: Sequence[bytes | str] | None = None
    fallback_payload: bytes | None = None
    fallback_sections: Sequence[FallbackSection] | None = None
    render_qr: bool = True
    render_fallback: bool = True
    key_lines: Sequence[str] | None = None


@dataclass(frozen=True)
class Layout:
    page_w: float
    page_h: float
    margin: float
    header_height: float
    instructions_y: float
    content_start_y: float
    usable_w: float
    usable_h: float
    usable_h_grid: float
    qr_size: float
    gap: float
    cols: int
    rows: int
    per_page: int
    gap_y_override: float | None
    fallback_width: float
    line_length: int
    line_height: float
    fallback_lines_per_page: int
    fallback_font: str
    fallback_size: float
    text_gap: float
    min_lines: int
    key_lines: tuple[str, ...]
    total_pages: int


@dataclass(frozen=True)
class PageBuildContext:
    """Context for building document pages, grouping related parameters."""

    inputs: RenderInputs
    spec: "DocumentSpec"
    layout: Layout
    layout_rest: Layout | None
    fallback_lines: Sequence[str]
    qr_payloads: Sequence[bytes | str]
    fallback_sections_data: Sequence[dict[str, object]] | None
    fallback_state: dict[str, int] | None
    key_lines: Sequence[str]
    keys_first_page_only: bool
