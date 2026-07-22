import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.forge.kit import (
    build_forge_kit_direct_plan,
    build_forge_kit_index_direct_plan,
    render_forge_kit_direct_pdf,
    render_forge_kit_index_direct_pdf,
)
from ethernity.render.direct_pdf.page_geometry import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    LETTER_HEIGHT_MM,
    LETTER_WIDTH_MM,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.doc_types import DOC_TYPE_KIT, DOC_TYPE_KIT_INDEX
from ethernity.render.proofs import (
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_text_in_pdf,
)
from ethernity.render.types import RenderInputs, RenderLineage


def _frames(count: int) -> tuple[Frame, ...]:
    return tuple(
        Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\xbb" * DOC_ID_LEN,
            index=index,
            total=count,
            data=f"kit-frame-{index}".encode("ascii"),
        )
        for index in range(count)
    )


def _kit_inputs(
    output_path: Path,
    *,
    count: int = 5,
    paper_size: str = "A4",
) -> RenderInputs:
    frames = _frames(count)
    return RenderInputs(
        frames=frames,
        output_path=output_path,
        context={
            "paper_size": paper_size,
            "doc_id": "bb" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
        },
        doc_type=DOC_TYPE_KIT,
        design_name="forge",
        lineage=RenderLineage(kind="recovery_kit"),
        qr_payloads=tuple(f"kit-chunk-{index}" for index in range(count)),
        render_qr=True,
        render_fallback=False,
    )


def _kit_index_inputs(
    output_path: Path,
    *,
    row_count: int = 3,
    paper_size: str = "A4",
) -> RenderInputs:
    return RenderInputs(
        frames=(),
        output_path=output_path,
        context={
            "paper_size": paper_size,
            "doc_id": "bb" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
            "kit_qr_page_count": 2,
            "kit_qr_chunk_count": 10,
            "inventory_rows": [
                {
                    "component_id": f"KIT-PAGE-{index + 1:02d}",
                    "detail": f"KIT {index + 1:02d}",
                    "status": "Generated",
                }
                for index in range(row_count)
            ],
        },
        doc_type=DOC_TYPE_KIT_INDEX,
        design_name="forge",
        lineage=RenderLineage(kind="root_backup"),
        qr_payloads=(),
        render_qr=False,
        render_fallback=False,
    )


class TestDirectPdfForgeKit(unittest.TestCase):
    def test_build_kit_plan_places_qr_payloads_and_instruction_page(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _kit_inputs(Path(tmp) / "kit.pdf", count=5)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_kit_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 2)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 5)
            self.assertEqual(plan.artifact_proof.physical_qr_payload_indexes, (0, 1, 2, 3, 4))
            warning_icon = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "forge-kit-p1-warning-icon"
            )
            first_card = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "forge-kit-p1-qr-card-0"
            )
            first_qr = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "forge-kit-p1-qr-image-0"
            )
            instruction_page = plan.page_plans[-1]
            scan_badge = next(
                item
                for item in instruction_page.plans
                if item.component_id == "forge-kit-p2-instruction-badge-1"
            )
            checklist_card = next(
                item
                for item in instruction_page.plans
                if item.component_id == "forge-kit-p2-checklist-card"
            )
            footer_rule = next(
                item
                for item in instruction_page.plans
                if item.component_id == "forge-kit-p2-instruction-footer-rule"
            )
            self.assertLess(warning_icon.proof.rect.y_mm, 65.0)
            self.assertLess(first_card.proof.rect.y_mm, 85.0)
            self.assertGreater(first_qr.proof.rect.width_mm, 45.0)
            self.assertLess(scan_badge.proof.rect.y_mm, 45.0)
            self.assertGreater(scan_badge.proof.rect.width_mm, 40.0)
            self.assertGreater(checklist_card.proof.rect.height_mm, 80.0)
            self.assertGreater(footer_rule.proof.rect.y_mm, 260.0)
            validate_render_artifact_proof(
                artifact_label="direct Forge kit document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )

    def test_render_kit_writes_valid_pdf_with_instruction_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "kit.pdf"
            inputs = _kit_inputs(output_path, count=4)

            result = render_forge_kit_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Forge kit document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Forge kit document",
                reader=reader,
                expected_text=("KIT 01", "HOW TO REBUILD THE RECOVERY KIT"),
            )

    def test_build_kit_plan_paginates_many_qr_chunks(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _kit_inputs(Path(tmp) / "kit.pdf", count=14)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_kit_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 4)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 14)

    def test_letter_kit_preserves_qr_size_and_footer_clearance(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _kit_inputs(
                Path(tmp) / "kit-letter.pdf",
                count=14,
                paper_size="LETTER",
            )
            surface = FpdfSurface(
                page_width_mm=LETTER_WIDTH_MM,
                page_height_mm=LETTER_HEIGHT_MM,
            )
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_kit_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 4)
            for page in plan.page_plans:
                self.assertAlmostEqual(page.rect.width_mm, LETTER_WIDTH_MM)
                self.assertAlmostEqual(page.rect.height_mm, LETTER_HEIGHT_MM)
                self.assertTrue(all(item.satisfied for item in page.proof.separation_constraints))
            qr_images = tuple(
                item
                for page in plan.page_plans[:-1]
                for item in page.plans
                if "-qr-image-" in item.component_id
            )
            self.assertTrue(qr_images)
            self.assertTrue(all(item.proof.rect.width_mm >= 45.0 for item in qr_images))

    def test_letter_kit_index_derives_inventory_capacity_without_overlap(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _kit_index_inputs(
                Path(tmp) / "kit-index-letter.pdf",
                row_count=20,
                paper_size="LETTER",
            )
            surface = FpdfSurface(
                page_width_mm=LETTER_WIDTH_MM,
                page_height_mm=LETTER_HEIGHT_MM,
            )
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_kit_index_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 4)
            first_page = plan.page_plans[0]
            inventory_rows = tuple(
                item for item in first_page.plans if "-inventory-row-" in item.component_id
            )
            custody_cards = tuple(
                item for item in first_page.plans if "-custody-card-" in item.component_id
            )
            self.assertEqual(len(inventory_rows), 2)
            self.assertTrue(custody_cards)
            self.assertLessEqual(
                max(item.proof.rect.bottom_mm for item in inventory_rows),
                min(item.proof.rect.y_mm for item in custody_cards),
            )
            self.assertTrue(
                all(
                    constraint.satisfied
                    for page in plan.page_plans
                    for constraint in page.proof.separation_constraints
                )
            )

    def test_letter_kit_index_continuation_starts_after_measured_header(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _kit_index_inputs(
                Path(tmp) / "kit-index-letter.pdf",
                row_count=20,
                paper_size="LETTER",
            )
            surface = FpdfSurface(
                page_width_mm=LETTER_WIDTH_MM,
                page_height_mm=LETTER_HEIGHT_MM,
            )
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_kit_index_direct_plan(surface, inputs)

            self.assertGreater(len(plan.page_plans), 1)
            for page in plan.page_plans[1:]:
                header_rule = next(
                    item for item in page.plans if item.component_id.endswith("-header-rule")
                )
                continuation_panel = next(
                    item for item in page.plans if item.component_id.endswith("-continuation-panel")
                )
                self.assertLessEqual(
                    header_rule.proof.rect.bottom_mm + 2.0,
                    continuation_panel.proof.rect.y_mm,
                )

    def test_build_kit_index_plan_uses_inventory_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _kit_index_inputs(Path(tmp) / "kit_index.pdf", row_count=6)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_kit_index_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 2)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 0)
            validate_render_artifact_proof(
                artifact_label="direct Forge kit-index document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )

    def test_render_kit_index_writes_valid_pdf_with_inventory_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "kit_index.pdf"
            inputs = _kit_index_inputs(output_path, row_count=2)

            result = render_forge_kit_index_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Forge kit-index document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Forge kit-index document",
                reader=reader,
                expected_text=("RECOVERY KIT", "INDEX", "KIT-PAGE-01", "CHAIN OF CUSTODY"),
            )


if __name__ == "__main__":
    unittest.main()
