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
class RenderLineage:
    """Render-time lineage metadata for root, extension, compacted, mint, and kit artifacts."""

    kind: Literal[
        "root_backup",
        "extension",
        "compaction_checkpoint",
        "minted_shard_set",
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
    lineage: RenderLineage
    design_name: str = "sentinel"
    qr_config: QrConfig | None = None
    qr_payloads: Sequence[bytes | str] | None = None
    fallback_sections: Sequence[FallbackSection] | None = None
    render_qr: bool = True
    render_fallback: bool = True
    key_lines: Sequence[str] | None = None
    recovery_meta: RecoveryMeta | None = None
    render_jobs: int | Literal["auto"] | None = None
    layout_debug_json_path: str | Path | None = None
    page_size: PaperSize | None = None

    def __post_init__(self) -> None:
        if self.lineage is None:
            raise ValueError("render lineage is required")
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
class RenderFallbackProof:
    """Structured proof that fallback section data was consumed by page assembly."""

    section_frame_digests: tuple[str, ...]
    section_titles: tuple[str, ...]
    expected_section_count: int
    emitted_block_count: int
    emitted_line_count: int
    consumed_section_count: int
    fully_consumed: bool
    emitted_fallback_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderArtifactProof:
    """Structured proof of what a render operation was asked to emit."""

    output_path: str
    doc_type: str
    frame_digests: tuple[str, ...]
    encoded_payload_count: int
    physical_qr_count: int
    page_count: int = 0
    fallback_proof: RenderFallbackProof | None = None
    qr_payload_digests: tuple[str, ...] = ()
    physical_qr_payload_indexes: tuple[int, ...] = ()
    physical_qr_payload_digests: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderRectProof:
    """A measured rectangle in millimeters for render-layout proofs."""

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
class RenderComponentLayoutProof:
    """Structured proof for one measured component placement."""

    component_id: str
    rect: RenderRectProof
    used_rect: RenderRectProof | None = None
    overflow: bool = False
    component_type: str | None = None
    policy: str | None = None
    line_count: int | None = None
    overflow_line_count: int | None = None
    font_size_pt: float | None = None


@dataclass(frozen=True)
class RenderSeparationConstraintProof:
    """Serializable result of one direct-layout separation check."""

    constraint_id: str
    first_region_id: str
    second_region_id: str
    minimum_clearance_mm: float
    measured_clearance_mm: float
    checked_pair_count: int
    satisfied: bool


@dataclass(frozen=True)
class RenderPageLayoutProof:
    """Structured proof for one measured PDF page."""

    page_number: int
    rect: RenderRectProof
    component_ids: tuple[str, ...]
    overflow_component_ids: tuple[str, ...]
    out_of_bounds_component_ids: tuple[str, ...]
    components: tuple[RenderComponentLayoutProof, ...]
    separation_constraints: tuple[RenderSeparationConstraintProof, ...] = ()

    @property
    def overflow(self) -> bool:
        return bool(self.overflow_component_ids or self.out_of_bounds_component_ids)


@dataclass(frozen=True)
class RenderLayoutProof:
    """Structured proof of measured page geometry for a render operation."""

    backend: str
    page_count: int
    pages: tuple[RenderPageLayoutProof, ...]

    @property
    def overflow(self) -> bool:
        return any(page.overflow for page in self.pages)


@dataclass(frozen=True)
class RenderResult:
    """Structured render result used by callers that must validate emitted content."""

    fallback_proof: RenderFallbackProof | None = None
    artifact_proof: RenderArtifactProof | None = None
    layout_proof: RenderLayoutProof | None = None
