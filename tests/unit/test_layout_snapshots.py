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

import unittest
from dataclasses import replace
from pathlib import Path

from fpdf import FPDF

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render.layout import compute_layout
from ethernity.render.pdf_render import (
    _apply_main_qr_grid_overrides,
    _uses_uniform_main_qr_capacity,
)
from ethernity.render.spec import document_spec
from ethernity.render.template_style import load_template_style
from ethernity.render.types import RenderInputs

_EXPECTED_LAYOUT_SNAPSHOT: dict[str, tuple[int, int, int, int, float, float]] = {
    "archive.main": (23, 13, 6, 9, 4.2, 4.2),
    "archive.recovery": (23, 13, 6, 9, 4.2, 4.2),
    "archive.shard": (10, 14, 9, 9, 4.2, 4.2),
    "archive.signing_key_shard": (10, 14, 9, 9, 4.2, 4.2),
    "forge.main": (24, 14, 6, 9, 4.2, 4.2),
    "forge.recovery": (25, 40, 6, 9, 5.8, 5.8),
    "forge.shard": (10, 13, 9, 9, 4.8, 4.8),
    "forge.signing_key_shard": (11, 12, 9, 9, 4.2, 4.2),
    "ledger.main": (10, 14, 9, 9, 4.2, 4.2),
    "ledger.recovery": (23, 13, 6, 9, 4.2, 4.2),
    "ledger.shard": (10, 14, 9, 9, 4.2, 4.2),
    "ledger.signing_key_shard": (10, 14, 9, 9, 4.2, 4.2),
    "maritime.main": (10, 14, 9, 9, 4.2, 4.2),
    "maritime.recovery": (11, 15, 9, 9, 4.2, 4.2),
    "maritime.shard": (10, 14, 9, 9, 4.2, 4.2),
    "maritime.signing_key_shard": (10, 14, 9, 9, 4.2, 4.2),
    "sentinel.main": (24, 14, 6, 9, 4.2, 4.2),
    "sentinel.recovery": (31, 40, 6, 9, 5.8, 5.8),
    "sentinel.shard": (10, 10, 9, 9, 4.8, 4.8),
    "sentinel.signing_key_shard": (17, 11, 9, 9, 4.2, 4.2),
}


class TestLayoutSnapshots(unittest.TestCase):
    def test_a4_layout_snapshot_matrix(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        for design in (
            "archive",
            "forge",
            "ledger",
            "maritime",
            "sentinel",
        ):
            for doc_type in ("main", "recovery", "shard", "signing_key_shard"):
                template = (
                    Path(__file__).resolve().parents[2]
                    / "src"
                    / "ethernity"
                    / "templates"
                    / design
                    / f"{doc_type}_document.html.j2"
                )
                key = f"{design}.{doc_type}"
                with self.subTest(key=key):
                    context = {
                        "doc_id": frame.doc_id.hex(),
                        "paper_size": "A4",
                        "created_timestamp_utc": "2026-01-01 00:00 UTC",
                        "shard_index": 1,
                        "shard_total": 3,
                        "shard_threshold": 2,
                    }
                    inputs = RenderInputs(
                        frames=[frame],
                        template_path=template,
                        output_path="out.pdf",
                        context=context,
                        doc_type=doc_type,
                        render_qr=True,
                        render_fallback=True,
                        fallback_payload=b"payload",
                        key_lines=["Passphrase:", "one two three four five six"],
                    )
                    spec = document_spec(doc_type, "A4", context)
                    style = load_template_style(template)
                    spec = replace(
                        spec,
                        header=replace(
                            spec.header,
                            meta_row_gap_mm=float(style.header.meta_row_gap_mm),
                            stack_gap_mm=float(style.header.stack_gap_mm),
                            divider_thickness_mm=float(style.header.divider_thickness_mm),
                        ),
                    )
                    divider_gap_extra_mm = float(style.content_offset.divider_gap_extra_mm)
                    if divider_gap_extra_mm and doc_type in style.content_offset.doc_types:
                        spec = replace(
                            spec,
                            header=replace(
                                spec.header,
                                divider_gap_mm=float(spec.header.divider_gap_mm)
                                + divider_gap_extra_mm,
                            ),
                        )
                    spec = _apply_main_qr_grid_overrides(
                        spec=spec,
                        doc_type=doc_type,
                        capabilities=style.capabilities,
                    )

                    pdf = FPDF(unit="mm", format="A4")
                    include_instructions = doc_type != "kit"
                    include_keys = doc_type != "recovery"
                    layout, _ = compute_layout(
                        inputs,
                        spec,
                        pdf,
                        key_lines=inputs.key_lines or [],
                        include_keys=include_keys,
                        include_instructions=include_instructions,
                    )

                    keys_first_page_only = bool(spec.keys.first_page_only)
                    instructions_first_page_only = bool(spec.instructions.first_page_only)
                    if _uses_uniform_main_qr_capacity(
                        doc_type=doc_type,
                        capabilities=style.capabilities,
                    ):
                        instructions_first_page_only = False

                    layout_rest = None
                    if instructions_first_page_only or keys_first_page_only:
                        layout_rest, _ = compute_layout(
                            inputs,
                            spec,
                            pdf,
                            key_lines=inputs.key_lines or [],
                            include_keys=not keys_first_page_only,
                            include_instructions=(
                                include_instructions and not instructions_first_page_only
                            ),
                        )

                    first_lines = layout.fallback_lines_per_page
                    rest_lines = (
                        layout_rest.fallback_lines_per_page
                        if layout_rest is not None
                        else layout.fallback_lines_per_page
                    )
                    first_per = layout.per_page
                    rest_per = layout_rest.per_page if layout_rest is not None else layout.per_page
                    first_line_height = round(layout.line_height, 1)
                    rest_line_height = (
                        round(layout_rest.line_height, 1)
                        if layout_rest is not None
                        else round(layout.line_height, 1)
                    )

                    self.assertEqual(
                        (
                            first_lines,
                            rest_lines,
                            first_per,
                            rest_per,
                            first_line_height,
                            rest_line_height,
                        ),
                        _EXPECTED_LAYOUT_SNAPSHOT[key],
                    )


if __name__ == "__main__":
    unittest.main()
