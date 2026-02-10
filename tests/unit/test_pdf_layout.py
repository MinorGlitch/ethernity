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
from ethernity.render.geometry import (
    fallback_lines_per_page,
    fallback_lines_per_page_text_only,
)
from ethernity.render.layout import compute_layout
from ethernity.render.pdf_render import _parse_recovery_key_lines, _recovery_meta_lines_extra
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
                recovery_meta = _parse_recovery_key_lines(key_lines)
                style = load_template_style(template_path)
                spec = replace(
                    spec,
                    header=replace(
                        spec.header,
                        meta_lines_extra=_recovery_meta_lines_extra(recovery_meta),
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
                divider_y = (
                    layout.margin + layout.header_height - float(spec.header.divider_thickness_mm)
                )
                self.assertGreaterEqual(divider_y, layout.margin)
                self.assertLessEqual(divider_y, layout.instructions_y)
                self.assertLess(layout.instructions_y, layout.content_start_y)
                self.assertGreater(layout.content_start_y, layout.margin)
                self.assertLess(layout.content_start_y, layout.page_h - layout.margin)

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

    def test_forge_does_not_force_max_rows_when_gap_reduction_is_possible(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x23" * DOC_ID_LEN,
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
            / "forge"
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

        self.assertEqual(layout.rows, 2)
        self.assertIsNone(layout.gap_y_override)

    def test_forge_caps_main_qr_rows_to_three(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x24" * DOC_ID_LEN,
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
            / "forge"
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
        spec = replace(spec, qr_grid=replace(spec.qr_grid, max_rows=4))
        pdf = FPDF(unit="mm", format=(300, 300))
        layout, _ = compute_layout(inputs, spec, pdf, key_lines=[])

        self.assertEqual(layout.rows, 3)

    def test_forge_main_first_page_uses_two_rows_and_rest_uses_three(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x25" * DOC_ID_LEN,
                index=i,
                total=30,
                data=f"payload-{i}".encode("utf-8"),
            )
            for i in range(30)
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "forge"
            / "main_document.html.j2"
        )
        context = {
            "doc_id": frames[0].doc_id.hex(),
            "paper_size": "A4",
            "created_timestamp_utc": "2026-01-01 00:00 UTC",
        }
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
        pdf = FPDF(unit="mm", format="A4")
        first_layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_keys=True,
            include_instructions=True,
        )
        rest_layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_keys=True,
            include_instructions=False,
        )

        self.assertEqual(first_layout.rows, 2)
        self.assertEqual(rest_layout.rows, 3)

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

    def test_forge_recovery_uses_larger_effective_line_height(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x34" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "forge"
            / "recovery_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
            fallback_payload=b"recovery payload",
        )
        spec = _build_spec(line_count=6, line_height=4.2)
        pdf = FPDF(unit="mm", format=(100, 100))
        layout, _ = compute_layout(inputs, spec, pdf, key_lines=[])

        self.assertGreaterEqual(layout.line_height, 5.8)
        self.assertEqual(layout.fallback_lines_per_page, 4)

    def test_forge_recovery_continuation_pages_use_more_fallback_capacity(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x37" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "forge"
            / "recovery_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
            fallback_payload=b"recovery payload",
        )
        spec = _build_spec(line_count=6, line_height=4.2)
        pdf = FPDF(unit="mm", format=(100, 100))
        first_layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=True,
        )
        rest_layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=False,
        )

        self.assertGreater(
            rest_layout.fallback_lines_per_page,
            first_layout.fallback_lines_per_page,
        )

    def test_sentinel_recovery_continuation_capacity_respects_template_reserve(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x7f" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "sentinel"
            / "recovery_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
            fallback_payload=b"recovery payload",
        )
        spec = _build_spec(line_count=6, line_height=4.2)
        pdf = FPDF(unit="mm", format=(100, 100))
        rest_layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=False,
        )

        raw_text_only_capacity = fallback_lines_per_page_text_only(
            rest_layout.content_start_y,
            rest_layout.page_h,
            rest_layout.margin,
            rest_layout.line_height,
        )
        self.assertEqual(
            rest_layout.fallback_lines_per_page,
            max(1, raw_text_only_capacity - 2),
        )

    def test_sentinel_recovery_lines_use_wider_grouping(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x80" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "sentinel"
            / "recovery_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex(), "paper_size": "A4"},
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
            fallback_payload=b"payload",
        )
        spec = document_spec("recovery", "A4", inputs.context)
        pdf = FPDF(unit="mm", format="A4")
        layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=True,
        )

        # 12 groups x 4 chars + 11 separators = 59 chars.
        self.assertGreaterEqual(layout.line_length, 59)

    def test_sentinel_recovery_first_page_capacity_adds_bonus_rows(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x81" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        base_context = {"doc_id": frame.doc_id.hex()}
        spec = _build_spec(line_count=6, line_height=4.2)
        pdf = FPDF(unit="mm", format=(100, 100))

        forge_inputs = RenderInputs(
            frames=[frame],
            template_path=(
                Path(__file__).resolve().parents[2]
                / "src"
                / "ethernity"
                / "templates"
                / "forge"
                / "recovery_document.html.j2"
            ),
            output_path="out.pdf",
            context=base_context,
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
            fallback_payload=b"payload",
        )
        sentinel_inputs = RenderInputs(
            frames=[frame],
            template_path=(
                Path(__file__).resolve().parents[2]
                / "src"
                / "ethernity"
                / "templates"
                / "sentinel"
                / "recovery_document.html.j2"
            ),
            output_path="out.pdf",
            context=base_context,
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
            fallback_payload=b"payload",
        )

        forge_layout, _ = compute_layout(
            forge_inputs,
            spec,
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=True,
        )
        sentinel_layout, _ = compute_layout(
            sentinel_inputs,
            spec,
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=True,
        )

        self.assertEqual(
            sentinel_layout.fallback_lines_per_page,
            forge_layout.fallback_lines_per_page + 10,
        )

    def test_sentinel_recovery_first_page_capacity_adds_more_rows_for_light_metadata(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x82" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        base_context = {"doc_id": frame.doc_id.hex()}
        spec = _build_spec(line_count=6, line_height=4.2)
        pdf = FPDF(unit="mm", format=(100, 100))

        sentinel_inputs = RenderInputs(
            frames=[frame],
            template_path=(
                Path(__file__).resolve().parents[2]
                / "src"
                / "ethernity"
                / "templates"
                / "sentinel"
                / "recovery_document.html.j2"
            ),
            output_path="out.pdf",
            context=base_context,
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
            fallback_payload=b"payload",
        )

        default_meta_layout, _ = compute_layout(
            sentinel_inputs,
            replace(spec, header=replace(spec.header, meta_lines_extra=0)),
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=True,
        )
        light_meta_layout, _ = compute_layout(
            sentinel_inputs,
            replace(spec, header=replace(spec.header, meta_lines_extra=3)),
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=True,
        )
        heavy_meta_layout, _ = compute_layout(
            sentinel_inputs,
            replace(spec, header=replace(spec.header, meta_lines_extra=8)),
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=True,
        )

        self.assertGreater(
            light_meta_layout.fallback_lines_per_page,
            default_meta_layout.fallback_lines_per_page,
        )
        self.assertGreater(
            light_meta_layout.fallback_lines_per_page,
            heavy_meta_layout.fallback_lines_per_page,
        )

    def test_sentinel_recovery_no_quorum_first_page_capacity_adds_rows(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x83" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "sentinel"
            / "recovery_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex(), "paper_size": "A4"},
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
            fallback_payload=b"payload",
        )
        spec_base = document_spec("recovery", "A4", inputs.context)
        pdf = FPDF(unit="mm", format="A4")

        key_lines_without_quorum = [
            "Passphrase:",
            "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
            "Signing public key (hex):",
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        ]
        meta_without_quorum = _parse_recovery_key_lines(key_lines_without_quorum)
        spec_without_quorum = replace(
            spec_base,
            header=replace(
                spec_base.header,
                meta_lines_extra=_recovery_meta_lines_extra(meta_without_quorum),
            ),
        )
        layout_without_quorum, _ = compute_layout(
            inputs,
            spec_without_quorum,
            pdf,
            key_lines=key_lines_without_quorum,
            include_keys=False,
            include_instructions=True,
        )

        key_lines_with_quorum = [
            *key_lines_without_quorum,
            "Recover with 2 of 3 shard documents.",
        ]
        meta_with_quorum = _parse_recovery_key_lines(key_lines_with_quorum)
        spec_with_quorum = replace(
            spec_base,
            header=replace(
                spec_base.header,
                meta_lines_extra=_recovery_meta_lines_extra(meta_with_quorum),
            ),
        )
        layout_with_quorum, _ = compute_layout(
            inputs,
            spec_with_quorum,
            pdf,
            key_lines=key_lines_with_quorum,
            include_keys=False,
            include_instructions=True,
        )

        self.assertGreater(
            layout_without_quorum.fallback_lines_per_page,
            layout_with_quorum.fallback_lines_per_page,
        )

    def test_forge_recovery_first_page_capacity_reduces_with_more_metadata_lines(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x38" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "forge"
            / "recovery_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
            fallback_payload=b"recovery payload",
        )
        spec = _build_spec(line_count=6, line_height=4.2)
        pdf = FPDF(unit="mm", format=(100, 100))

        spec_default = replace(spec, header=replace(spec.header, meta_lines_extra=3))
        layout_default, _ = compute_layout(
            inputs,
            spec_default,
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=True,
        )

        spec_heavy_meta = replace(spec, header=replace(spec.header, meta_lines_extra=11))
        layout_heavy_meta, _ = compute_layout(
            inputs,
            spec_heavy_meta,
            pdf,
            key_lines=[],
            include_keys=False,
            include_instructions=True,
        )

        self.assertLess(
            layout_heavy_meta.fallback_lines_per_page,
            layout_default.fallback_lines_per_page,
        )

    def test_forge_shard_fallback_capacity_matches_payload_zone(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x36" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "forge"
            / "shard_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="shard",
            render_qr=True,
            render_fallback=True,
            fallback_payload=b"shard payload",
        )
        spec = _build_spec(line_count=6, line_height=3.5)
        pdf = FPDF(unit="mm", format=(100, 100))
        layout, _ = compute_layout(inputs, spec, pdf, key_lines=[])

        self.assertEqual(layout.fallback_lines_per_page, 9)

    def test_sentinel_shard_first_page_capacity_adds_bonus_line(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x36" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        spec = _build_spec(line_count=6, line_height=3.5)
        pdf = FPDF(unit="mm", format=(100, 100))

        forge_template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "forge"
            / "shard_document.html.j2"
        )
        forge_inputs = RenderInputs(
            frames=[frame],
            template_path=forge_template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="shard",
            render_qr=True,
            render_fallback=True,
            fallback_payload=b"shard payload",
        )
        forge_layout, _ = compute_layout(
            forge_inputs,
            spec,
            pdf,
            key_lines=[],
            include_instructions=True,
        )

        sentinel_template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "sentinel"
            / "shard_document.html.j2"
        )
        sentinel_inputs = RenderInputs(
            frames=[frame],
            template_path=sentinel_template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="shard",
            render_qr=True,
            render_fallback=True,
            fallback_payload=b"shard payload",
        )
        sentinel_layout, _ = compute_layout(
            sentinel_inputs,
            spec,
            pdf,
            key_lines=[],
            include_instructions=True,
        )

        self.assertEqual(
            sentinel_layout.fallback_lines_per_page,
            forge_layout.fallback_lines_per_page + 1,
        )

    def test_non_forge_shard_uses_base_fallback_capacity(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x3b" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "ledger"
            / "shard_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="shard",
            render_qr=True,
            render_fallback=True,
            fallback_payload=b"shard payload",
        )
        spec = _build_spec(line_count=6, line_height=3.5)
        pdf = FPDF(unit="mm", format=(100, 100))
        layout, _ = compute_layout(inputs, spec, pdf, key_lines=[])

        expected_lines = fallback_lines_per_page(
            layout.rows,
            layout.content_start_y,
            layout.page_h,
            layout.margin,
            layout.qr_size,
            layout.gap,
            layout.line_height,
        )
        self.assertEqual(layout.line_height, 3.5)
        self.assertEqual(layout.fallback_lines_per_page, expected_lines)

    def test_forge_shard_continuation_pages_use_more_fallback_capacity(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x39" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "forge"
            / "shard_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="shard",
            render_qr=True,
            render_fallback=True,
            fallback_payload=b"shard payload",
        )
        spec = _build_spec(line_count=6, line_height=3.5)
        pdf = FPDF(unit="mm", format=(100, 100))
        first_layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_instructions=True,
        )
        rest_layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_instructions=False,
        )

        self.assertGreater(
            rest_layout.fallback_lines_per_page,
            first_layout.fallback_lines_per_page,
        )

    def test_forge_signing_key_shard_fallback_capacity_matches_payload_zone(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x35" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "forge"
            / "signing_key_shard_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="signing_key_shard",
            render_qr=True,
            render_fallback=True,
            fallback_payload=b"signing payload",
        )
        spec = _build_spec(line_count=6, line_height=3.5)
        pdf = FPDF(unit="mm", format=(100, 100))
        layout, _ = compute_layout(inputs, spec, pdf, key_lines=[])

        self.assertEqual(layout.fallback_lines_per_page, 11)

    def test_forge_signing_key_shard_continuation_pages_use_more_fallback_capacity(self) -> None:
        frame = Frame(
            version=1,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x3a" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "templates"
            / "forge"
            / "signing_key_shard_document.html.j2"
        )
        inputs = RenderInputs(
            frames=[frame],
            template_path=template_path,
            output_path="out.pdf",
            context={"doc_id": frame.doc_id.hex()},
            doc_type="signing_key_shard",
            render_qr=True,
            render_fallback=True,
            fallback_payload=b"signing payload",
        )
        spec = _build_spec(line_count=6, line_height=3.5)
        pdf = FPDF(unit="mm", format=(100, 100))
        first_layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_instructions=True,
        )
        rest_layout, _ = compute_layout(
            inputs,
            spec,
            pdf,
            key_lines=[],
            include_instructions=False,
        )

        self.assertGreater(
            rest_layout.fallback_lines_per_page,
            first_layout.fallback_lines_per_page,
        )


if __name__ == "__main__":
    unittest.main()
