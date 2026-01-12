#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from .doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SIGNING_KEY_SHARD,
    DOC_TYPES,
)
from .utils import int_value as _int_value

Color = str | tuple[int, int, int] | tuple[int, int, int, int]


@dataclass(frozen=True)
class PageSpec:
    size: str = "A4"
    margin_mm: float = 14.0
    header_height_mm: float = 16.0
    instructions_gap_mm: float = 4.0
    keys_gap_mm: float = 3.0
    width_mm: float | None = None
    height_mm: float | None = None


@dataclass(frozen=True)
class HeaderSpec:
    title: str = ""
    subtitle: str = ""
    doc_id_label: str = "Document ID:"
    doc_id: str | None = None
    page_label: str | None = None
    title_size: float = 20.0
    subtitle_size: float = 10.0
    meta_size: float = 8.0
    layout: str = "split"
    split_left_ratio: float = 0.7
    divider_enabled: bool = True
    divider_gap_mm: float = 2.5
    divider_thickness_mm: float = 0.5


@dataclass(frozen=True)
class TextBlockSpec:
    label: str | None = None
    lines: tuple[str, ...] = ()
    font_family: str = "Helvetica"
    font_size: float = 9.0
    line_height_mm: float | None = None
    label_layout: str = "column"
    label_size: float = 7.0
    label_column_mm: float = 24.0
    label_gap_mm: float = 2.0
    indent_mm: float = 0.0
    first_page_only: bool = False
    label_line_height_mm: float | None = None


@dataclass(frozen=True)
class FallbackSpec:
    font_family: str = "Courier"
    font_size: float = 10.0
    line_height_mm: float = 4.2
    padding_mm: float = 2.0
    label_size: float = 10.0
    label_line_height_mm: float | None = None
    group_size: int = 4
    line_length: int = 0
    line_count: int = 10


@dataclass(frozen=True)
class QrGridSpec:
    qr_size_mm: float = 58.0
    gap_mm: float = 3.0
    max_cols: int | None = 3
    max_rows: int | None = 4
    text_gap_mm: float = 2.5
    outline_padding_mm: float = 1.0


@dataclass(frozen=True)
class QrSequenceSpec:
    enabled: bool = False
    font_size: float = 12.0
    line_thickness_mm: float = 0.7
    label_offset_mm: float = 2.0


@dataclass(frozen=True)
class DocumentSpec:
    page: PageSpec
    header: HeaderSpec
    instructions: TextBlockSpec
    keys: TextBlockSpec
    qr_grid: QrGridSpec
    qr_sequence: QrSequenceSpec
    fallback: FallbackSpec

    def with_header(self, *, doc_id: str, page_label: str) -> "DocumentSpec":
        return replace(self, header=replace(self.header, doc_id=doc_id, page_label=page_label))

    def with_key_lines(self, lines: Sequence[str]) -> "DocumentSpec":
        return replace(self, keys=replace(self.keys, lines=tuple(lines)))


def document_spec(
    doc_type: str,
    paper_size: str,
    context: dict[str, object],
) -> DocumentSpec:
    normalized = doc_type.strip().lower()
    if normalized not in DOC_TYPES:
        normalized = DOC_TYPE_MAIN

    header = HeaderSpec()
    instructions = TextBlockSpec(
        label="Instructions",
        font_family="Helvetica",
        font_size=9.0,
        line_height_mm=4.5,
        label_layout="column",
        label_size=7.0,
        label_column_mm=24.0,
        label_gap_mm=2.0,
        first_page_only=True,
    )
    keys = TextBlockSpec(
        label="Keys",
        font_family="Courier",
        font_size=8.0,
        line_height_mm=4.0,
        label_layout="column",
        label_size=7.0,
        label_column_mm=24.0,
        label_gap_mm=2.0,
    )
    fallback = FallbackSpec()
    page = PageSpec(size=paper_size)
    qr_grid = QrGridSpec()
    qr_sequence = QrSequenceSpec()

    shard_index = _int_value(context.get("shard_index"), default=1)
    shard_total = _int_value(context.get("shard_total"), default=1)

    if normalized == DOC_TYPE_MAIN:
        header = replace(header, title="Main Document", subtitle="Mode: passphrase")
        instructions = replace(
            instructions,
            lines=(
                "Scan all QR codes in any order.",
                "Use the Recovery Document for text fallback if needed.",
            ),
        )
    elif normalized == DOC_TYPE_RECOVERY:
        header = replace(header, title="Recovery Document", subtitle="Keys + Text Fallback")
        instructions = replace(
            instructions,
            lines=(
                "This document contains recovery keys and full text fallback.",
                "Keep it separate from the QR document.",
                "Fallback includes AUTH + MAIN sections; keep the labels when transcribing.",
            ),
        )
        keys = replace(keys, first_page_only=True)
    elif normalized == DOC_TYPE_KIT:
        header = replace(header, title="Recovery Kit", subtitle="Offline HTML bundle")
        instructions = replace(
            instructions,
            lines=(
                "Scan QR codes in order and concatenate the payloads.",
                "Write the output to recovery_kit.bundle.html.",
            ),
        )
        if paper_size.strip().lower() == "letter":
            qr_grid = replace(qr_grid, qr_size_mm=52.0, max_cols=3, max_rows=4)
        else:
            qr_grid = replace(qr_grid, qr_size_mm=58.0, max_cols=3, max_rows=4)
        qr_grid = replace(qr_grid, gap_mm=2.0, text_gap_mm=3.0)
        qr_sequence = QrSequenceSpec(enabled=False)
    elif normalized == DOC_TYPE_SIGNING_KEY_SHARD:
        header = replace(
            header,
            title="Signing Key Shard",
            subtitle=f"Signing key shard {shard_index} of {shard_total}",
        )
        instructions = replace(
            instructions,
            lines=(
                "This document is one shard of the signing key.",
                "Keep signing-key shards separate and secure.",
            ),
        )
    else:
        header = replace(
            header,
            title="Shard Document",
            subtitle=f"Shard {shard_index} of {shard_total}",
        )
        instructions = replace(
            instructions,
            lines=(
                "This document is one shard of the passphrase.",
                "Keep shards separate and secure.",
            ),
        )

    return DocumentSpec(
        page=page,
        header=header,
        instructions=instructions,
        keys=keys,
        qr_grid=qr_grid,
        qr_sequence=qr_sequence,
        fallback=fallback,
    )
