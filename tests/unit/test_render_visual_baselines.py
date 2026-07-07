import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fpdf import FPDF
from PIL import Image

from ethernity.render.doc_types import (
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.types import RenderInputs, RenderResult

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "render_visual_baselines.py"
_SPEC = importlib.util.spec_from_file_location("render_visual_baselines", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


class TestRenderVisualBaselines(unittest.TestCase):
    def test_discover_design_cases_uses_design_manifests(self) -> None:
        cases = _MODULE.discover_design_cases()

        discovered = {(case.design, case.doc_type) for case in cases}
        self.assertIn(("forge", DOC_TYPE_MAIN), discovered)
        self.assertIn(("sentinel", DOC_TYPE_KIT_INDEX), discovered)

    def test_build_sample_inputs_sets_recovery_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case = _MODULE.VisualBaselineCase(
                design="forge",
                doc_type=DOC_TYPE_RECOVERY,
            )

            inputs = _MODULE.build_sample_inputs(case, Path(temp_dir) / "recovery.pdf")

        self.assertFalse(inputs.render_qr)
        self.assertTrue(inputs.render_fallback)
        self.assertIsNotNone(inputs.recovery_meta)
        self.assertEqual(len(inputs.fallback_sections), 2)

    def test_build_sample_inputs_sets_kit_index_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case = _MODULE.VisualBaselineCase(
                design="forge",
                doc_type=DOC_TYPE_KIT_INDEX,
            )

            inputs = _MODULE.build_sample_inputs(case, Path(temp_dir) / "kit_index.pdf")

        self.assertEqual(inputs.frames, ())
        self.assertEqual(inputs.qr_payloads, ())
        self.assertFalse(inputs.render_qr)
        self.assertFalse(inputs.render_fallback)
        self.assertEqual(inputs.context["kit_qr_chunk_count"], 3)

    def test_render_visual_baselines_renders_direct_artifacts_for_supported_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            forge_case = _MODULE.VisualBaselineCase(
                design="forge",
                doc_type=DOC_TYPE_MAIN,
            )
            sentinel_case = _MODULE.VisualBaselineCase(
                design="sentinel",
                doc_type=DOC_TYPE_RECOVERY,
            )
            sentinel_main_case = _MODULE.VisualBaselineCase(
                design="sentinel",
                doc_type=DOC_TYPE_MAIN,
            )

            report = _MODULE.render_visual_baselines(
                root / "baselines",
                cases=(forge_case, sentinel_case, sentinel_main_case),
                rasterize="never",
                renderer=_fake_pdf_renderer,
            )
            manifest_path = root / "baselines" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        artifacts = {
            case.case_id: [artifact.renderer for artifact in case.artifacts]
            for case in report.cases
        }
        self.assertEqual(artifacts["forge/main"], ["direct"])
        self.assertEqual(artifacts["sentinel/recovery"], ["direct"])
        self.assertEqual(artifacts["sentinel/main"], ["direct"])
        self.assertEqual(report.schema_version, 3)
        self.assertIn("not pixel-perfect", report.visual_review_note)
        self.assertIn("existing render style", report.visual_review_note)
        self.assertEqual(manifest["visual_review_note"], report.visual_review_note)

    def test_signing_key_shard_baseline_uses_dedicated_direct_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            signing_case = _MODULE.VisualBaselineCase(
                design="forge",
                doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
            )

            report = _MODULE.render_visual_baselines(
                root / "baselines",
                cases=(signing_case,),
                rasterize="never",
                renderer=_fake_pdf_renderer,
            )

        self.assertTrue(report.cases[0].direct_supported)
        self.assertEqual(
            [artifact.renderer for artifact in report.cases[0].artifacts],
            ["direct"],
        )

    def test_direct_renderer_rejects_unsupported_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case = _MODULE.VisualBaselineCase(
                design="archive",
                doc_type=DOC_TYPE_KIT_INDEX,
            )

            with self.assertRaisesRegex(ValueError, "does not support"):
                _MODULE.render_visual_baselines(
                    Path(temp_dir) / "baselines",
                    cases=(case,),
                    rasterize="never",
                    renderer=_fake_pdf_renderer,
                )

    def test_measure_png_pair_diagnostic_reports_pixel_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference = root / "reference.png"
            direct = root / "direct.png"
            Image.new("RGB", (2, 2), (255, 255, 255)).save(reference)
            Image.new("RGB", (2, 2), (0, 255, 255)).save(direct)

            diagnostic = _MODULE.measure_png_pair_diagnostic(root, reference, direct, page_number=1)
            diff_exists = (root / "diff-1.png").exists()

        self.assertEqual(diagnostic.status, "measured")
        self.assertEqual(diagnostic.diff_png, "diff-1.png")
        self.assertTrue(diff_exists)
        self.assertEqual(diagnostic.max_abs_delta, 255)
        self.assertGreater(diagnostic.mean_abs_delta, 0)
        self.assertEqual(
            [region.name for region in diagnostic.regions],
            ["header", "body", "footer"],
        )
        self.assertEqual(diagnostic.regions[0].bbox_px, (0, 0, 2, 1))

    def test_measure_png_pair_diagnostic_normalizes_tiny_size_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reference = root / "reference.png"
            direct = root / "direct.png"
            Image.new("RGB", (2, 2), (255, 255, 255)).save(reference)
            Image.new("RGB", (3, 2), (255, 255, 255)).save(direct)

            diagnostic = _MODULE.measure_png_pair_diagnostic(root, reference, direct, page_number=1)

        self.assertEqual(diagnostic.status, "measured-normalized-size")
        self.assertEqual(diagnostic.width_px, 2)
        self.assertEqual(diagnostic.height_px, 2)
        self.assertEqual(diagnostic.max_abs_delta, 0)
        self.assertEqual(diagnostic.regions[-1].bbox_px, (0, 1, 2, 2))


def _fake_pdf_renderer(inputs: RenderInputs) -> RenderResult:
    pdf = FPDF(unit="mm", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(text=f"{inputs.doc_type} {inputs.output_path}")
    pdf.output(str(inputs.output_path))
    return RenderResult()


if __name__ == "__main__":
    unittest.main()
