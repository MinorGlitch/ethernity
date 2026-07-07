import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    FpdfSurface,
    build_forge_main_direct_plan,
    packaged_direct_pdf_assets,
    render_forge_main_direct_pdf,
)
from ethernity.render.direct_pdf.page import DirectPdfPagePlan, PaintPlan
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
            doc_id=b"\x99" * DOC_ID_LEN,
            index=index,
            total=count,
            data=f"payload-{index}".encode("ascii"),
        )
        for index in range(count)
    )


def _inputs(output_path: Path, *, frame_count: int = 3) -> RenderInputs:
    return RenderInputs(
        frames=_frames(frame_count),
        output_path=output_path,
        context={
            "paper_size": "A4",
            "doc_id": "99" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
        },
        doc_type=DOC_TYPE_MAIN,
        design_name="forge",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=False,
    )


def _component(page_plan: DirectPdfPagePlan, component_id: str) -> PaintPlan:
    return next(plan for plan in page_plan.plans if plan.component_id == component_id)


class TestDirectPdfForgeMain(unittest.TestCase):
    def test_build_plan_places_qr_payloads_and_artifact_proof(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "main.pdf", frame_count=4)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_main_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 1)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 4)
            self.assertEqual(plan.artifact_proof.physical_qr_payload_indexes, (0, 1, 2, 3))
            validate_render_artifact_proof(
                artifact_label="direct Forge main document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )

    def test_render_writes_valid_pdf_with_segment_labels(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "main.pdf"
            inputs = _inputs(output_path, frame_count=3)

            result = render_forge_main_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            self.assertIsNotNone(result.layout_proof)
            self.assertEqual(result.layout_proof.backend, "direct_pdf")
            self.assertEqual(result.layout_proof.page_count, len(reader.pages))
            self.assertFalse(result.layout_proof.overflow)
            self.assertIn("forge-main-p1-header-rule", result.layout_proof.pages[0].component_ids)
            validate_render_artifact_proof(
                artifact_label="direct Forge main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Forge main document",
                reader=reader,
                expected_text=("SEGMENT 01", "SEGMENT 02", "SEGMENT 03"),
            )

    def test_render_writes_direct_layout_debug_json_sidecar(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "main.pdf"
            debug_path = Path(tmp) / "debug" / "layout.json"
            inputs = RenderInputs(
                frames=_frames(2),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "99" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_MAIN,
                design_name="forge",
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
                layout_debug_json_path=debug_path,
            )

            render_forge_main_direct_pdf(inputs)

            payload = json.loads(debug_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["backend"], "direct_pdf")
            self.assertEqual(payload["style_name"], "forge")
            self.assertEqual(payload["design_name"], "forge")
            self.assertEqual(payload["doc_type"], DOC_TYPE_MAIN)
            self.assertEqual(payload["page_count"], 1)
            self.assertFalse(payload["pages"][0]["overflow"])
            self.assertGreater(payload["pages"][0]["component_count"], 0)
            self.assertIn("rect", payload["pages"][0]["components"][0])
            self.assertIn("component_ids", payload["pages"][0])

    def test_build_plan_paginates_qr_payloads(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "main.pdf", frame_count=10)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_main_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 2)
            self.assertEqual(plan.artifact_proof.page_count, 2)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 10)

    def test_build_plan_keeps_directive_title_clear_of_cards(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "main.pdf", frame_count=4)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_main_direct_plan(surface, inputs)
            page_plan = plan.page_plans[0]

            title = _component(page_plan, "forge-main-p1-directives-title")
            first_card = _component(page_plan, "forge-main-p1-directive-card-0")
            section_rule = _component(page_plan, "forge-main-p1-directives-rule")
            first_qr_card = _component(page_plan, "forge-main-p1-qr-card-0")
            long_directive = _component(page_plan, "forge-main-p1-directive-text-3")

            self.assertLessEqual(title.proof.rect.bottom_mm, first_card.proof.rect.y_mm)
            self.assertLess(first_card.proof.rect.bottom_mm, section_rule.proof.rect.y_mm)
            self.assertLess(section_rule.proof.rect.bottom_mm, first_qr_card.proof.rect.y_mm)
            self.assertEqual(long_directive.proof.line_count, 3)
            self.assertEqual(long_directive.proof.font_size_pt, 9.0)


if __name__ == "__main__":
    unittest.main()
