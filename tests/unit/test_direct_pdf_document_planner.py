from __future__ import annotations

import unittest
from typing import cast

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf.document_planner import (
    assemble_document_plan,
    build_qr_document_plan,
    build_responsive_recovery_document_plan,
    build_single_qr_fallback_plan,
    recovery_overflow_meta,
)
from ethernity.render.direct_pdf.fallback_layout import (
    ResponsiveFallbackSpec,
    fallback_entries,
    fallback_sections,
    paginate_fallback_entries,
)
from ethernity.render.direct_pdf.page import DirectPdfPagePlan
from ethernity.render.direct_pdf.recovery_metadata import (
    RecoveryPassphraseContinuationPage,
    RecoveryPassphrasePagination,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.recovery_meta import (
    PASSPHRASE_PRINT_MODE_LITERAL,
    RecoveryMeta,
)
from ethernity.render.types import DocumentOrigin, FallbackSection, RenderInputs


def _frame(index: int = 0, total: int = 1) -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=b"\x61" * DOC_ID_LEN,
        index=index,
        total=total,
        data=f"classic-planner-{index}".encode(),
    )


def _page_plan(label: str) -> DirectPdfPagePlan:
    return cast(DirectPdfPagePlan, label)


class TestDocumentPlanner(unittest.TestCase):
    def test_empty_document_is_rejected_before_layout_construction(self) -> None:
        inputs = RenderInputs(
            frames=(_frame(),),
            output_path="empty.pdf",
            context={},
            doc_type="main",
            design_name="ledger",
            origin=DocumentOrigin(kind="root_backup"),
            render_fallback=False,
        )
        with self.assertRaisesRegex(ValueError, "at least one planned page"):
            assemble_document_plan(inputs, (), qr_payloads=(), encoded_payload_count=0)

    def test_qr_plan_owns_pagination_trailing_page_and_layout(self) -> None:
        frames = tuple(_frame(index, 3) for index in range(3))
        inputs = RenderInputs(
            frames=frames,
            output_path="classic-qr.pdf",
            context={},
            doc_type="main",
            origin=DocumentOrigin(kind="root_backup"),
            design_name="ledger",
            render_qr=True,
            render_fallback=False,
        )
        calls: list[tuple[int, int, int, int]] = []

        plan = build_qr_document_plan(
            inputs,
            capacity=2,
            first_page_capacity=1,
            page_builder=lambda page, total_pages, item_count: (
                calls.append((page.page_number, len(page.items), total_pages, item_count))
                or _page_plan(f"qr-{page.page_number}")
            ),
            trailing_page_builder=lambda page_number, total_pages: _page_plan(
                f"trailing-{page_number}-{total_pages}"
            ),
        )

        self.assertEqual(calls, [(1, 1, 3, 3), (2, 2, 3, 3)])
        self.assertEqual(plan.page_plans, ("qr-1", "qr-2", "trailing-3-3"))
        self.assertEqual(plan.document_summary.page_count, 3)
        self.assertEqual(plan.document_summary.physical_qr_payload_indexes, (0, 1, 2))

    def test_recovery_plan_orders_fallback_before_passphrase_continuation(self) -> None:
        frame = _frame()
        inputs = RenderInputs(
            frames=(frame,),
            output_path="classic-recovery.pdf",
            context={},
            doc_type="recovery",
            origin=DocumentOrigin(kind="root_backup"),
            design_name="maritime",
            render_qr=False,
            render_fallback=True,
            fallback_sections=(FallbackSection(label="MAIN FRAME", frame=frame),),
        )
        inline_meta = RecoveryMeta(
            passphrase="alpha beta",
            passphrase_lines=("alpha beta",),
        )
        pagination = RecoveryPassphrasePagination(
            inline_meta=inline_meta,
            continuation_pages=(
                RecoveryPassphraseContinuationPage(
                    page_index=1,
                    total_pages=1,
                    print_mode=PASSPHRASE_PRINT_MODE_LITERAL,
                    literal_lines=("continued",),
                ),
            ),
        )
        overflow_meta = recovery_overflow_meta(pagination)
        fallback_calls: list[tuple[int, str | None, PdfRect, int]] = []
        passphrase_calls: list[tuple[int, int]] = []
        surface = FpdfSurface(page_width_mm=210.0, page_height_mm=297.0)
        area = PdfRect(10.0, 20.0, 190.0, 180.0)
        style = TextStyle(family="Courier", size_pt=7.0)

        plan = build_responsive_recovery_document_plan(
            surface,
            inputs,
            passphrase_pagination=pagination,
            overflow_meta=overflow_meta,
            first_fallback_area=area,
            continuation_fallback_area=area,
            fallback_spec=ResponsiveFallbackSpec(
                group_size=4,
                row_height_mm=4.0,
                body_style=style,
                number_style=style,
                content_left_inset_mm=2.0,
                content_right_inset_mm=2.0,
                vertical_reserved_mm=0.0,
                number_gap_mm=1.0,
                number_minimum_width_mm=6.0,
            ),
            fallback_page_builder=lambda page, meta, page_area, total_pages: (
                fallback_calls.append((page.page_number, meta.passphrase, page_area, total_pages))
                or _page_plan(f"fallback-{page.page_number}")
            ),
            passphrase_page_builder=lambda page, page_number, total_pages: (
                passphrase_calls.append((page_number, total_pages))
                or _page_plan(f"passphrase-{page.page_index}")
            ),
        )

        self.assertEqual(fallback_calls, [(1, "alpha beta", area, 2)])
        self.assertEqual(passphrase_calls, [(2, 2)])
        self.assertEqual(plan.page_plans, ("fallback-1", "passphrase-1"))
        self.assertTrue(plan.fallback_summary and plan.fallback_summary.fully_consumed)

    def test_single_qr_fallback_plan_uses_local_page_builder_and_shared_layouts(self) -> None:
        frame = _frame()
        source_sections = (FallbackSection(label="SHARD PAYLOAD", frame=frame),)
        inputs = RenderInputs(
            frames=(frame,),
            output_path="classic-shard.pdf",
            context={},
            doc_type="shard",
            origin=DocumentOrigin(kind="root_backup"),
            design_name="ledger",
            render_qr=True,
            render_fallback=True,
            fallback_sections=source_sections,
        )
        sections = fallback_sections(source_sections, group_size=4, line_length=24)
        pages = paginate_fallback_entries(fallback_entries(sections), capacity=1_000)
        calls: list[tuple[int, int, int]] = []

        plan = build_single_qr_fallback_plan(
            inputs,
            sections=sections,
            fallback_pages=pages,
            page_entries=lambda page: tuple(item.entry for item in page.entries),
            page_builder=lambda page, qr_bytes, total_pages: (
                calls.append((page.page_number, len(qr_bytes), total_pages))
                or _page_plan(f"shard-{page.page_number}")
            ),
        )

        self.assertEqual(len(calls), 1)
        self.assertGreater(calls[0][1], 0)
        self.assertEqual(calls[0][2], 1)
        self.assertEqual(plan.document_summary.physical_qr_count, 1)
        self.assertTrue(plan.fallback_summary and plan.fallback_summary.fully_consumed)


if __name__ == "__main__":
    unittest.main()
