import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    FpdfSurface,
    build_sentinel_kit_direct_plan,
    packaged_direct_pdf_assets,
    render_sentinel_kit_direct_pdf,
)
from ethernity.render.doc_types import DOC_TYPE_KIT
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
            doc_id=b"\x88" * DOC_ID_LEN,
            index=index,
            total=count,
            data=f"sentinel-kit-frame-{index}".encode("ascii"),
        )
        for index in range(count)
    )


def _inputs(output_path: Path, *, count: int = 5) -> RenderInputs:
    frames = _frames(count)
    return RenderInputs(
        frames=frames,
        output_path=output_path,
        context={
            "paper_size": "A4",
            "doc_id": "88" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
        },
        doc_type=DOC_TYPE_KIT,
        design_name="sentinel",
        lineage=RenderLineage(kind="recovery_kit"),
        qr_payloads=tuple(f"kit-chunk-{index}" for index in range(count)),
        render_qr=True,
        render_fallback=False,
    )


class TestDirectPdfSentinelKit(unittest.TestCase):
    def test_build_plan_places_qr_payloads_and_instruction_page(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "kit.pdf", count=5)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_kit_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 2)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 5)
            self.assertEqual(plan.artifact_proof.physical_qr_payload_indexes, (0, 1, 2, 3, 4))
            warning_panel = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "sentinel-kit-p1-warning-panel"
            )
            first_card = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "sentinel-kit-p1-qr-card-0"
            )
            first_qr = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "sentinel-kit-p1-qr-image-0"
            )
            instruction_page = plan.page_plans[-1]
            title = next(
                item
                for item in instruction_page.plans
                if item.component_id == "sentinel-kit-p2-instruction-title"
            )
            checklist_card = next(
                item
                for item in instruction_page.plans
                if item.component_id == "sentinel-kit-p2-checklist-card"
            )

            self.assertLess(warning_panel.proof.rect.y_mm, 35.0)
            self.assertGreater(first_card.proof.rect.width_mm, 55.0)
            self.assertGreater(first_qr.proof.rect.width_mm, 49.0)
            self.assertLess(title.proof.rect.y_mm, 25.0)
            self.assertGreater(checklist_card.proof.rect.height_mm, 80.0)
            validate_render_artifact_proof(
                artifact_label="direct Sentinel kit document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )

    def test_render_writes_valid_pdf_with_instruction_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "kit.pdf"
            inputs = _inputs(output_path, count=4)

            result = render_sentinel_kit_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Sentinel kit document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Sentinel kit document",
                reader=reader,
                expected_text=("PART 01", "HOW TO REBUILD THE RECOVERY KIT"),
            )

    def test_build_plan_paginates_many_qr_chunks(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "kit.pdf", count=14)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_kit_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 3)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 14)


if __name__ == "__main__":
    unittest.main()
