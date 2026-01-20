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

from fpdf import FPDF

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render import RenderInputs
from ethernity.render.layout import compute_layout
from ethernity.render.spec import (
    DocumentSpec,
    FallbackSpec,
    HeaderSpec,
    PageSpec,
    QrGridSpec,
    QrSequenceSpec,
    TextBlockSpec,
)


def _build_spec(*, line_count: int, line_height: float) -> DocumentSpec:
    page = PageSpec(
        size="custom",
        width_mm=100,
        height_mm=100,
        margin_mm=0,
        header_height_mm=0,
        instructions_gap_mm=0,
        keys_gap_mm=0,
    )
    header = HeaderSpec(
        title="",
        subtitle="",
        doc_id_label="",
        doc_id=None,
        page_label=None,
        divider_enabled=False,
    )
    instructions = TextBlockSpec()
    keys = TextBlockSpec()
    qr_grid = QrGridSpec(
        qr_size_mm=30,
        gap_mm=10,
        max_cols=1,
        max_rows=3,
        text_gap_mm=2,
    )
    qr_sequence = QrSequenceSpec()
    fallback = FallbackSpec(
        group_size=4,
        line_length=80,
        line_count=line_count,
        line_height_mm=line_height,
        font_family="Courier",
        font_size=8,
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


class TestPdfLayout(unittest.TestCase):
    def test_gap_override_when_max_rows_exceeds_fit(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x22" * DOC_ID_LEN,
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
            context={"doc_id": frames[0].doc_id.hex()},
            doc_type="main",
            render_fallback=False,
        )
        spec = _build_spec(line_count=6, line_height=3.5)
        pdf = FPDF(unit="mm", format=(100, 100))
        layout, _ = compute_layout(inputs, spec, pdf, key_lines=[])

        self.assertEqual(layout.rows, 3)
        self.assertIsNotNone(layout.gap_y_override)

    def test_fallback_reduces_rows(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x33" * DOC_ID_LEN,
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
            context={"doc_id": frames[0].doc_id.hex()},
            doc_type="main",
            render_fallback=True,
        )
        spec = _build_spec(line_count=4, line_height=10)
        pdf = FPDF(unit="mm", format=(100, 100))
        layout, _ = compute_layout(inputs, spec, pdf, key_lines=[])

        self.assertEqual(layout.rows, 1)
        self.assertGreater(layout.fallback_lines_per_page, 0)


if __name__ == "__main__":
    unittest.main()
