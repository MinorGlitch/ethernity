import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    FpdfSurface,
    build_sentinel_main_direct_plan,
    packaged_direct_pdf_assets,
    render_sentinel_main_direct_pdf,
)
from ethernity.render.doc_types import DOC_TYPE_MAIN
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
            doc_id=b"\x55" * DOC_ID_LEN,
            index=index,
            total=count,
            data=f"sentinel-main-{index}".encode("ascii"),
        )
        for index in range(count)
    )


def _inputs(output_path: Path, *, count: int = 4) -> RenderInputs:
    frames = _frames(count)
    return RenderInputs(
        frames=frames,
        output_path=output_path,
        context={
            "paper_size": "A4",
            "doc_id": "55" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
        },
        doc_type=DOC_TYPE_MAIN,
        design_name="sentinel",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=False,
    )


class TestDirectPdfSentinelMain(unittest.TestCase):
    def test_build_plan_uses_primary_qr_and_segment_cards(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "main.pdf", count=4)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_main_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 1)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 4)
            self.assertIn(
                "sentinel-main-p1-primary-qr-frame",
                plan.page_plans[0].proof.component_ids,
            )
            self.assertIn(
                "sentinel-main-p1-security-notice-panel",
                plan.page_plans[0].proof.component_ids,
            )
            self.assertIn("sentinel-main-p1-qr-card-1", plan.page_plans[0].proof.component_ids)
            validate_render_artifact_proof(
                artifact_label="direct Sentinel main document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )

    def test_build_plan_paginates_many_qr_payloads(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "main.pdf", count=14)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_main_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 3)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 14)

    def test_render_writes_valid_pdf_with_segment_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "main.pdf"
            inputs = _inputs(output_path, count=4)

            result = render_sentinel_main_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Sentinel main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Sentinel main document",
                reader=reader,
                expected_text=("MAIN DOCUMENT", "Segment 01", "SECURITY NOTICE"),
            )


if __name__ == "__main__":
    unittest.main()
