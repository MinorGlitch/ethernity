import importlib.util
import json
import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fpdf import FPDF
from PIL import Image
from pypdf import PdfReader

from ethernity.core.bounds import MAX_SHARD_CBOR_BYTES
from ethernity.encoding.framing import FrameType, encode_frame
from ethernity.page_sizes import PaperSize
from ethernity.qr.scan import scan_qr_payloads
from ethernity.render import render_frames_to_pdf
from ethernity.render.designs import list_design_manifests
from ethernity.render.doc_types import (
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.proofs import (
    frame_digest,
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
)
from ethernity.render.recovery_meta import (
    PASSPHRASE_PRINT_MODE_JSON_PARTS,
    build_recovery_meta,
    decode_printed_passphrase,
)
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderComponentLayoutProof,
    RenderFallbackProof,
    RenderInputs,
    RenderRectProof,
    RenderResult,
)

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "render_visual_baselines.py"
_SPEC = importlib.util.spec_from_file_location("render_visual_baselines", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


class TestRenderVisualBaselines(unittest.TestCase):
    def _assert_typography_floors(self, case: object, artifact: object) -> None:
        minimum_font_size = getattr(artifact, "minimum_font_size_pt")
        self.assertIsNotNone(minimum_font_size)
        self.assertGreaterEqual(minimum_font_size, _MODULE.MINIMUM_TEXT_FONT_SIZE_PT)

        baseline_case = _MODULE.VisualBaselineCase(
            design=getattr(case, "design"),
            doc_type=getattr(case, "doc_type"),
            paper_size=getattr(case, "paper_size"),
        )
        if not _MODULE.requires_manual_fallback_line_numbers(baseline_case):
            return
        minimum_line_number_size = getattr(
            artifact,
            "minimum_manual_fallback_line_number_font_size_pt",
        )
        self.assertIsNotNone(minimum_line_number_size)
        self.assertGreaterEqual(
            minimum_line_number_size,
            _MODULE.MINIMUM_MANUAL_FALLBACK_LINE_NUMBER_FONT_SIZE_PT,
        )

    def test_discover_design_cases_uses_design_manifests(self) -> None:
        cases = _MODULE.discover_design_cases()

        discovered = {(case.design, case.doc_type) for case in cases}
        self.assertIn(("forge", DOC_TYPE_MAIN), discovered)
        self.assertIn(("sentinel", DOC_TYPE_KIT_INDEX), discovered)
        self.assertIn(
            ("forge", DOC_TYPE_MAIN, "LETTER"),
            {(case.design, case.doc_type, case.paper_size) for case in cases},
        )

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
        self.assertEqual(inputs.context["kit_qr_chunk_count"], 14)

    def test_every_recovery_renderer_preserves_ambiguous_long_passphrase(self) -> None:
        passphrase = ("alpha  beta\tgamma\npäss-") * 120
        part_pattern = re.compile(r'\b\d+/\d+\s+"(?:\\.|[^"\\\r\n])*"')
        cases = tuple(
            _MODULE.VisualBaselineCase(
                design=manifest.name,
                doc_type=DOC_TYPE_RECOVERY,
                paper_size=paper_size,
            )
            for manifest in list_design_manifests().values()
            if DOC_TYPE_RECOVERY in manifest.documents
            for paper_size in ("A4", "LETTER")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for case in cases:
                with self.subTest(case_id=case.case_id):
                    output_path = (
                        root / case.design / case.paper_size.lower() / "recovery-passphrase.pdf"
                    )
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    inputs = _MODULE.build_sample_inputs(case, output_path)
                    recovery_meta = build_recovery_meta(
                        passphrase=passphrase,
                        quorum_threshold=None,
                        quorum_shares=None,
                        signing_pub=b"\x31" * 32,
                    )

                    result = render_frames_to_pdf(replace(inputs, recovery_meta=recovery_meta))

                    self.assertIsNotNone(result.layout_proof)
                    assert result.layout_proof is not None
                    self.assertFalse(result.layout_proof.overflow)
                    components = tuple(
                        component
                        for page in result.layout_proof.pages
                        for component in page.components
                    )
                    complete, overlaps = _MODULE.content_overlap_evidence(components)
                    self.assertTrue(complete)
                    self.assertEqual(overlaps, ())
                    extracted_text = "\n".join(
                        page.extract_text() or "" for page in PdfReader(output_path).pages
                    )
                    printed_parts = tuple(part_pattern.findall(extracted_text))
                    self.assertGreater(len(printed_parts), 1)
                    self.assertEqual(
                        decode_printed_passphrase(
                            printed_parts,
                            print_mode=PASSPHRASE_PRINT_MODE_JSON_PARTS,
                        ),
                        passphrase,
                    )

    def test_every_shard_document_renderer_is_one_page_at_key_document_data_bound(self) -> None:
        cases = tuple(
            _MODULE.VisualBaselineCase(
                design=manifest.name,
                doc_type=doc_type,
                paper_size=paper_size.name,
                page_spec=paper_size,
            )
            for manifest in list_design_manifests().values()
            for doc_type in (DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD)
            for paper_size in (
                PaperSize("A4", "A4", 210.0, 297.0),
                PaperSize("LETTER", "Letter", 215.9, 279.4),
                PaperSize(
                    "BOUNDARY",
                    "Boundary",
                    manifest.page_support_for(doc_type).minimum_width_mm,
                    manifest.page_support_for(doc_type).minimum_height_mm,
                ),
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for case in cases:
                with self.subTest(case_id=case.case_id):
                    output_path = root / case.design / case.paper_size.lower() / "shard.pdf"
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    inputs = _MODULE.build_sample_inputs(case, output_path)
                    frame = replace(inputs.frames[0], data=b"s" * MAX_SHARD_CBOR_BYTES)
                    inputs = replace(
                        inputs,
                        frames=(frame,),
                        fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
                    )

                    result = render_frames_to_pdf(inputs)

                    reader = PdfReader(output_path)
                    self.assertEqual(len(reader.pages), 1)
                    self.assertIsNotNone(result.artifact_proof)
                    assert result.artifact_proof is not None
                    self.assertEqual(result.artifact_proof.page_count, 1)
                    self.assertEqual(result.artifact_proof.physical_qr_count, 1)
                    self.assertIsNotNone(result.layout_proof)
                    assert result.layout_proof is not None
                    self.assertFalse(result.layout_proof.overflow)
                    components = tuple(
                        component
                        for page in result.layout_proof.pages
                        for component in page.components
                    )
                    constraints = tuple(
                        constraint
                        for page in result.layout_proof.pages
                        for constraint in page.separation_constraints
                    )
                    self.assertTrue(constraints)
                    self.assertTrue(all(constraint.satisfied for constraint in constraints))
                    complete, overlaps = _MODULE.content_overlap_evidence(components)
                    self.assertTrue(complete)
                    self.assertEqual(overlaps, ())

                    font_sizes = tuple(
                        component.font_size_pt
                        for component in components
                        if component.font_size_pt is not None
                    )
                    manual_number_sizes = tuple(
                        component.font_size_pt
                        for component in components
                        if component.font_size_pt is not None
                        and _MODULE.is_manual_fallback_line_number_component(
                            case,
                            component.component_id,
                        )
                    )
                    self._assert_typography_floors(
                        case,
                        SimpleNamespace(
                            minimum_font_size_pt=min(font_sizes),
                            minimum_manual_fallback_line_number_font_size_pt=(
                                min(manual_number_sizes) if manual_number_sizes else None
                            ),
                        ),
                    )
                    qr_sizes = tuple(
                        min(component.rect.width_mm, component.rect.height_mm)
                        for component in components
                        if component.component_type == "image"
                        and "qr" in component.component_id.lower()
                        and "image" in component.component_id.lower()
                    )
                    self.assertTrue(qr_sizes)
                    self.assertGreaterEqual(min(qr_sizes), _MODULE.MINIMUM_QR_IMAGE_SIZE_MM)
                    if case.paper_size in {"A4", "LETTER"}:
                        self.assertEqual(scan_qr_payloads((output_path,)), [encode_frame(frame)])
                        composited_count, skipped_reason = _MODULE.scan_composited_pdf_qr_count(
                            output_path
                        )
                        self.assertIsNone(skipped_reason)
                        self.assertEqual(composited_count, 1)
                    validate_fallback_render_proof(
                        artifact_label=case.case_id,
                        frames=(frame,),
                        fallback_proof=result.fallback_proof,
                    )
                    validate_fallback_text_in_pdf(
                        artifact_label=case.case_id,
                        reader=reader,
                        fallback_sections=inputs.fallback_sections or (),
                        fallback_proof=result.fallback_proof,
                    )

    def test_every_shard_fallback_panel_is_full_width_and_bottom_anchored(self) -> None:
        cases = tuple(
            _MODULE.VisualBaselineCase(
                design=manifest.name,
                doc_type=doc_type,
                paper_size=paper_size.name,
                page_spec=paper_size,
            )
            for manifest in list_design_manifests().values()
            for doc_type in (DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD)
            for paper_size in (
                PaperSize("A4", "A4", 210.0, 297.0),
                PaperSize("LETTER", "Letter", 215.9, 279.4),
                PaperSize("FUTURE_PORTRAIT", "Future portrait", 260.0, 360.0),
            )
        )

        def fallback_container(result: RenderResult) -> tuple[RenderRectProof, RenderRectProof]:
            self.assertIsNotNone(result.layout_proof)
            assert result.layout_proof is not None
            self.assertEqual(len(result.layout_proof.pages), 1)
            page = result.layout_proof.pages[0]
            interior_spans = tuple(
                component.rect.width_mm
                for component in page.components
                if component.component_type in {"panel", "rule"}
                and component.rect.width_mm < page.rect.width_mm - 2.0
            )
            self.assertTrue(interior_spans)
            full_safe_width_mm = max(interior_spans)
            containers = tuple(
                component.rect
                for component in page.components
                if component.component_type == "panel"
                and component.component_id.endswith(
                    ("fallback-panel", "payload-panel", "fallback-block-0")
                )
            )
            self.assertEqual(len(containers), 1)
            self.assertGreaterEqual(containers[0].width_mm, full_safe_width_mm - 1.0)
            return page.rect, containers[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for case in cases:
                with self.subTest(case_id=case.case_id):
                    case_root = root / case.design / case.doc_type / case.paper_size.lower()
                    case_root.mkdir(parents=True, exist_ok=True)
                    normal_inputs = _MODULE.build_sample_inputs(case, case_root / "normal.pdf")
                    normal_result = render_frames_to_pdf(normal_inputs)
                    normal_page, normal_panel = fallback_container(normal_result)

                    frame = replace(normal_inputs.frames[0], data=b"s" * MAX_SHARD_CBOR_BYTES)
                    maximum_inputs = replace(
                        normal_inputs,
                        output_path=case_root / "maximum.pdf",
                        frames=(frame,),
                        fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
                    )
                    maximum_result = render_frames_to_pdf(maximum_inputs)
                    maximum_page, maximum_panel = fallback_container(maximum_result)

                    for page, panel in (
                        (normal_page, normal_panel),
                        (maximum_page, maximum_panel),
                    ):
                        left_margin_mm = panel.x_mm - page.x_mm
                        right_margin_mm = page.right_mm - panel.right_mm
                        self.assertAlmostEqual(left_margin_mm, right_margin_mm, delta=1.0)
                        self.assertGreaterEqual(
                            panel.bottom_mm,
                            page.y_mm + page.height_mm * 0.8,
                        )

                    self.assertAlmostEqual(normal_panel.x_mm, maximum_panel.x_mm, delta=0.1)
                    self.assertAlmostEqual(
                        normal_panel.width_mm,
                        maximum_panel.width_mm,
                        delta=0.1,
                    )
                    self.assertAlmostEqual(
                        normal_panel.bottom_mm,
                        maximum_panel.bottom_mm,
                        delta=0.1,
                    )
                    self.assertLessEqual(normal_panel.height_mm, maximum_panel.height_mm)

    def test_every_shard_renderer_designates_an_unlabeled_fallback_payload_region(self) -> None:
        cases = tuple(
            _MODULE.VisualBaselineCase(design=manifest.name, doc_type=doc_type)
            for manifest in list_design_manifests().values()
            for doc_type in (DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for case in cases:
                with self.subTest(case_id=case.case_id):
                    output_path = root / case.design / case.doc_type / "unlabeled.pdf"
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    inputs = _MODULE.build_sample_inputs(case, output_path)
                    frame = inputs.frames[0]
                    inputs = replace(
                        inputs,
                        fallback_sections=(FallbackSection(label=None, frame=frame),),
                    )

                    result = render_frames_to_pdf(inputs)
                    reader = PdfReader(output_path)

                    self.assertEqual(len(reader.pages), 1)
                    validate_fallback_text_in_pdf(
                        artifact_label=case.case_id,
                        reader=reader,
                        fallback_sections=inputs.fallback_sections or (),
                        fallback_proof=result.fallback_proof,
                    )

    def test_every_shard_fallback_text_adapts_to_its_measured_container_width(self) -> None:
        cases = tuple(
            _MODULE.VisualBaselineCase(
                design=manifest.name,
                doc_type=doc_type,
                paper_size=paper_size.name,
                page_spec=paper_size,
            )
            for manifest in list_design_manifests().values()
            for doc_type in (DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD)
            for paper_size in (
                PaperSize("A4", "A4", 210.0, 297.0),
                PaperSize("LETTER", "Letter", 215.9, 279.4),
                PaperSize("FUTURE_PORTRAIT", "Future portrait", 260.0, 360.0),
            )
        )

        def fallback_container(page: object) -> RenderRectProof:
            components = getattr(page, "components")
            containers = tuple(
                component.rect
                for component in components
                if component.component_type == "panel"
                and component.component_id.endswith(
                    ("fallback-panel", "payload-panel", "fallback-block-0")
                )
            )
            self.assertEqual(len(containers), 1)
            return containers[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for case in cases:
                for payload_name, payload_size in (
                    ("compact", 400),
                    ("maximum", MAX_SHARD_CBOR_BYTES),
                ):
                    with self.subTest(case_id=case.case_id, payload=payload_name):
                        output_path = (
                            root
                            / case.design
                            / case.doc_type
                            / case.paper_size.lower()
                            / f"{payload_name}.pdf"
                        )
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        inputs = _MODULE.build_sample_inputs(case, output_path)
                        frame = replace(inputs.frames[0], data=b"s" * payload_size)
                        inputs = replace(
                            inputs,
                            frames=(frame,),
                            fallback_sections=(FallbackSection(label=None, frame=frame),),
                        )

                        result = render_frames_to_pdf(inputs)

                        self.assertIsNotNone(result.layout_proof)
                        assert result.layout_proof is not None
                        self.assertEqual(len(result.layout_proof.pages), 1)
                        page = result.layout_proof.pages[0]
                        panel = fallback_container(page)
                        lines = tuple(
                            component
                            for component in page.components
                            if (
                                "fallback-line" in component.component_id
                                or "payload-line" in component.component_id
                            )
                            and component.used_rect is not None
                        )
                        self.assertTrue(lines)
                        columns: dict[float, list[RenderComponentLayoutProof]] = {}
                        for line in lines:
                            columns.setdefault(round(line.rect.x_mm, 2), []).append(line)

                        if payload_name == "compact":
                            self.assertEqual(len(columns), 1)
                            self.assertGreaterEqual(lines[0].rect.width_mm, panel.width_mm * 0.75)
                        else:
                            self.assertLessEqual(len(columns), 2)

                        for column_lines in columns.values():
                            ordered = sorted(column_lines, key=lambda item: item.rect.y_mm)
                            full_lines = ordered[:-1] or ordered
                            for line in full_lines:
                                assert line.used_rect is not None
                                self.assertGreaterEqual(
                                    line.used_rect.width_mm,
                                    line.rect.width_mm * 0.78,
                                )

    def test_every_shard_renderer_rejects_ambiguous_fallback_sources(self) -> None:
        cases = tuple(
            _MODULE.VisualBaselineCase(design=manifest.name, doc_type=doc_type)
            for manifest in list_design_manifests().values()
            for doc_type in (DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for case in cases:
                output_path = root / case.design / case.doc_type / "shard.pdf"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                inputs = _MODULE.build_sample_inputs(case, output_path)
                section = (inputs.fallback_sections or ())[0]

                with self.subTest(case_id=case.case_id, invalid_shape="duplicate-section"):
                    with self.assertRaisesRegex(ValueError, "exactly one fallback section"):
                        render_frames_to_pdf(replace(inputs, fallback_sections=(section, section)))

                mismatched_frame = replace(section.frame, data=section.frame.data + b"x")
                with self.subTest(case_id=case.case_id, invalid_shape="mismatched-frame"):
                    with self.assertRaisesRegex(ValueError, "must match its QR frame"):
                        render_frames_to_pdf(
                            replace(
                                inputs,
                                fallback_sections=(
                                    FallbackSection(
                                        label=section.label,
                                        frame=mismatched_frame,
                                    ),
                                ),
                            )
                        )

                wrong_role_frame = replace(
                    section.frame,
                    frame_type=FrameType.MAIN_DOCUMENT,
                )
                with self.subTest(case_id=case.case_id, invalid_shape="wrong-frame-role"):
                    with self.assertRaisesRegex(ValueError, "KEY_DOCUMENT frame"):
                        render_frames_to_pdf(
                            replace(
                                inputs,
                                frames=(wrong_role_frame,),
                                fallback_sections=(
                                    FallbackSection(
                                        label=section.label,
                                        frame=wrong_role_frame,
                                    ),
                                ),
                            )
                        )

                with self.subTest(case_id=case.case_id, invalid_shape="unrelated-qr-payload"):
                    with self.assertRaisesRegex(
                        ValueError,
                        "QR payload must encode its shard frame",
                    ):
                        render_frames_to_pdf(replace(inputs, qr_payloads=(b"UNRELATED",)))

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
                require_evidence=False,
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
        self.assertEqual(report.schema_version, 7)
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
                require_evidence=False,
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

    def test_manual_fallback_line_number_detection_is_design_specific(self) -> None:
        archive_shard = _MODULE.VisualBaselineCase(
            design="archive",
            doc_type=DOC_TYPE_SHARD,
        )
        forge_recovery = _MODULE.VisualBaselineCase(
            design="forge",
            doc_type=DOC_TYPE_RECOVERY,
        )
        forge_shard = _MODULE.VisualBaselineCase(
            design="forge",
            doc_type=DOC_TYPE_SHARD,
        )
        sentinel_recovery = _MODULE.VisualBaselineCase(
            design="sentinel",
            doc_type=DOC_TYPE_RECOVERY,
        )

        self.assertTrue(_MODULE.requires_manual_fallback_line_numbers(archive_shard))
        self.assertTrue(_MODULE.requires_manual_fallback_line_numbers(forge_recovery))
        self.assertTrue(_MODULE.requires_manual_fallback_line_numbers(sentinel_recovery))
        self.assertFalse(_MODULE.requires_manual_fallback_line_numbers(forge_shard))
        self.assertTrue(
            _MODULE.is_manual_fallback_line_number_component(
                archive_shard,
                "archive-shard-p1-fallback-line-0-1",
            )
        )
        self.assertTrue(
            _MODULE.is_manual_fallback_line_number_component(
                forge_recovery,
                "forge-recovery-p2-fallback-line-number-3",
            )
        )
        self.assertFalse(
            _MODULE.is_manual_fallback_line_number_component(
                forge_shard,
                "forge-shard-p2-fallback-line-3",
            )
        )

    def test_typography_gate_rejects_text_below_six_points(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_MAIN)
        artifact = SimpleNamespace(
            minimum_font_size_pt=5.99,
            layout_component_count=1,
            minimum_manual_fallback_line_number_font_size_pt=None,
        )

        with self.assertRaisesRegex(RuntimeError, "text font floor failed"):
            _MODULE.validate_typography_floor(case, artifact)

    def test_typography_gate_rejects_small_or_missing_manual_line_numbers(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_RECOVERY)
        for minimum_line_number_size, expected_message in (
            (None, "line-number evidence is missing"),
            (6.49, "line-number font floor failed"),
        ):
            with self.subTest(minimum_line_number_size=minimum_line_number_size):
                artifact = SimpleNamespace(
                    minimum_font_size_pt=6.0,
                    layout_component_count=1,
                    minimum_manual_fallback_line_number_font_size_pt=(minimum_line_number_size),
                )

                with self.assertRaisesRegex(RuntimeError, expected_message):
                    _MODULE.validate_typography_floor(case, artifact)

    def test_render_visual_baselines_rejects_layout_proof_failures(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_MAIN)
        failures = (
            (
                SimpleNamespace(
                    layout_overflow=True,
                    layout_component_count=1,
                    separation_constraint_count=1,
                    separation_constraints_satisfied=True,
                ),
                "layout overflow",
            ),
            (
                SimpleNamespace(
                    layout_overflow=False,
                    layout_component_count=1,
                    separation_constraint_count=1,
                    separation_constraints_satisfied=False,
                ),
                "separation constraint",
            ),
        )

        for artifact, expected_message in failures:
            with (
                self.subTest(expected_message=expected_message),
                tempfile.TemporaryDirectory() as tmp,
            ):
                with mock.patch.object(
                    _MODULE,
                    "render_baseline_artifact",
                    return_value=artifact,
                ):
                    with self.assertRaisesRegex(RuntimeError, expected_message):
                        _MODULE.render_visual_baselines(
                            Path(tmp) / "baselines",
                            cases=(case,),
                            rasterize="never",
                        )

    def test_layout_gate_rejects_missing_proof_inventory(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_MAIN)
        missing_cases = (
            (
                SimpleNamespace(
                    layout_overflow=None,
                    layout_component_count=0,
                    separation_constraint_count=0,
                    separation_constraints_satisfied=None,
                ),
                "layout proof is missing",
            ),
            (
                SimpleNamespace(
                    layout_overflow=False,
                    layout_component_count=1,
                    separation_constraint_count=0,
                    separation_constraints_satisfied=None,
                ),
                "separation-constraint proof is missing",
            ),
        )

        for artifact, expected_message in missing_cases:
            with self.subTest(expected_message=expected_message):
                with self.assertRaisesRegex(RuntimeError, expected_message):
                    _MODULE.validate_layout_evidence(case, artifact)

    def test_layout_gate_rejects_content_overlap_and_missing_visible_rects(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_MAIN)
        missing = SimpleNamespace(
            layout_overflow=False,
            layout_component_count=1,
            separation_constraint_count=1,
            separation_constraints_satisfied=True,
            content_overlap_evidence_complete=False,
            content_overlap_count=0,
            content_overlap_pairs=(),
        )
        overlapping = SimpleNamespace(
            layout_overflow=False,
            layout_component_count=2,
            separation_constraint_count=1,
            separation_constraints_satisfied=True,
            content_overlap_evidence_complete=True,
            content_overlap_count=1,
            content_overlap_pairs=("heading (text) intersects qr (image)",),
        )

        with self.assertRaisesRegex(RuntimeError, "content-overlap evidence is incomplete"):
            _MODULE.validate_layout_evidence(case, missing)
        with self.assertRaisesRegex(RuntimeError, "content overlap detected"):
            _MODULE.validate_layout_evidence(case, overlapping)

    def test_content_overlap_evidence_checks_text_and_images_but_not_image_compounds(self) -> None:
        def component(
            component_id: str,
            component_type: str,
            rect: RenderRectProof,
            *,
            used_rect: RenderRectProof | None = None,
        ) -> RenderComponentLayoutProof:
            return RenderComponentLayoutProof(
                component_id=component_id,
                rect=rect,
                used_rect=used_rect,
                overflow=False,
                component_type=component_type,
            )

        text_rect = RenderRectProof(0.0, 0.0, 10.0, 10.0)
        components = (
            component("heading", "text", text_rect, used_rect=text_rect),
            component(
                "caption",
                "text",
                RenderRectProof(5.0, 5.0, 10.0, 10.0),
                used_rect=RenderRectProof(5.0, 5.0, 10.0, 10.0),
            ),
            component("qr-image", "image", RenderRectProof(12.0, 12.0, 10.0, 10.0)),
            component("qr-frame", "image", RenderRectProof(12.0, 12.0, 10.0, 10.0)),
        )

        complete, overlaps = _MODULE.content_overlap_evidence(components)

        self.assertTrue(complete)
        self.assertEqual(len(overlaps), 3)
        self.assertFalse(any("qr-image (image) intersects qr-frame" in item for item in overlaps))

        missing_used_rect = component("missing", "text", text_rect)
        complete, _overlaps = _MODULE.content_overlap_evidence((missing_used_rect,))
        self.assertFalse(complete)

    def test_production_default_rejects_synthetic_renderer_without_proof(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_MAIN)

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "layout proof is missing"):
                _MODULE.render_visual_baselines(
                    Path(temp_dir) / "baselines",
                    cases=(case,),
                    rasterize="never",
                    renderer=_fake_pdf_renderer,
                )

    def test_page_label_gate_rejects_missing_and_incomplete_evidence(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_MAIN)
        missing = SimpleNamespace(
            numbered_page_count=None,
            all_pages_numbered=None,
            page_count=2,
        )
        incomplete = SimpleNamespace(
            numbered_page_count=1,
            all_pages_numbered=False,
            page_count=2,
        )

        with self.assertRaisesRegex(RuntimeError, "page-label evidence is missing"):
            _MODULE.validate_page_label_evidence(case, missing)
        with self.assertRaisesRegex(RuntimeError, "page-label coverage mismatch"):
            _MODULE.validate_page_label_evidence(case, incomplete)

    def test_shard_page_count_gate_requires_one_page_and_one_physical_qr(self) -> None:
        shard_case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_SHARD)
        signing_case = _MODULE.VisualBaselineCase(
            design="sentinel",
            doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
        )
        valid = SimpleNamespace(page_count=1, expected_qr_count=1)

        _MODULE.validate_page_count_contract(shard_case, valid)
        _MODULE.validate_page_count_contract(signing_case, valid)

        with self.assertRaisesRegex(RuntimeError, "page-count contract failed"):
            _MODULE.validate_page_count_contract(
                shard_case,
                SimpleNamespace(page_count=2, expected_qr_count=2),
            )
        with self.assertRaisesRegex(RuntimeError, "QR-count contract failed"):
            _MODULE.validate_page_count_contract(
                signing_case,
                SimpleNamespace(page_count=1, expected_qr_count=2),
            )

        main_case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_MAIN)
        _MODULE.validate_page_count_contract(
            main_case,
            SimpleNamespace(page_count=3, expected_qr_count=12),
        )

    def test_poppler_gate_is_strict_by_default_but_portable_tests_can_opt_out(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_MAIN)
        missing = SimpleNamespace(
            poppler_clean=None,
            poppler_warning_count=None,
            poppler_skipped_reason="Poppler tools not found",
        )

        with self.assertRaisesRegex(RuntimeError, "Poppler evidence is missing"):
            _MODULE.validate_poppler_evidence(
                case,
                missing,
                strict_external_tools=True,
            )
        _MODULE.validate_poppler_evidence(
            case,
            missing,
            strict_external_tools=False,
        )

        failed = SimpleNamespace(
            poppler_clean=False,
            poppler_warning_count=1,
            poppler_skipped_reason=None,
        )
        with self.assertRaisesRegex(RuntimeError, "Poppler reported"):
            _MODULE.validate_poppler_evidence(
                case,
                failed,
                strict_external_tools=False,
            )
        incomplete = SimpleNamespace(
            poppler_clean=True,
            poppler_warning_count=None,
            poppler_skipped_reason=None,
        )
        with self.assertRaisesRegex(RuntimeError, "warning-count evidence is missing"):
            _MODULE.validate_poppler_evidence(
                case,
                incomplete,
                strict_external_tools=False,
            )

    def test_qr_gate_requires_embedded_composited_and_physical_size_evidence(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_MAIN)
        valid = {
            "expected_qr_count": 2,
            "decoded_qr_count": 2,
            "qr_scan_succeeded": True,
            "minimum_qr_image_size_mm": _MODULE.MINIMUM_QR_IMAGE_SIZE_MM,
            "composited_decoded_qr_count": 2,
            "composited_qr_scan_succeeded": True,
            "composited_qr_scan_skipped_reason": None,
        }
        failures = (
            ({**valid, "expected_qr_count": None}, "QR proof is missing"),
            ({**valid, "qr_scan_succeeded": None}, "QR scan evidence failed or is missing"),
            ({**valid, "minimum_qr_image_size_mm": None}, "QR-size evidence is missing"),
            (
                {
                    **valid,
                    "minimum_qr_image_size_mm": _MODULE.MINIMUM_QR_IMAGE_SIZE_MM - 0.01,
                },
                "QR physical-size floor failed",
            ),
            (
                {**valid, "composited_qr_scan_succeeded": False},
                "composited QR scan count mismatch",
            ),
            (
                {**valid, "composited_decoded_qr_count": None},
                "composited QR scan count evidence is missing",
            ),
            (
                {
                    **valid,
                    "composited_qr_scan_succeeded": None,
                    "composited_qr_scan_skipped_reason": "pdftoppm not found",
                },
                "composited QR scan evidence is missing",
            ),
        )

        for artifact_values, expected_message in failures:
            with self.subTest(expected_message=expected_message):
                with self.assertRaisesRegex(RuntimeError, expected_message):
                    _MODULE.validate_qr_evidence(
                        case,
                        SimpleNamespace(**artifact_values),
                        strict_external_tools=True,
                    )

        missing_composited = SimpleNamespace(
            **{
                **valid,
                "composited_qr_scan_succeeded": None,
                "composited_qr_scan_skipped_reason": "pdftoppm not found",
            }
        )
        _MODULE.validate_qr_evidence(
            case,
            missing_composited,
            strict_external_tools=False,
        )

    def test_render_visual_baselines_requires_fallback_artifact_proof(self) -> None:
        case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_RECOVERY)

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "artifact proof is missing"):
                _MODULE.render_visual_baselines(
                    Path(temp_dir) / "baselines",
                    cases=(case,),
                    rasterize="never",
                    renderer=_fake_pdf_renderer,
                )

    def test_fallback_proof_gate_rejects_incomplete_or_inconsistent_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case = _MODULE.VisualBaselineCase(design="forge", doc_type=DOC_TYPE_RECOVERY)
            inputs = _MODULE.build_sample_inputs(case, Path(temp_dir) / "recovery.pdf")

        sections = inputs.fallback_sections
        valid_proof = RenderFallbackProof(
            section_frame_digests=tuple(frame_digest(section.frame) for section in sections),
            section_titles=tuple(section.label for section in sections),
            expected_section_count=len(sections),
            emitted_block_count=len(sections),
            emitted_line_count=2,
            consumed_section_count=len(sections),
            fully_consumed=True,
            emitted_fallback_lines=("line one", "line two"),
        )
        invalid_proofs = (
            replace(valid_proof, fully_consumed=False),
            replace(valid_proof, emitted_line_count=3),
            replace(valid_proof, consumed_section_count=len(sections) - 1),
        )

        for fallback_proof in invalid_proofs:
            with self.subTest(fallback_proof=fallback_proof):
                result = RenderResult(
                    fallback_proof=fallback_proof,
                    artifact_proof=RenderArtifactProof(
                        output_path=str(inputs.output_path),
                        doc_type=inputs.doc_type,
                        frame_digests=tuple(frame_digest(frame) for frame in inputs.frames),
                        encoded_payload_count=len(inputs.frames),
                        physical_qr_count=0,
                        fallback_proof=fallback_proof,
                    ),
                )

                with self.assertRaisesRegex(RuntimeError, "fallback render proof failed"):
                    _MODULE.validate_fallback_proof_evidence(case, inputs, result)

    def test_every_design_document_renders_at_its_declared_geometry_boundary(self) -> None:
        cases = tuple(
            _MODULE.VisualBaselineCase(
                design=manifest.name,
                doc_type=doc_type,
                paper_size="BOUNDARY",
                page_spec=PaperSize(
                    "BOUNDARY",
                    "Boundary",
                    manifest.page_support_for(doc_type).minimum_width_mm,
                    manifest.page_support_for(doc_type).minimum_height_mm,
                ),
            )
            for manifest in list_design_manifests().values()
            for doc_type in sorted(manifest.documents)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            report = _MODULE.render_visual_baselines(
                Path(temp_dir) / "boundary-matrix",
                cases=cases,
                rasterize="never",
                strict_external_tools=False,
            )

        self.assertEqual(len(report.cases), 27)
        for case in report.cases:
            with self.subTest(case_id=case.case_id):
                artifact = case.artifacts[0]
                self.assertGreater(artifact.page_count, 0)
                self.assertFalse(artifact.layout_overflow)
                self.assertGreater(artifact.layout_component_count, 0)
                self.assertGreater(artifact.separation_constraint_count, 0)
                self.assertTrue(artifact.separation_constraints_satisfied)
                self._assert_typography_floors(case, artifact)
                self.assertIn(artifact.qr_scan_succeeded, {True, None})
                self.assertTrue(artifact.all_pages_numbered)
                self.assertIn(artifact.poppler_clean, {True, None})
                self.assertIn(artifact.composited_qr_scan_succeeded, {True, None})

    def test_every_design_document_renders_on_conventional_future_page_sizes(self) -> None:
        future_pages = (
            PaperSize("LEGAL", "Legal", 215.9, 355.6),
            PaperSize("A3", "A3", 297.0, 420.0),
        )
        cases = tuple(
            _MODULE.VisualBaselineCase(
                design=manifest.name,
                doc_type=doc_type,
                paper_size=page.name,
                page_spec=page,
            )
            for page in future_pages
            for manifest in list_design_manifests().values()
            for doc_type in sorted(manifest.documents)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            report = _MODULE.render_visual_baselines(
                Path(temp_dir) / "future-size-matrix",
                cases=cases,
                rasterize="never",
                strict_external_tools=False,
            )

        self.assertEqual(len(report.cases), 54)
        for case in report.cases:
            with self.subTest(case_id=case.case_id):
                artifact = case.artifacts[0]
                self.assertFalse(artifact.layout_overflow)
                self.assertGreater(artifact.separation_constraint_count, 0)
                self.assertTrue(artifact.separation_constraints_satisfied)
                self._assert_typography_floors(case, artifact)
                self.assertIn(artifact.qr_scan_succeeded, {True, None})
                self.assertTrue(artifact.all_pages_numbered)
                self.assertIn(artifact.poppler_clean, {True, None})
                self.assertIn(artifact.composited_qr_scan_succeeded, {True, None})

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
