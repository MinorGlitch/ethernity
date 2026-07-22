import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.core.bounds import MAX_SHARD_CBOR_BYTES
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import resolve_paper_size
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.page_geometry import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.sentinel.shard import (
    build_sentinel_shard_direct_plan,
    render_sentinel_shard_direct_pdf,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.doc_types import DOC_TYPE_SHARD
from ethernity.render.proofs import (
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_text_in_pdf,
)
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


def _frame(*, data: bytes = b"shard-payload") -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.KEY_DOCUMENT,
        doc_id=b"\x44" * DOC_ID_LEN,
        index=0,
        total=1,
        data=data,
    )


def _inputs(output_path: Path, *, data: bytes = b"shard-payload") -> RenderInputs:
    frame = _frame(data=data)
    return RenderInputs(
        frames=(frame,),
        output_path=output_path,
        context={
            "paper_size": "A4",
            "doc_id": "44" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
            "shard_index": 1,
            "shard_total": 3,
            "shard_threshold": 2,
        },
        doc_type=DOC_TYPE_SHARD,
        design_name="sentinel",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=True,
        fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
    )


class TestDirectPdfSentinelShard(unittest.TestCase):
    def test_build_plan_uses_sentinel_shard_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "shard.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_shard_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 1)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 1)
            self.assertIn("sentinel-shard-p1-warning-panel", plan.page_plans[0].proof.component_ids)
            self.assertIn("sentinel-shard-p1-shard-label", plan.page_plans[0].proof.component_ids)
            self.assertIn("sentinel-shard-p1-qr-image", plan.page_plans[0].proof.component_ids)
            self.assertIn(
                "sentinel-shard-p1-fallback-panel",
                plan.page_plans[0].proof.component_ids,
            )
            validate_render_artifact_proof(
                artifact_label="direct Sentinel shard document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Sentinel shard document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=plan.fallback_proof,
            )

    def test_render_writes_valid_pdf_with_fallback_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "shard.pdf"
            inputs = _inputs(output_path)

            result = render_sentinel_shard_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Sentinel shard document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Sentinel shard document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=result.fallback_proof,
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Sentinel shard document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Sentinel shard document",
                reader=reader,
                expected_text=("SHARD DOCUMENT", "SHARD 01", "MANUAL TRANSCRIPTION"),
            )

    def test_build_plan_fits_maximum_frame_on_one_page(self) -> None:
        with TemporaryDirectory() as tmp:
            for paper_name in ("A4", "LETTER"):
                with self.subTest(paper_name=paper_name):
                    paper = resolve_paper_size(paper_name)
                    inputs = _inputs(
                        Path(tmp) / f"shard-{paper_name.lower()}.pdf",
                        data=b"x" * MAX_SHARD_CBOR_BYTES,
                    )
                    inputs = replace(
                        inputs,
                        context={**inputs.context, "paper_size": paper_name},
                        page_size=paper,
                    )
                    surface = FpdfSurface(
                        page_width_mm=paper.width_mm,
                        page_height_mm=paper.height_mm,
                    )
                    packaged_direct_pdf_assets().register_fonts(surface)

                    plan = build_sentinel_shard_direct_plan(surface, inputs)

                    self.assertEqual(len(plan.page_plans), 1)
                    self.assertEqual(plan.artifact_proof.page_count, 1)
                    self.assertEqual(plan.artifact_proof.physical_qr_count, 1)
                    self.assertEqual(plan.artifact_proof.physical_qr_payload_indexes, (0,))
                    self.assertTrue(plan.fallback_proof.fully_consumed)
                    self.assertFalse(plan.page_plans[0].proof.overflow)


if __name__ == "__main__":
    unittest.main()
