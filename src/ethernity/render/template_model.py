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
            "doc": {
                "title": self.doc.title,
                "subtitle": self.doc.subtitle,
            },
            "instructions": {
                "label": self.instructions.label,
                "lines": list(self.instructions.lines),
                "scan_hint": self.instructions.scan_hint,
            },
            "fallback": {"width_mm": self.fallback_width_mm},
            "pages": [self._page_to_dict(page) for page in self.pages],
        }
        if self.recovery is not None:
            payload["recovery"] = {
                "passphrase": self.recovery.passphrase,
                "passphrase_lines": list(self.recovery.passphrase_lines),
                "quorum_value": self.recovery.quorum_value,
                "signing_pub_lines": list(self.recovery.signing_pub_lines),
            }
        return payload

    def _page_to_dict(self, page: PageModel) -> dict[str, object]:
        return {
            "page_num": page.page_num,
            "page_label": page.page_label,
            "divider_y_mm": page.divider_y_mm,
            "instructions_y_mm": page.instructions_y_mm,
            "show_instructions": page.show_instructions,
            "instructions_full_page": page.instructions_full_page,
            "qr_items": [
                {"index": slot.index, "data_uri": slot.data_uri} for slot in page.qr_items
            ],
            "qr_grid": None
            if page.qr_grid is None
            else {
                "size_mm": page.qr_grid.size_mm,
                "gap_x_mm": page.qr_grid.gap_x_mm,
                "gap_y_mm": page.qr_grid.gap_y_mm,
                "cols": page.qr_grid.cols,
                "rows": page.qr_grid.rows,
                "count": page.qr_grid.count,
                "x_mm": page.qr_grid.x_mm,
                "y_mm": page.qr_grid.y_mm,
            },
            "qr_outline": None
            if page.qr_outline is None
            else {
                "x_mm": page.qr_outline.x_mm,
                "y_mm": page.qr_outline.y_mm,
                "width_mm": page.qr_outline.width_mm,
                "height_mm": page.qr_outline.height_mm,
            },
            "sequence": None
            if page.sequence is None
            else {
                "lines": [
                    {"x1": line.x1, "y1": line.y1, "x2": line.x2, "y2": line.y2}
                    for line in page.sequence.lines
                ],
                "labels": [
                    {"x": label.x, "y": label.y, "text": label.text}
                    for label in page.sequence.labels
                ],
            },
            "fallback_blocks": [
                {
                    "title": block.title,
                    "lines": list(block.lines),
                    "line_offset": block.line_offset,
                    "y_mm": block.y_mm,
                    "height_mm": block.height_mm,
                }
                for block in page.fallback_blocks
            ],
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
