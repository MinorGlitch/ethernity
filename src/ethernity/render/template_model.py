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


@dataclass(frozen=True)
class DocModel:
    title: str
    subtitle: str


@dataclass(frozen=True)
class InstructionsModel:
    label: str
    lines: tuple[str, ...]
    scan_hint: str | None


@dataclass(frozen=True)
class QrItemModel:
    index: int
    data_uri: str


@dataclass(frozen=True)
class QrGridModel:
    size_mm: float
    gap_x_mm: float
    gap_y_mm: float
    cols: int
    rows: int
    count: int
    x_mm: float | None = None
    y_mm: float | None = None


@dataclass(frozen=True)
class QrOutlineModel:
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class QrSequenceLineModel:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class QrSequenceLabelModel:
    x: float
    y: float
    text: str


@dataclass(frozen=True)
class QrSequenceModel:
    lines: tuple[QrSequenceLineModel, ...]
    labels: tuple[QrSequenceLabelModel, ...]


@dataclass(frozen=True)
class FallbackBlockModel:
    title: str | None
    lines: tuple[str, ...]
    line_offset: int
    y_mm: float | None = None
    height_mm: float | None = None


@dataclass(frozen=True)
class PageModel:
    page_num: int
    page_label: str
    show_instructions: bool
    instructions_full_page: bool
    qr_items: tuple[QrItemModel, ...]
    qr_grid: QrGridModel | None
    fallback_blocks: tuple[FallbackBlockModel, ...]
    divider_y_mm: float | None = None
    instructions_y_mm: float | None = None
    qr_outline: QrOutlineModel | None = None
    sequence: QrSequenceModel | None = None
    fallback_line_capacity: int = 0
    fallback_row_height_mm: float | None = None


@dataclass(frozen=True)
class RecoveryModel:
    passphrase: str | None
    passphrase_lines: tuple[str, ...]
    quorum_value: str | None
    signing_pub_lines: tuple[str, ...]


@dataclass(frozen=True)
class TemplateContext:
    page_size_css: str
    page_width_mm: float
    page_height_mm: float
    margin_mm: float
    usable_width_mm: float
    doc_id: str
    created_timestamp_utc: str
    doc: DocModel
    instructions: InstructionsModel
    pages: tuple[PageModel, ...]
    fallback_width_mm: float
    recovery: RecoveryModel | None = None

    def to_template_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "page_size_css": self.page_size_css,
            "page_width_mm": self.page_width_mm,
            "page_height_mm": self.page_height_mm,
            "margin_mm": self.margin_mm,
            "usable_width_mm": self.usable_width_mm,
            "doc_id": self.doc_id,
            "created_timestamp_utc": self.created_timestamp_utc,
            "doc": self._serialize_doc(self.doc),
            "instructions": self._serialize_instructions(self.instructions),
            "fallback": {"width_mm": self.fallback_width_mm},
            "pages": [self._serialize_page(page) for page in self.pages],
        }
        if self.recovery is not None:
            payload["recovery"] = self._serialize_recovery(self.recovery)
        return payload

    @staticmethod
    def _serialize_doc(doc: DocModel) -> dict[str, object]:
        return {
            "title": doc.title,
            "subtitle": doc.subtitle,
        }

    @staticmethod
    def _serialize_instructions(instructions: InstructionsModel) -> dict[str, object]:
        return {
            "label": instructions.label,
            "lines": list(instructions.lines),
            "scan_hint": instructions.scan_hint,
        }

    @staticmethod
    def _serialize_recovery(recovery: RecoveryModel) -> dict[str, object]:
        return {
            "passphrase": recovery.passphrase,
            "passphrase_lines": list(recovery.passphrase_lines),
            "quorum_value": recovery.quorum_value,
            "signing_pub_lines": list(recovery.signing_pub_lines),
        }

    @staticmethod
    def _serialize_page(page: PageModel) -> dict[str, object]:
        return {
            "page_num": page.page_num,
            "page_label": page.page_label,
            "divider_y_mm": page.divider_y_mm,
            "instructions_y_mm": page.instructions_y_mm,
            "show_instructions": page.show_instructions,
            "instructions_full_page": page.instructions_full_page,
            "qr_items": [TemplateContext._serialize_qr_item(slot) for slot in page.qr_items],
            "qr_grid": TemplateContext._serialize_qr_grid(page.qr_grid),
            "qr_outline": TemplateContext._serialize_qr_outline(page.qr_outline),
            "sequence": TemplateContext._serialize_sequence(page.sequence),
            "fallback_blocks": [
                TemplateContext._serialize_fallback_block(block) for block in page.fallback_blocks
            ],
            "fallback_line_capacity": page.fallback_line_capacity,
            "fallback_row_height_mm": page.fallback_row_height_mm,
        }

    @staticmethod
    def _serialize_qr_item(item: QrItemModel) -> dict[str, object]:
        return {"index": item.index, "data_uri": item.data_uri}

    @staticmethod
    def _serialize_qr_grid(grid: QrGridModel | None) -> dict[str, object] | None:
        if grid is None:
            return None
        return {
            "size_mm": grid.size_mm,
            "gap_x_mm": grid.gap_x_mm,
            "gap_y_mm": grid.gap_y_mm,
            "cols": grid.cols,
            "rows": grid.rows,
            "count": grid.count,
            "x_mm": grid.x_mm,
            "y_mm": grid.y_mm,
        }

    @staticmethod
    def _serialize_qr_outline(outline: QrOutlineModel | None) -> dict[str, object] | None:
        if outline is None:
            return None
        return {
            "x_mm": outline.x_mm,
            "y_mm": outline.y_mm,
            "width_mm": outline.width_mm,
            "height_mm": outline.height_mm,
        }

    @staticmethod
    def _serialize_sequence(sequence: QrSequenceModel | None) -> dict[str, object] | None:
        if sequence is None:
            return None
        return {
            "lines": [
                {"x1": line.x1, "y1": line.y1, "x2": line.x2, "y2": line.y2}
                for line in sequence.lines
            ],
            "labels": [
                {"x": label.x, "y": label.y, "text": label.text} for label in sequence.labels
            ],
        }

    @staticmethod
    def _serialize_fallback_block(block: FallbackBlockModel) -> dict[str, object]:
        return {
            "title": block.title,
            "lines": list(block.lines),
            "line_offset": block.line_offset,
            "y_mm": block.y_mm,
            "height_mm": block.height_mm,
        }


__all__ = [
    "DocModel",
    "FallbackBlockModel",
    "InstructionsModel",
    "PageModel",
    "QrOutlineModel",
    "QrSequenceLabelModel",
    "QrSequenceLineModel",
    "QrSequenceModel",
    "QrGridModel",
    "QrItemModel",
    "RecoveryModel",
    "TemplateContext",
]
