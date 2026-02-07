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
from dataclasses import replace
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
    document_spec,
)
from ethernity.render.template_style import load_template_style


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
    def test_main_first_page_capacity_remains_3x4_across_styles(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x11" * DOC_ID_LEN,
                index=i,
                total=24,
                data=f"payload-{i}".encode("utf-8"),
            )
            for i in range(24)
        ]
        context = {
            "doc_id": frames[0].doc_id.hex(),
            "paper_size": "A4",
            "created_timestamp_utc": "2026-01-01 00:00 UTC",
        }
        pdf = FPDF(unit="mm", format="A4")

        for design in ("ledger", "dossier", "maritime", "midnight"):
            with self.subTest(design=design):
                template_path = (
                    Path(__file__).resolve().parents[2]
                    / "src"
                    / "ethernity"
                    / "templates"
                    / design
                    / "main_document.html.j2"
                )
                inputs = RenderInputs(
                    frames=frames,
                    template_path=template_path,
                    output_path="out.pdf",
                    context=context,
                    doc_type="main",
                    render_fallback=False,
                )
                spec = document_spec("main", "A4", context)
                style = load_template_style(template_path)
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
                if divider_gap_extra_mm and "main" in style.content_offset.doc_types:
                    spec = replace(
                        spec,
                        header=replace(
                            spec.header,
                            divider_gap_mm=float(spec.header.divider_gap_mm) + divider_gap_extra_mm,
                        ),
                    )

                layout, _ = compute_layout(
                    inputs,
                    spec,
                    pdf,
                    key_lines=[],
                    include_keys=True,
                    include_instructions=True,
                )
                self.assertEqual(layout.cols, 3)
                self.assertEqual(layout.rows, 4)
                self.assertEqual(layout.per_page, 12)

    def test_recovery_text_layout_smoke_across_styles(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x66" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        context = {
            "doc_id": frame.doc_id.hex(),
            "paper_size": "A4",
            "created_timestamp_utc": "2026-01-01 00:00 UTC",
        }
        key_lines = [
            "Passphrase:",
            "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
            "Recover with 3 of 5 shard documents.",
            "Signing public key (hex):",
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        ]
        pdf = FPDF(unit="mm", format="A4")

        for design in ("ledger", "dossier", "maritime", "midnight"):
            with self.subTest(design=design):
                template_path = (
                    Path(__file__).resolve().parents[2]
                    / "src"
                    / "ethernity"
                    / "templates"
                    / design
                    / "recovery_document.html.j2"
                )
                inputs = RenderInputs(
                    frames=[frame],
                    template_path=template_path,
                    output_path="out.pdf",
                    context=context,
                    doc_type="recovery",
                    render_qr=False,
                    render_fallback=True,
                    key_lines=key_lines,
                    fallback_payload=b"recovery payload",
                )
                spec = document_spec("recovery", "A4", context)
                style = load_template_style(template_path)
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
                if divider_gap_extra_mm and "recovery" in style.content_offset.doc_types:
                    spec = replace(
                        spec,
                        header=replace(
                            spec.header,
                            divider_gap_mm=float(spec.header.divider_gap_mm) + divider_gap_extra_mm,
                        ),
                    )

                layout, fallback_lines = compute_layout(
                    inputs,
                    spec,
                    pdf,
                    key_lines=key_lines,
                    include_keys=False,
                    include_instructions=True,
                )
                self.assertEqual(layout.cols, 0)
                self.assertEqual(layout.rows, 0)
                self.assertEqual(layout.per_page, 0)
                self.assertGreater(layout.fallback_lines_per_page, 0)
                self.assertGreaterEqual(layout.total_pages, 1)
                self.assertGreater(len(fallback_lines), 0)

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
