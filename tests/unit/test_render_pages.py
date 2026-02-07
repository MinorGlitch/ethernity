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

import unittest
from pathlib import Path

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render.pages import build_pages
from ethernity.render.spec import (
    DocumentSpec,
    FallbackSpec,
    HeaderSpec,
    PageSpec,
    QrGridSpec,
    QrSequenceSpec,
    TextBlockSpec,
)
from ethernity.render.types import Layout, RenderInputs


def _layout(
    *,
    cols: int,
    rows: int,
    per_page: int,
    fallback_lines_per_page: int,
) -> Layout:
    return Layout(
        page_w=100.0,
        page_h=100.0,
        margin=0.0,
        header_height=0.0,
        instructions_y=0.0,
        content_start_y=0.0,
        usable_w=100.0,
        usable_h=100.0,
        usable_h_grid=100.0,
        qr_size=10.0,
        gap=0.0,
        cols=cols,
        rows=rows,
        per_page=per_page,
        gap_y_override=None,
        fallback_width=100.0,
        line_length=10,
        line_height=1.0,
        fallback_lines_per_page=fallback_lines_per_page,
        fallback_font="Courier",
        fallback_size=8.0,
        text_gap=0.0,
        min_lines=1,
        key_lines=(),
        total_pages=1,
    )


def _spec() -> DocumentSpec:
    return DocumentSpec(
        page=PageSpec(
            size="custom",
            width_mm=100.0,
            height_mm=100.0,
            margin_mm=0.0,
            header_height_mm=0.0,
        ),
        header=HeaderSpec(
            divider_enabled=True,
            divider_thickness_mm=0.5,
            divider_gap_mm=0.0,
        ),
        instructions=TextBlockSpec(first_page_only=True),
        keys=TextBlockSpec(),
        qr_grid=QrGridSpec(outline_padding_mm=0.0),
        qr_sequence=QrSequenceSpec(enabled=False),
        fallback=FallbackSpec(),
    )


class TestBuildPages(unittest.TestCase):
    def test_qr_page_starts_account_for_layout_rest(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x44" * DOC_ID_LEN,
                index=i,
                total=5,
                data=f"payload-{i}".encode("utf-8"),
            )
            for i in range(5)
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "ledger"
            / "main_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="main",
            render_qr=True,
            render_fallback=False,
        )

        layout = _layout(cols=2, rows=1, per_page=2, fallback_lines_per_page=1)
        layout_rest = _layout(cols=3, rows=1, per_page=3, fallback_lines_per_page=1)
        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=layout,
            layout_rest=layout_rest,
            fallback_lines=[],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        qr_indices = [item.index for page in pages for item in page.qr_items]
        self.assertEqual(qr_indices, [1, 2, 3, 4, 5])

    def test_fallback_page_slices_account_for_layout_rest_with_qr(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x55" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "ledger"
            / "main_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="main",
            render_qr=True,
            render_fallback=True,
        )

        fallback_lines = [f"L{idx}" for idx in range(10)]
        layout = _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=3)
        layout_rest = _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=4)
        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=layout,
            layout_rest=layout_rest,
            fallback_lines=fallback_lines,
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        rendered = []
        for page in pages:
            blocks = page.fallback_blocks
            if not blocks:
                continue
            self.assertEqual(len(blocks), 1)
            rendered.extend(blocks[0].lines)

        self.assertEqual(rendered, fallback_lines)


if __name__ == "__main__":
    unittest.main()
