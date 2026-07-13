import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import ethernity.render.direct_pdf.sentinel.recovery as sentinel_recovery_module
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.page_geometry import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.sentinel.common import build_sentinel_page_layout
from ethernity.render.direct_pdf.sentinel.recovery import (
    build_sentinel_recovery_direct_plan,
    render_sentinel_recovery_direct_pdf,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.proofs import (
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
)
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


def _frame(frame_type: FrameType, *, data: bytes, index: int = 0, total: int = 1) -> Frame:
    return Frame(
        version=VERSION,
        frame_type=frame_type,
        doc_id=b"\x66" * DOC_ID_LEN,
        index=index,
        total=total,
        data=data,
    )


def _inputs(output_path: Path, *, main_data: bytes = b"payload") -> RenderInputs:
    auth_frame = _frame(FrameType.AUTH, data=b"auth-payload")
    main_frame = _frame(FrameType.MAIN_DOCUMENT, data=main_data)
    return RenderInputs(
        frames=(auth_frame, main_frame),
        output_path=output_path,
        context={
            "paper_size": "A4",
            "doc_id": "66" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
        },
        doc_type=DOC_TYPE_RECOVERY,
        design_name="sentinel",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=False,
        render_fallback=True,
        recovery_meta=build_recovery_meta(
            passphrase="alpha bravo charlie delta echo foxtrot",
            quorum_threshold=2,
            quorum_shares=3,
            signing_pub=b"\x31" * 32,
        ),
        fallback_sections=(
            FallbackSection(label="AUTH FRAME", frame=auth_frame),
            FallbackSection(label="MAIN FRAME", frame=main_frame),
        ),
    )


class TestDirectPdfSentinelRecovery(unittest.TestCase):
    def test_build_plan_uses_sentinel_shell_and_fallback_table(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "recovery.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_recovery_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 1)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertIn("sentinel-recovery-p1-top-strip", plan.page_plans[0].proof.component_ids)
            self.assertIn(
                "sentinel-recovery-p1-session-panel",
                plan.page_plans[0].proof.component_ids,
            )
            self.assertIn(
                "sentinel-recovery-p1-fallback-table",
                plan.page_plans[0].proof.component_ids,
            )
            self.assertIn(
                "sentinel-recovery-p1-metadata-box-0",
                plan.page_plans[0].proof.component_ids,
            )
            validate_render_artifact_proof(
                artifact_label="direct Sentinel recovery document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Sentinel recovery document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=plan.fallback_proof,
            )

    def test_render_writes_valid_pdf_with_extractable_fallback_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery.pdf"
            inputs = _inputs(output_path)

            result = render_sentinel_recovery_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Sentinel recovery document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Sentinel recovery document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=result.fallback_proof,
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Sentinel recovery document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )

    def test_build_plan_paginates_large_fallback_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "recovery.pdf", main_data=b"x" * 2200)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_recovery_direct_plan(surface, inputs)

            self.assertGreater(len(plan.page_plans), 1)
            self.assertEqual(plan.artifact_proof.page_count, len(plan.page_plans))
            self.assertTrue(plan.fallback_proof.fully_consumed)
            for page in plan.page_plans:
                labels = [
                    placement.text
                    for item in page.plans
                    if "fallback-line-number" in item.component_id
                    for placement in getattr(item, "lines", ())
                ]
                if labels:
                    self.assertEqual(labels[0], "01.")
                    self.assertTrue(all(len(label.removesuffix(".")) <= 4 for label in labels))

    def test_custom_paginator_resets_display_numbers_per_page_and_section(self) -> None:
        entries = (
            sentinel_recovery_module._FallbackTitleEntry(section_index=0, title="AUTH FRAME"),
            *(
                sentinel_recovery_module._FallbackLineEntry(
                    section_index=0,
                    line_number=index,
                    text="yyyy",
                )
                for index in range(1, 71)
            ),
            sentinel_recovery_module._FallbackTitleEntry(section_index=1, title="MAIN FRAME"),
            *(
                sentinel_recovery_module._FallbackLineEntry(
                    section_index=1,
                    line_number=index,
                    text="yyyy",
                )
                for index in range(1, 8)
            ),
        )

        pages = sentinel_recovery_module._paginate_fallback_entries(
            entries,
            page_layout=build_sentinel_page_layout(_inputs(Path("unused.pdf"))),
        )

        self.assertGreater(len(pages), 1)
        for page in pages:
            current_block: list[int] = []
            for page_entry in page.entries:
                if page_entry.display_line_number is None:
                    if current_block:
                        self.assertEqual(current_block, list(range(1, len(current_block) + 1)))
                        current_block = []
                    continue
                current_block.append(page_entry.display_line_number)
                self.assertLessEqual(len(str(page_entry.display_line_number)), 4)
            if current_block:
                self.assertEqual(current_block, list(range(1, len(current_block) + 1)))


if __name__ == "__main__":
    unittest.main()
