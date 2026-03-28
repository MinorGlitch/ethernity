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

import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render.fallback import FallbackConsumerState, FallbackSectionData
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


def _write_template(
    root: Path,
    folder: str,
    *,
    capabilities: dict[str, object] | None = None,
) -> Path:
    template_dir = root / folder
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "style.json").write_text(
        json.dumps(
            {
                "name": "custom",
                "header": {
                    "meta_row_gap_mm": 1.2,
                    "stack_gap_mm": 1.0,
                    "divider_thickness_mm": 0.5,
                },
                "content_offset": {
                    "divider_gap_extra_mm": 0.0,
                    "doc_types": [],
                },
                "capabilities": capabilities or {},
            }
        ),
        encoding="utf-8",
    )
    template_path = template_dir / "recovery_document.html.j2"
    template_path.write_text("", encoding="utf-8")
    return template_path


class TestBuildPages(unittest.TestCase):
    def test_kit_doc_type_is_case_insensitive_for_instruction_visibility(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x12" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "forge"
            / "kit_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="KIT",
            render_qr=True,
            render_fallback=False,
        )

        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=_layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=1),
            layout_rest=None,
            fallback_lines=[],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        self.assertFalse(pages[0].show_instructions)
        self.assertTrue(any(page.instructions_full_page for page in pages))

    def test_kit_index_doc_type_does_not_add_synthetic_instruction_page(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x34" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "forge"
            / "kit_index_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="kit_index",
            render_qr=True,
            render_fallback=False,
        )

        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=_layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=1),
            layout_rest=None,
            fallback_lines=[],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        self.assertFalse(any(page.instructions_full_page for page in pages))

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
            / "resources"
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

    def test_sentinel_main_first_page_uses_extra_primary_slot(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x66" * DOC_ID_LEN,
                index=i,
                total=16,
                data=f"payload-{i}".encode("utf-8"),
            )
            for i in range(16)
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "sentinel"
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

        layout = _layout(cols=3, rows=2, per_page=6, fallback_lines_per_page=1)
        layout_rest = _layout(cols=3, rows=3, per_page=9, fallback_lines_per_page=1)
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

        self.assertEqual(len(pages), 2)
        self.assertEqual([item.index for item in pages[0].qr_items], [1, 2, 3, 4, 5, 6, 7])
        self.assertIsNotNone(pages[0].qr_grid)
        assert pages[0].qr_grid is not None
        self.assertEqual(pages[0].qr_grid.rows, 2)
        self.assertEqual(pages[0].qr_grid.count, 6)
        self.assertEqual(
            [item.index for item in pages[1].qr_items],
            [8, 9, 10, 11, 12, 13, 14, 15, 16],
        )

    def test_sentinel_extra_first_page_slot_without_layout_rest_renders_all_frames(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x67" * DOC_ID_LEN,
                index=i,
                total=20,
                data=f"payload-{i}".encode("utf-8"),
            )
            for i in range(20)
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "sentinel"
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

        layout = _layout(cols=3, rows=2, per_page=6, fallback_lines_per_page=1)
        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=layout,
            layout_rest=None,
            fallback_lines=[],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        self.assertEqual(len(pages), 4)
        qr_indices = [item.index for page in pages for item in page.qr_items]
        self.assertEqual(qr_indices, list(range(1, 21)))

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
            / "resources"
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

    def test_fallback_y_uses_rows_rendered_on_page(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x77" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
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

        layout = _layout(cols=1, rows=3, per_page=3, fallback_lines_per_page=3)
        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=layout,
            layout_rest=None,
            fallback_lines=["L1", "L2"],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        self.assertEqual(len(pages), 1)
        page = pages[0]
        self.assertIsNotNone(page.qr_grid)
        assert page.qr_grid is not None
        self.assertEqual(page.qr_grid.rows, 1)
        self.assertTrue(page.fallback_blocks)
        self.assertEqual(page.fallback_blocks[0].y_mm, 10.0)

    def test_text_only_fallback_pages_do_not_reserve_empty_qr_rows(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x88" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
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

        layout = _layout(cols=1, rows=2, per_page=1, fallback_lines_per_page=1)
        layout_rest = _layout(cols=1, rows=2, per_page=1, fallback_lines_per_page=2)
        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=layout,
            layout_rest=layout_rest,
            fallback_lines=["L1", "L2", "L3", "L4", "L5"],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        self.assertGreaterEqual(len(pages), 2)
        page_two = pages[1]
        self.assertFalse(page_two.qr_items)
        self.assertIsNotNone(page_two.qr_grid)
        assert page_two.qr_grid is not None
        self.assertEqual(page_two.qr_grid.rows, 0)
        self.assertTrue(page_two.fallback_blocks)
        self.assertEqual(page_two.fallback_blocks[0].y_mm, 0.0)

    def test_shard_continuation_pages_repeat_primary_qr(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x99" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "forge"
            / "shard_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="shard",
            render_qr=True,
            render_fallback=True,
        )

        layout = _layout(cols=1, rows=2, per_page=1, fallback_lines_per_page=1)
        layout_rest = _layout(cols=1, rows=2, per_page=1, fallback_lines_per_page=2)
        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=layout,
            layout_rest=layout_rest,
            fallback_lines=["L1", "L2", "L3"],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        self.assertGreaterEqual(len(pages), 2)
        page_two = pages[1]
        self.assertTrue(page_two.qr_items)
        self.assertEqual([item.index for item in page_two.qr_items], [1])
        self.assertIsNotNone(page_two.qr_grid)
        assert page_two.qr_grid is not None
        self.assertEqual(page_two.qr_grid.rows, 1)
        self.assertTrue(page_two.fallback_blocks)
        self.assertEqual(page_two.fallback_blocks[0].y_mm, 10.0)

    def test_signing_key_shard_continuation_pages_repeat_primary_qr(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xab" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "forge"
            / "signing_key_shard_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="signing_key_shard",
            render_qr=True,
            render_fallback=True,
        )

        layout = _layout(cols=1, rows=2, per_page=1, fallback_lines_per_page=1)
        layout_rest = _layout(cols=1, rows=2, per_page=1, fallback_lines_per_page=2)
        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=layout,
            layout_rest=layout_rest,
            fallback_lines=["L1", "L2", "L3"],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        self.assertGreaterEqual(len(pages), 2)
        page_two = pages[1]
        self.assertTrue(page_two.qr_items)
        self.assertEqual([item.index for item in page_two.qr_items], [1])
        self.assertIsNotNone(page_two.qr_grid)
        assert page_two.qr_grid is not None
        self.assertEqual(page_two.qr_grid.rows, 1)
        self.assertTrue(page_two.fallback_blocks)
        self.assertEqual(page_two.fallback_blocks[0].y_mm, 10.0)

    def test_non_forge_shard_continuation_pages_do_not_repeat_primary_qr(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xbc" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "ledger"
            / "shard_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="shard",
            render_qr=True,
            render_fallback=True,
        )

        layout = _layout(cols=1, rows=2, per_page=1, fallback_lines_per_page=1)
        layout_rest = _layout(cols=1, rows=2, per_page=1, fallback_lines_per_page=2)
        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=layout,
            layout_rest=layout_rest,
            fallback_lines=["L1", "L2", "L3"],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        self.assertGreaterEqual(len(pages), 2)
        page_two = pages[1]
        self.assertFalse(page_two.qr_items)
        self.assertIsNotNone(page_two.qr_grid)
        assert page_two.qr_grid is not None
        self.assertEqual(page_two.qr_grid.rows, 0)
        self.assertTrue(page_two.fallback_blocks)
        self.assertEqual(page_two.fallback_blocks[0].y_mm, 0.0)

    def test_forge_recovery_starts_main_section_on_second_page(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xcd" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "forge"
            / "recovery_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
        )

        sections = [
            FallbackSectionData(title="AUTH FRAME", tokens=("a", "b", "c", "d"), group_size=1),
            FallbackSectionData(title="MAIN FRAME", tokens=("e", "f", "g", "h"), group_size=1),
        ]
        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=_layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=10),
            layout_rest=_layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=10),
            fallback_lines=["L1"],
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=sections,
            fallback_state=FallbackConsumerState(),
        )

        self.assertGreaterEqual(len(pages), 2)
        first_page_titles = [block.title for block in pages[0].fallback_blocks if block.title]
        second_page_titles = [block.title for block in pages[1].fallback_blocks if block.title]
        self.assertEqual(first_page_titles, ["AUTH FRAME"])
        self.assertEqual(second_page_titles, ["MAIN FRAME"])

    def test_forge_recovery_raises_when_section_fallback_cannot_fit_any_rows(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xde" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "forge"
            / "recovery_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
        )
        sections = [
            FallbackSectionData(title="AUTH FRAME", tokens=("a", "b", "c", "d"), group_size=1),
        ]
        layout = replace(
            _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=10),
            content_start_y=100.0,
            line_height=2.0,
        )

        with self.assertRaisesRegex(
            ValueError,
            "fallback capacity exhausted before consuming section data",
        ):
            build_pages(
                inputs=inputs,
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )

    def test_forge_recovery_raises_when_section_fallback_cannot_make_progress(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xed" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "forge"
            / "recovery_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="recovery",
            render_qr=False,
            render_fallback=True,
        )
        sections = [
            FallbackSectionData(title="AUTH FRAME", tokens=("a", "b"), group_size=1),
        ]
        layout = replace(
            _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=10),
            content_start_y=99.0,
            line_height=1.0,
        )

        with self.assertRaisesRegex(
            ValueError,
            "fallback capacity exhausted before consuming section data",
        ):
            build_pages(
                inputs=inputs,
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )

    def test_non_section_fallback_raises_when_first_page_capacity_is_zero(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xef" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
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
            render_qr=False,
            render_fallback=True,
        )
        layout = _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=0)

        with self.assertRaisesRegex(
            ValueError,
            "fallback capacity exhausted before consuming fallback lines",
        ):
            build_pages(
                inputs=inputs,
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=None,
                fallback_state=None,
            )

    def test_non_section_fallback_raises_when_continuation_capacity_is_zero(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xf0" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
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
            render_qr=False,
            render_fallback=True,
        )
        layout = _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=1)
        layout_rest = _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=0)

        with self.assertRaisesRegex(
            ValueError,
            "fallback continuation capacity exhausted before consuming fallback lines",
        ):
            build_pages(
                inputs=inputs,
                spec=_spec(),
                layout=layout,
                layout_rest=layout_rest,
                fallback_lines=["L1", "L2"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=None,
                fallback_state=None,
            )

    def test_forge_shard_non_section_fallback_respects_effective_page_capacity(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xf1" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        template_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "ethernity"
            / "resources"
            / "templates"
            / "forge"
            / "shard_document.html.j2"
        )
        inputs = RenderInputs(
            frames=frames,
            template_path=template_path,
            output_path="out.pdf",
            context={},
            doc_type="shard",
            render_qr=False,
            render_fallback=True,
        )
        layout = _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=10)
        fallback_lines = [f"L{i}" for i in range(1, 11)]

        pages = build_pages(
            inputs=inputs,
            spec=_spec(),
            layout=layout,
            layout_rest=layout,
            fallback_lines=fallback_lines,
            qr_image_builder=lambda idx: f"qr:{idx}",
            fallback_sections_data=None,
            fallback_state=None,
        )

        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0].fallback_line_capacity, 9)
        self.assertEqual(pages[1].fallback_line_capacity, 13)
        self.assertEqual(list(pages[0].fallback_blocks[0].lines), fallback_lines[:9])
        self.assertEqual(list(pages[1].fallback_blocks[0].lines), fallback_lines[9:])

    def test_main_pages_repeat_instructions_when_capability_is_enabled(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xf2" * DOC_ID_LEN,
                index=i,
                total=3,
                data=f"payload-{i}".encode("utf-8"),
            )
            for i in range(3)
        ]
        with TemporaryDirectory() as temp_dir:
            template_path = _write_template(
                Path(temp_dir),
                "maritime",
                capabilities={"repeat_main_instructions_on_all_pages": True},
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
            layout = _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=1)
            layout_rest = _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=1)

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

        self.assertTrue(all(page.show_instructions for page in pages))

    def test_recovery_capability_bonus_applies_only_when_explicit(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xaa" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        sections = [
            FallbackSectionData(
                title="MAIN FRAME",
                tokens=(
                    "aaaaaaaaaa",
                    "bbbbbbbbbb",
                    "cccccccccc",
                    "dddddddddd",
                    "eeeeeeeeee",
                ),
                group_size=1,
            ),
        ]
        layout = replace(
            _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=10),
            content_start_y=98.0,
            line_height=1.0,
            line_length=10,
        )

        with TemporaryDirectory() as temp_dir:
            template_root = Path(temp_dir)
            bonus_template = _write_template(
                template_root,
                "bonus",
                capabilities={
                    "recovery_line_groups_bonus": 5,
                    "recovery_first_page_bonus_lines": 13,
                    "recovery_first_page_bonus_lines_per_extra_section": 2,
                    "recovery_continuation_bonus_lines": 16,
                },
            )
            baseline_template = _write_template(template_root, "baseline")

            bonus_pages = build_pages(
                inputs=RenderInputs(
                    frames=frames,
                    template_path=bonus_template,
                    output_path="out.pdf",
                    context={},
                    doc_type="recovery",
                    render_qr=False,
                    render_fallback=True,
                ),
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )
            baseline_pages = build_pages(
                inputs=RenderInputs(
                    frames=frames,
                    template_path=baseline_template,
                    output_path="out.pdf",
                    context={},
                    doc_type="recovery",
                    render_qr=False,
                    render_fallback=True,
                ),
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )

        self.assertEqual(len(bonus_pages), 1)
        self.assertEqual(len(baseline_pages), 3)
        self.assertEqual(len(bonus_pages[0].fallback_blocks[0].lines), 5)
        self.assertEqual(len(baseline_pages[0].fallback_blocks[0].lines), 1)

    def test_recovery_continuation_bonus_pages_use_extra_rows(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xbb" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        sections = [
            FallbackSectionData(
                title="MAIN FRAME",
                tokens=tuple(f"{idx:010d}" for idx in range(1, 21)),
                group_size=1,
            ),
        ]
        layout = replace(
            _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=10),
            content_start_y=97.0,
            line_height=1.0,
            line_length=10,
        )

        with TemporaryDirectory() as temp_dir:
            template_root = Path(temp_dir)
            bonus_template = _write_template(
                template_root,
                "bonus",
                capabilities={
                    "recovery_line_groups_bonus": 5,
                    "recovery_first_page_bonus_lines": 13,
                    "recovery_first_page_bonus_lines_per_extra_section": 2,
                    "recovery_continuation_bonus_lines": 16,
                },
            )
            baseline_template = _write_template(template_root, "baseline")

            bonus_pages = build_pages(
                inputs=RenderInputs(
                    frames=frames,
                    template_path=bonus_template,
                    output_path="out.pdf",
                    context={},
                    doc_type="recovery",
                    render_qr=False,
                    render_fallback=True,
                ),
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )
            baseline_pages = build_pages(
                inputs=RenderInputs(
                    frames=frames,
                    template_path=baseline_template,
                    output_path="out.pdf",
                    context={},
                    doc_type="recovery",
                    render_qr=False,
                    render_fallback=True,
                ),
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )

        self.assertGreaterEqual(len(bonus_pages), 2)
        self.assertGreaterEqual(len(baseline_pages), 2)
        bonus_continuation_lines = len(bonus_pages[1].fallback_blocks[0].lines)
        baseline_continuation_lines = len(baseline_pages[1].fallback_blocks[0].lines)
        self.assertGreater(bonus_continuation_lines, baseline_continuation_lines)
        self.assertEqual(bonus_continuation_lines, 5)
        self.assertEqual(baseline_continuation_lines, 3)

    def test_recovery_group_wrapping_bonus_reduces_page_count(
        self,
    ) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xcc" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        sections = [
            FallbackSectionData(
                title="MAIN FRAME",
                tokens=tuple(f"{idx:02d}" for idx in range(1, 81)),
                group_size=2,
            ),
        ]
        layout = replace(
            _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=10),
            content_start_y=97.0,
            line_height=1.0,
            line_length=10,
        )

        with TemporaryDirectory() as temp_dir:
            template_root = Path(temp_dir)
            bonus_template = _write_template(
                template_root,
                "bonus",
                capabilities={
                    "recovery_line_groups_bonus": 5,
                    "recovery_first_page_bonus_lines": 13,
                    "recovery_first_page_bonus_lines_per_extra_section": 2,
                    "recovery_continuation_bonus_lines": 16,
                },
            )
            baseline_template = _write_template(template_root, "baseline")

            bonus_pages = build_pages(
                inputs=RenderInputs(
                    frames=frames,
                    template_path=bonus_template,
                    output_path="out.pdf",
                    context={},
                    doc_type="recovery",
                    render_qr=False,
                    render_fallback=True,
                ),
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )
            baseline_pages = build_pages(
                inputs=RenderInputs(
                    frames=frames,
                    template_path=baseline_template,
                    output_path="out.pdf",
                    context={},
                    doc_type="recovery",
                    render_qr=False,
                    render_fallback=True,
                ),
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )

        self.assertEqual(len(bonus_pages), 1)
        self.assertGreaterEqual(len(baseline_pages), 2)
        bonus_first_groups = len(bonus_pages[0].fallback_blocks[0].lines[0].split())
        baseline_first_groups = len(baseline_pages[0].fallback_blocks[0].lines[0].split())
        self.assertGreater(bonus_first_groups, baseline_first_groups)

    def test_recovery_behavior_does_not_depend_on_template_directory_name(self) -> None:
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\xdd" * DOC_ID_LEN,
                index=0,
                total=1,
                data=b"payload",
            )
        ]
        sections = [
            FallbackSectionData(
                title="MAIN FRAME",
                tokens=tuple(f"{idx:010d}" for idx in range(1, 21)),
                group_size=1,
            ),
        ]
        layout = replace(
            _layout(cols=1, rows=1, per_page=1, fallback_lines_per_page=10),
            content_start_y=97.0,
            line_height=1.0,
            line_length=10,
        )

        capabilities = {
            "recovery_line_groups_bonus": 5,
            "recovery_first_page_bonus_lines": 13,
            "recovery_first_page_bonus_lines_per_extra_section": 2,
            "recovery_continuation_bonus_lines": 16,
        }
        with TemporaryDirectory() as temp_dir:
            template_root = Path(temp_dir)
            alpha_template = _write_template(
                template_root,
                "renamed-alpha",
                capabilities=capabilities,
            )
            bravo_template = _write_template(
                template_root,
                "renamed-bravo",
                capabilities=capabilities,
            )

            alpha_pages = build_pages(
                inputs=RenderInputs(
                    frames=frames,
                    template_path=alpha_template,
                    output_path="out.pdf",
                    context={},
                    doc_type="recovery",
                    render_qr=False,
                    render_fallback=True,
                ),
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )
            bravo_pages = build_pages(
                inputs=RenderInputs(
                    frames=frames,
                    template_path=bravo_template,
                    output_path="out.pdf",
                    context={},
                    doc_type="recovery",
                    render_qr=False,
                    render_fallback=True,
                ),
                spec=_spec(),
                layout=layout,
                layout_rest=layout,
                fallback_lines=["L1"],
                qr_image_builder=lambda idx: f"qr:{idx}",
                fallback_sections_data=sections,
                fallback_state=FallbackConsumerState(),
            )

        self.assertEqual(len(alpha_pages), len(bravo_pages))
        self.assertEqual(
            alpha_pages[0].fallback_blocks[0].lines,
            bravo_pages[0].fallback_blocks[0].lines,
        )


if __name__ == "__main__":
    unittest.main()
