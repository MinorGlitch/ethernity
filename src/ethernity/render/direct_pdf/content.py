"""Normalize document content before any template measures it."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ethernity.render.direct_pdf.document_inputs import non_negative_int
from ethernity.render.types import RenderInputs


@dataclass(frozen=True)
class InventoryRow:
    identifier: str
    detail: str
    status: str = "Generated"


def inventory_rows(inputs: RenderInputs) -> tuple[InventoryRow, ...]:
    raw = inputs.context.get("inventory_rows")
    rows: list[InventoryRow] = []
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValueError("inventory rows must be objects")
            identifier = str(item.get("component_id") or "").strip()
            if not identifier:
                raise ValueError("inventory row requires a component_id")
            rows.append(
                InventoryRow(
                    identifier,
                    str(item.get("detail") or ""),
                    str(item.get("status") or "Generated"),
                )
            )
        if rows:
            return tuple(rows)
    page_count = non_negative_int(inputs.context.get("kit_qr_page_count"), default=0)
    chunk_count = non_negative_int(inputs.context.get("kit_qr_chunk_count"), default=0)
    if not page_count:
        return (InventoryRow("KIT-PAGE-01", "No QR chunks"),)
    chunks_per_page = max(1, math.ceil(chunk_count / page_count))
    return tuple(
        InventoryRow(
            f"KIT-PAGE-{index + 1:02d}",
            f"KIT {index * chunks_per_page + 1:02d} to "
            f"KIT {min(chunk_count, (index + 1) * chunks_per_page):02d}"
            if chunk_count
            else f"KIT PAGE {index + 1:02d}",
        )
        for index in range(page_count)
    )
