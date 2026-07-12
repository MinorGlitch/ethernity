import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    FpdfSurface,
    build_forge_shard_direct_plan,
    packaged_direct_pdf_assets,
    render_forge_shard_direct_pdf,
)
from ethernity.render.doc_types import DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD
from ethernity.render.proofs import (
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_render_layout_proof,
    validate_text_in_pdf,
)
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


def _frame(*, data: bytes = b"shard-payload") -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.KEY_DOCUMENT,
        doc_id=b"\xaa" * DOC_ID_LEN,
        index=0,
        total=1,
        data=data,
    )


def _inputs(
    output_path: Path,
    *,
    doc_type: str = DOC_TYPE_SHARD,
    data: bytes = b"shard-payload",
) -> RenderInputs:
    frame = _frame(data=data)
    return RenderInputs(
        frames=(frame,),
        output_path=output_path,
        context={
            "paper_size": "A4",
            "doc_id": "aa" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
            "shard_index": 1,
            "shard_total": 3,
            "shard_threshold": 2,
        },
        doc_type=doc_type,
        design_name="forge",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=True,
        fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
    )


class TestDirectPdfForgeShard(unittest.TestCase):
    def test_build_plan_places_qr_and_fallback_proofs(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "shard.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_shard_direct_plan(surface, inputs)

            self.assertGreaterEqual(len(plan.page_plans), 1)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertEqual(plan.artifact_proof.physical_qr_payload_indexes[0], 0)
            qr_frame = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "forge-shard-p1-qr-frame"
            )
            fallback_panel = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "forge-shard-p1-fallback-panel"
            )
            self.assertGreaterEqual(
                fallback_panel.proof.rect.y_mm,
                qr_frame.proof.rect.bottom_mm + 8.0,
            )
            validate_render_artifact_proof(
                artifact_label="direct Forge shard document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Forge shard document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=plan.fallback_proof,
            )

    def test_render_writes_valid_pdf_with_fallback_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "shard.pdf"
            inputs = _inputs(output_path)

            result = render_forge_shard_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Forge shard document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_render_layout_proof(
                artifact_label="direct Forge shard document",
                layout_proof=result.layout_proof,
                expected_page_count=len(reader.pages),
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Forge shard document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Forge shard document",
                reader=reader,
                expected_text=("SHARD PAYLOAD", "TOTAL SHARDS"),
            )

    def test_explicit_created_timestamp_produces_stable_pdf_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            first_path = Path(tmp) / "first.pdf"
            second_path = Path(tmp) / "second.pdf"

            render_forge_shard_direct_pdf(_inputs(first_path))
            render_forge_shard_direct_pdf(_inputs(second_path))

            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())

    def test_build_plan_paginates_and_repeats_qr_on_continuation(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "shard.pdf"
            inputs = _inputs(output_path, data=b"x" * 700)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_shard_direct_plan(surface, inputs)
            result = render_forge_shard_direct_pdf(inputs)
            reader = validate_pdf_has_pages(output_path)

            self.assertGreater(len(plan.page_plans), 1)
            self.assertEqual(plan.artifact_proof.physical_qr_count, len(plan.page_plans))
            self.assertEqual(
                plan.artifact_proof.physical_qr_payload_indexes,
                tuple(0 for _ in plan.page_plans),
            )
            validate_render_layout_proof(
                artifact_label="paginated direct Forge shard document",
                layout_proof=result.layout_proof,
                expected_page_count=len(reader.pages),
            )
            validate_fallback_text_in_pdf(
                artifact_label="paginated direct Forge shard document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )

    def test_signing_key_shard_doc_type_is_not_accepted_by_shard_renderer(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(
                Path(tmp) / "signing_key_shard.pdf",
                doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
            )
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            with self.assertRaisesRegex(ValueError, "only supports shard documents"):
                build_forge_shard_direct_plan(surface, inputs)


if __name__ == "__main__":
    unittest.main()
