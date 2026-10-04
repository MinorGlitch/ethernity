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

"""Shared dataclasses for render inputs, layouts, and page-building state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from ethernity.encoding.framing import Frame
from ethernity.page_sizes import (
    DEFAULT_PAPER_SIZE_NAME,
    PaperSize,
    normalize_paper_size_name,
    resolve_paper_size,
)
from ethernity.qr.codec import QrConfig
from ethernity.render.recovery_meta import RecoveryMeta


@dataclass(frozen=True)
class DocumentOrigin:
    """Render-time origin metadata for root, extension, rebuilt, replacement, and kit documents."""

    kind: Literal[
        "root_backup",
        "extension",
        "rebuilt_backup",
        "replacement_recovery",
        "recovery_kit",
    ]
    extension_index: int | None = None


@dataclass(frozen=True)
class FallbackSection:
    """A labeled frame included in fallback text sections."""

    label: str | None
    frame: Frame


@dataclass(frozen=True)
class RenderInputs:
    """Inputs consumed by the render pipeline for a single output document."""

    frames: Sequence[Frame]
    output_path: str | Path
    context: dict[str, object]
    doc_type: str
    origin: DocumentOrigin
    design_name: str = "sentinel"
    qr_config: QrConfig | None = None
    qr_payloads: Sequence[bytes | str] | None = None
    fallback_sections: Sequence[FallbackSection] | None = None
    render_qr: bool = True
    render_fallback: bool = True
    key_lines: Sequence[str] | None = None
    recovery_meta: RecoveryMeta | None = None
    layout_debug_json_path: str | Path | None = None
    page_size: PaperSize | None = None

    def __post_init__(self) -> None:
        if self.origin is None:
            raise ValueError("render origin is required")
        if self.render_fallback and not self.fallback_sections:
            raise ValueError("fallback_sections are required when render_fallback is enabled")
        if self.page_size is not None and not isinstance(self.page_size, PaperSize):
            raise TypeError("page_size must be a PaperSize")
        configured_name = self.context.get("paper_size")
        resolved_page_size = self.page_size
        if resolved_page_size is None:
            raw_name = (
                configured_name
                if isinstance(configured_name, str) and configured_name.strip()
                else DEFAULT_PAPER_SIZE_NAME
            )
            resolved_page_size = resolve_paper_size(raw_name)
            object.__setattr__(self, "page_size", resolved_page_size)
        if (
            isinstance(configured_name, str)
            and configured_name.strip()
            and normalize_paper_size_name(configured_name) != resolved_page_size.name
        ):
            raise ValueError(
                "typed page_size conflicts with context paper_size: "
                f"{resolved_page_size.name!r} != {configured_name!r}"
            )
        normalized_context = dict(self.context)
        normalized_context["paper_size"] = resolved_page_size.name
        object.__setattr__(self, "context", normalized_context)


@dataclass(frozen=True)
class FallbackSummary:
    """Counts and exact fallback text consumed during page assembly."""

    section_frame_digests: tuple[str, ...]
    section_titles: tuple[str, ...]
    expected_section_count: int
    emitted_block_count: int
    emitted_line_count: int
    consumed_section_count: int
    fully_consumed: bool
    emitted_fallback_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderedDocumentSummary:
    """Expected frames, QR placements, and fallback text for one rendered document."""

    output_path: str
    doc_type: str
    frame_digests: tuple[str, ...]
    encoded_payload_count: int
    physical_qr_count: int
    page_count: int = 0
    fallback_summary: FallbackSummary | None = None
    qr_payload_digests: tuple[str, ...] = ()
    physical_qr_payload_indexes: tuple[int, ...] = ()
    physical_qr_payload_digests: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderRect:
    """A measured rectangle in millimeters."""

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float

    @property
    def right_mm(self) -> float:
        return self.x_mm + self.width_mm

    @property
    def bottom_mm(self) -> float:
        return self.y_mm + self.height_mm


@dataclass(frozen=True)
class RenderTextMetadata:
    """Meaning of a printed recovery value, independent of its label and design."""

    role: Literal["recovery_passphrase", "recovery_quorum", "recovery_signing_public_key"]
    print_mode: str | None = None
    continuation_index: int = 0
    value_prefix: str = ""

    def __post_init__(self) -> None:
        if self.role not in {
            "recovery_passphrase",
            "recovery_quorum",
            "recovery_signing_public_key",
        }:
            raise ValueError("unsupported printed recovery value role")
        if self.continuation_index < 0:
            raise ValueError("recovery continuation index must be non-negative")


@dataclass(frozen=True)
class RenderTextLine:
    """Exact text and baseline expected from one planned paint operation."""

    text: str
    x_mm: float
    baseline_y_mm: float
    color: tuple[int, int, int]


@dataclass(frozen=True)
class ComponentLayout:
    """Measured placement, text, and overflow status for one component."""

    component_id: str
    rect: RenderRect
    used_rect: RenderRect | None = None
    overflow: bool = False
    component_type: str | None = None
    policy: str | None = None
    line_count: int | None = None
    overflow_line_count: int | None = None
    font_size_pt: float | None = None
    text_lines: tuple[RenderTextLine, ...] = ()
    text_metadata: RenderTextMetadata | None = None


@dataclass(frozen=True)
class SeparationCheck:
    """Serializable result of one direct-layout separation check."""

    constraint_id: str
    first_region_id: str
    second_region_id: str
    minimum_clearance_mm: float
    measured_clearance_mm: float
    checked_pair_count: int
    satisfied: bool


@dataclass(frozen=True)
class PageLayout:
    """Measured components and spacing checks for one PDF page."""

    page_number: int
    rect: RenderRect
    component_ids: tuple[str, ...]
    overflow_component_ids: tuple[str, ...]
    out_of_bounds_component_ids: tuple[str, ...]
    components: tuple[ComponentLayout, ...]
    separation_constraints: tuple[SeparationCheck, ...] = ()

    @property
    def overflow(self) -> bool:
        return bool(self.overflow_component_ids or self.out_of_bounds_component_ids)


@dataclass(frozen=True)
class LayoutReport:
    """Measured page geometry for one render operation."""

    backend: str
    page_count: int
    pages: tuple[PageLayout, ...]

    @property
    def overflow(self) -> bool:
        return any(page.overflow for page in self.pages)


@dataclass(frozen=True)
class RenderResult:
    """Document summaries and measured layouts used to validate the emitted PDF."""

    fallback_summary: FallbackSummary | None = None
    document_summary: RenderedDocumentSummary | None = None
    layout_report: LayoutReport | None = None
