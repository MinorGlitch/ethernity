import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.page_geometry import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.sentinel.kit_index import (
    build_sentinel_kit_index_direct_plan,
    render_sentinel_kit_index_direct_pdf,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.doc_types import DOC_TYPE_KIT_INDEX
from ethernity.render.proofs import (
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_text_in_pdf,
)
from ethernity.render.types import RenderInputs, RenderLineage


def _inputs(output_path: Path, *, row_count: int = 3) -> RenderInputs:
    return RenderInputs(
        frames=(),
        output_path=output_path,
        context={
            "paper_size": "A4",
            "doc_id": "88" * 8,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
            "kit_qr_page_count": 1,
            "kit_qr_chunk_count": 3,
            "inventory_rows": tuple(
                {
                    "component_id": f"KIT-CHUNK-{index + 1:02d}",
                    "detail": f"Recovery kit payload chunk {index + 1}",
                    "status": "Generated",
                }
                for index in range(row_count)
            ),
        },
        doc_type=DOC_TYPE_KIT_INDEX,
        design_name="sentinel",
        lineage=RenderLineage(kind="root_backup"),
        qr_payloads=(),
        render_qr=False,
        render_fallback=False,
    )


class TestDirectPdfSentinelKitIndex(unittest.TestCase):
    def test_build_plan_uses_inventory_and_custody_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "kit_index.pdf", row_count=6)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_kit_index_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 2)
            component_ids = plan.page_plans[0].proof.component_ids
            self.assertIn("sentinel-kit-index-p1-stats-band", component_ids)
            self.assertIn("sentinel-kit-index-p1-warning-panel", component_ids)
            self.assertIn("sentinel-kit-index-p1-inventory-table", component_ids)
            self.assertIn("sentinel-kit-index-p1-custody-table", component_ids)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 0)
            validate_render_artifact_proof(
                artifact_label="direct Sentinel kit-index document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )

    def test_render_writes_valid_pdf_with_inventory_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "kit_index.pdf"
            inputs = _inputs(output_path, row_count=2)

            result = render_sentinel_kit_index_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Sentinel kit-index document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Sentinel kit-index document",
                reader=reader,
                expected_text=("RECOVERY KIT INDEX", "HARDWARE INVENTORY", "CHAIN OF CUSTODY"),
            )


if __name__ == "__main__":
    unittest.main()
