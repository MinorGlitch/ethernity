import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import resolve_paper_size
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.page_geometry import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.sentinel.main import (
    build_sentinel_main_direct_plan,
    render_sentinel_main_direct_pdf,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
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

    def test_compaction_security_notice_fits_a4_and_letter_at_readable_size(self) -> None:
        with TemporaryDirectory() as tmp:
            for paper_name in ("A4", "LETTER"):
                with self.subTest(paper_size=paper_name):
                    page_size = resolve_paper_size(paper_name)
                    base_inputs = _inputs(Path(tmp) / f"main-{paper_name.lower()}.pdf")
                    context = dict(base_inputs.context)
                    context["paper_size"] = paper_name
                    inputs = replace(
                        base_inputs,
                        context=context,
                        lineage=RenderLineage(kind="compaction_checkpoint"),
                        page_size=page_size,
                    )
                    surface = FpdfSurface(
                        page_width_mm=page_size.width_mm,
                        page_height_mm=page_size.height_mm,
                    )
                    packaged_direct_pdf_assets().register_fonts(surface)

                    plan = build_sentinel_main_direct_plan(surface, inputs)

                    page = plan.page_plans[0]
                    plans_by_id = {item.component_id: item for item in page.plans}
                    notice_panel = plans_by_id["sentinel-main-p1-security-notice-panel"]
                    notice_body = plans_by_id["sentinel-main-p1-security-notice-body"]
                    self.assertFalse(page.proof.overflow)
                    self.assertGreaterEqual(notice_body.proof.font_size_pt, 6.0)
                    self.assertGreaterEqual(
                        notice_body.proof.used_rect.y_mm,
                        notice_panel.proof.rect.y_mm,
                    )
                    self.assertLessEqual(
                        notice_body.proof.used_rect.bottom_mm,
                        notice_panel.proof.rect.bottom_mm,
                    )
                    self.assertTrue(
                        all(
                            constraint.satisfied for constraint in page.proof.separation_constraints
                        )
                    )
                    qr_footer_constraints = tuple(
                        constraint
                        for constraint in page.proof.separation_constraints
                        if "qr-footer" in constraint.constraint_id
                    )
                    self.assertEqual(len(qr_footer_constraints), 1)
                    self.assertGreaterEqual(
                        qr_footer_constraints[0].measured_clearance_mm,
                        qr_footer_constraints[0].minimum_clearance_mm,
                    )

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
