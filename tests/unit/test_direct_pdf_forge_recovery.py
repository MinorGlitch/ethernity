import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    FpdfSurface,
    build_forge_recovery_direct_plan,
    forge_recovery as forge_recovery_module,
    packaged_direct_pdf_assets,
    render_forge_recovery_direct_pdf,
)
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.proofs import (
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_render_layout_proof,
)
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


def _frame(frame_type: FrameType, *, data: bytes, index: int = 0, total: int = 1) -> Frame:
    return Frame(
        version=VERSION,
        frame_type=frame_type,
        doc_id=b"\x77" * DOC_ID_LEN,
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
            "doc_id": "77" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
        },
        doc_type=DOC_TYPE_RECOVERY,
        design_name="forge",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=False,
        render_fallback=True,
        key_lines=("recovery-key-line",),
        recovery_meta=build_recovery_meta(
            passphrase="alpha bravo charlie delta echo foxtrot golf hotel",
            quorum_threshold=2,
            quorum_shares=3,
            signing_pub=b"\x12" * 32,
        ),
        fallback_sections=(
            FallbackSection(label="AUTH FRAME", frame=auth_frame),
            FallbackSection(label="MAIN FRAME", frame=main_frame),
        ),
    )


class TestDirectPdfForgeRecovery(unittest.TestCase):
    def test_build_plan_consumes_real_render_inputs_and_fallback_proof(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "recovery.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_recovery_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 2)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertNotIn(
                "forge-recovery-p1-fallback-panel",
                plan.page_plans[0].proof.component_ids,
            )
            self.assertIn(
                "forge-recovery-p1-fallback-line-box-1",
                plan.page_plans[0].proof.component_ids,
            )
            validate_render_artifact_proof(
                artifact_label="direct Forge recovery document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Forge recovery document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=plan.fallback_proof,
            )
            self.assertIn("AUTH FRAME", plan.fallback_proof.section_titles)

    def test_render_writes_valid_pdf_with_extractable_fallback_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery.pdf"
            inputs = _inputs(output_path)

            result = render_forge_recovery_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Forge recovery document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_render_layout_proof(
                artifact_label="direct Forge recovery document",
                layout_proof=result.layout_proof,
                expected_page_count=len(reader.pages),
            )
            validate_fallback_render_proof(
                artifact_label="direct Forge recovery document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=result.fallback_proof,
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Forge recovery document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )

    def test_build_plan_paginates_large_fallback_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery.pdf"
            inputs = _inputs(output_path, main_data=b"x" * 1000)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_recovery_direct_plan(surface, inputs)
            result = render_forge_recovery_direct_pdf(inputs)
            reader = validate_pdf_has_pages(output_path)

            self.assertGreater(len(plan.page_plans), 1)
            self.assertEqual(plan.artifact_proof.page_count, len(plan.page_plans))
            self.assertTrue(plan.fallback_proof.fully_consumed)
            self.assertEqual(max(map(len, plan.fallback_proof.emitted_fallback_lines)), 44)
            fallback_text_components = [
                item.proof
                for page in plan.page_plans
                for item in page.plans
                if "fallback-line-text" in item.component_id
            ]
            self.assertTrue(fallback_text_components)
            self.assertTrue(all(not component.overflow for component in fallback_text_components))
            self.assertGreaterEqual(
                min(component.font_size_pt or 0.0 for component in fallback_text_components),
                7.0,
            )
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
            validate_render_layout_proof(
                artifact_label="large direct Forge recovery document",
                layout_proof=result.layout_proof,
                expected_page_count=len(reader.pages),
            )
            validate_fallback_text_in_pdf(
                artifact_label="large direct Forge recovery document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )

    def test_custom_paginator_resets_display_numbers_per_page_and_section(self) -> None:
        entries = (
            forge_recovery_module._FallbackTitleEntry(section_index=0, title="AUTH FRAME"),
            *(
                forge_recovery_module._FallbackLineEntry(
                    section_index=0,
                    line_number=index,
                    text="yyyy",
                )
                for index in range(1, 71)
            ),
            forge_recovery_module._FallbackTitleEntry(section_index=1, title="MAIN FRAME"),
            *(
                forge_recovery_module._FallbackLineEntry(
                    section_index=1,
                    line_number=index,
                    text="yyyy",
                )
                for index in range(1, 8)
            ),
        )

        pages = forge_recovery_module._paginate_fallback_entries(
            entries,
            first_page_single_section=False,
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
