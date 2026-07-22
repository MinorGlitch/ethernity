import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import ethernity.render.direct_pdf.forge.signing_key_shard as forge_signing_module
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import TextBoxPlan
from ethernity.render.direct_pdf.forge.signing_key_shard import (
    build_forge_signing_key_shard_direct_plan,
    render_forge_signing_key_shard_direct_pdf,
)
from ethernity.render.direct_pdf.page_geometry import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    LETTER_HEIGHT_MM,
    LETTER_WIDTH_MM,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.doc_types import DOC_TYPE_SIGNING_KEY_SHARD
from ethernity.render.proofs import (
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_render_layout_proof,
    validate_text_in_pdf,
)
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


def _frame(*, data: bytes = b"signing-key-shard-payload") -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.KEY_DOCUMENT,
        doc_id=b"\xbb" * DOC_ID_LEN,
        index=0,
        total=1,
        data=data,
    )


def _inputs(
    output_path: Path,
    *,
    data: bytes = b"signing-key-shard-payload",
    paper_size: str = "A4",
    page_size: PaperSize | None = None,
) -> RenderInputs:
    frame = _frame(data=data)
    return RenderInputs(
        frames=(frame,),
        output_path=output_path,
        context={
            "paper_size": page_size.name if page_size is not None else paper_size,
            "doc_id": "bb" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
            "shard_index": 1,
            "shard_total": 3,
            "shard_threshold": 2,
        },
        doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
        design_name="forge",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=True,
        fallback_sections=(FallbackSection(label=None, frame=frame),),
        page_size=page_size,
    )


class TestDirectPdfForgeSigningKeyShard(unittest.TestCase):
    def test_labeled_payload_uses_the_static_extraction_heading_once(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "labeled-signing-key-shard.pdf")
            frame = inputs.frames[0]
            inputs = replace(
                inputs,
                fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
            )
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_signing_key_shard_direct_plan(surface, inputs)

            payload_labels = tuple(
                item
                for item in plan.page_plans[0].plans
                if any(line.text == "SHARD PAYLOAD" for line in getattr(item, "lines", ()))
            )
            self.assertEqual(len(payload_labels), 1)

    def test_build_plan_uses_signing_key_shard_layout_family(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "signing_key_shard.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_signing_key_shard_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 1)
            component_ids = plan.page_plans[0].proof.component_ids
            self.assertIn("forge-signing-key-shard-p1-payload-panel", component_ids)
            self.assertIn("forge-signing-key-shard-p1-reference-panel", component_ids)
            self.assertIn("forge-signing-key-shard-p1-specs-table", component_ids)
            self.assertNotIn("forge-shard-p1-qr-frame", component_ids)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertEqual(plan.artifact_proof.physical_qr_payload_indexes[0], 0)
            validate_render_artifact_proof(
                artifact_label="direct Forge signing-key shard document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Forge signing-key shard document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=plan.fallback_proof,
            )

    def test_render_writes_valid_pdf_with_fallback_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "signing_key_shard.pdf"
            inputs = _inputs(output_path)

            result = render_forge_signing_key_shard_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Forge signing-key shard document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_render_layout_proof(
                artifact_label="direct Forge signing-key shard document",
                layout_proof=result.layout_proof,
                expected_page_count=len(reader.pages),
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Forge signing-key shard document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Forge signing-key shard document",
                reader=reader,
                expected_text=("KEY MATERIAL PAYLOAD", "PUBLIC REFERENCE", "SPECIFICATIONS"),
            )

    def test_explicit_created_timestamp_produces_stable_pdf_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            first_path = Path(tmp) / "first.pdf"
            second_path = Path(tmp) / "second.pdf"

            render_forge_signing_key_shard_direct_pdf(_inputs(first_path))
            render_forge_signing_key_shard_direct_pdf(_inputs(second_path))

            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())

    def test_maximum_valid_payload_stays_on_one_page_with_one_qr(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "signing_key_shard.pdf"
            inputs = _inputs(output_path, data=b"x" * 2048)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_signing_key_shard_direct_plan(surface, inputs)
            result = render_forge_signing_key_shard_direct_pdf(inputs)
            reader = validate_pdf_has_pages(output_path)

            self.assertEqual(len(plan.page_plans), 1)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 1)
            self.assertEqual(plan.artifact_proof.physical_qr_payload_indexes, (0,))
            validate_render_layout_proof(
                artifact_label="single-page direct Forge signing-key shard document",
                layout_proof=result.layout_proof,
                expected_page_count=len(reader.pages),
            )
            validate_fallback_text_in_pdf(
                artifact_label="single-page direct Forge signing-key shard document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )

    def test_fallback_panel_spans_safe_width_and_stays_bottom_anchored(self) -> None:
        with TemporaryDirectory() as tmp:
            paper_sizes = (
                PaperSize("A4", "A4", A4_WIDTH_MM, A4_HEIGHT_MM),
                PaperSize("LETTER", "Letter", LETTER_WIDTH_MM, LETTER_HEIGHT_MM),
                PaperSize("FUTURE", "Future", 260.0, 360.0),
            )
            payloads = (
                ("normal", b"signing-key-shard-payload"),
                ("maximum", b"x" * 2048),
            )
            maximum_line_lengths: dict[str, int] = {}
            for paper in paper_sizes:
                for payload_name, data in payloads:
                    with self.subTest(paper_size=paper.name, payload=payload_name):
                        output_path = Path(tmp) / (
                            f"signing-key-shard-{paper.name.lower()}-{payload_name}.pdf"
                        )
                        inputs = _inputs(output_path, data=data, page_size=paper)
                        surface = FpdfSurface(
                            page_width_mm=paper.width_mm,
                            page_height_mm=paper.height_mm,
                        )
                        packaged_direct_pdf_assets().register_fonts(surface)

                        plan = build_forge_signing_key_shard_direct_plan(surface, inputs)
                        result = render_forge_signing_key_shard_direct_pdf(inputs)
                        reader = validate_pdf_has_pages(output_path)

                        self.assertEqual(len(plan.page_plans), 1)
                        self.assertEqual(len(reader.pages), 1)
                        self.assertEqual(plan.artifact_proof.physical_qr_count, 1)
                        self.assertEqual(plan.artifact_proof.physical_qr_payload_indexes, (0,))

                        page = plan.page_plans[0]
                        payload_panel = next(
                            item
                            for item in page.plans
                            if item.component_id.endswith("-payload-panel")
                        )
                        intact = next(
                            item
                            for item in page.plans
                            if item.component_id.endswith("-intact-notice")
                        )
                        self.assertAlmostEqual(payload_panel.proof.rect.x_mm, 15.0)
                        self.assertAlmostEqual(
                            payload_panel.proof.rect.width_mm,
                            paper.width_mm - 30.0,
                        )
                        self.assertAlmostEqual(
                            payload_panel.proof.rect.bottom_mm + 1.5,
                            intact.proof.rect.y_mm,
                        )
                        self.assertFalse(page.proof.overflow)
                        self.assertTrue(
                            all(item.satisfied for item in page.proof.separation_constraints)
                        )
                        text_plans = tuple(
                            item for item in page.plans if hasattr(item.proof, "font_size_pt")
                        )
                        self.assertGreaterEqual(
                            min(item.proof.font_size_pt for item in text_plans),
                            6.0,
                        )

                        fallback_lines = tuple(
                            item
                            for item in page.plans
                            if isinstance(item, TextBoxPlan)
                            and "-payload-line-" in item.component_id
                        )
                        self.assertTrue(fallback_lines)
                        column_xs = sorted(
                            {round(item.proof.rect.x_mm, 3) for item in fallback_lines}
                        )
                        self.assertIn(len(column_xs), (1, 2))
                        if payload_name == "normal":
                            self.assertEqual(len(column_xs), 1)
                        expected_column_width = (
                            payload_panel.proof.rect.width_mm - 8.0 - 4.0 * (len(column_xs) - 1)
                        ) / len(column_xs)
                        self.assertTrue(
                            all(
                                abs(item.proof.rect.width_mm - expected_column_width) <= 0.01
                                for item in fallback_lines
                            )
                        )
                        self.assertEqual(
                            column_xs[0],
                            round(payload_panel.proof.rect.x_mm + 4.0, 3),
                        )
                        if len(column_xs) == 2:
                            self.assertAlmostEqual(
                                column_xs[1],
                                column_xs[0] + expected_column_width + 4.0,
                                places=2,
                            )
                        if payload_name == "maximum":
                            maximum_line_lengths[paper.name] = max(
                                len(line.text) for item in fallback_lines for line in item.lines
                            )

                        validate_render_artifact_proof(
                            artifact_label="responsive direct Forge signing-key shard document",
                            inputs=inputs,
                            artifact_proof=result.artifact_proof,
                        )
                        validate_render_layout_proof(
                            artifact_label="responsive direct Forge signing-key shard document",
                            layout_proof=result.layout_proof,
                            expected_page_count=1,
                        )
                        validate_fallback_text_in_pdf(
                            artifact_label="responsive direct Forge signing-key shard document",
                            reader=reader,
                            fallback_sections=inputs.fallback_sections or (),
                            fallback_proof=result.fallback_proof,
                        )

            self.assertGreater(maximum_line_lengths["FUTURE"], maximum_line_lengths["A4"])

    def test_plan_anchors_body_to_actual_header_across_responsive_page_sizes(self) -> None:
        with TemporaryDirectory() as tmp:
            paper_sizes = (
                PaperSize("MINIMUM", "Minimum", 210.0, LETTER_HEIGHT_MM),
                PaperSize("A4", "A4", A4_WIDTH_MM, A4_HEIGHT_MM),
                PaperSize("LETTER", "Letter", LETTER_WIDTH_MM, LETTER_HEIGHT_MM),
                PaperSize("LEGAL", "Legal", LETTER_WIDTH_MM, 355.6),
                PaperSize("A3", "A3", 297.0, 420.0),
            )
            for paper in paper_sizes:
                with self.subTest(paper_size=paper.name):
                    inputs = _inputs(
                        Path(tmp) / f"signing-key-shard-{paper.name.lower()}.pdf",
                        data=b"x" * 2048,
                        page_size=paper,
                    )
                    surface = FpdfSurface(
                        page_width_mm=paper.width_mm,
                        page_height_mm=paper.height_mm,
                    )
                    packaged_direct_pdf_assets().register_fonts(surface)

                    plan = build_forge_signing_key_shard_direct_plan(surface, inputs)

                    self.assertEqual(len(plan.page_plans), 1)
                    for page in plan.page_plans:
                        self.assertAlmostEqual(page.rect.width_mm, paper.width_mm)
                        self.assertAlmostEqual(page.rect.height_mm, paper.height_mm)
                        self.assertTrue(
                            all(item.satisfied for item in page.proof.separation_constraints)
                        )
                        actual_header_constraint = next(
                            item
                            for item in page.proof.separation_constraints
                            if item.constraint_id.endswith("-warning-after-actual-header")
                        )
                        self.assertGreaterEqual(
                            actual_header_constraint.measured_clearance_mm,
                            3.0 - 0.01,
                        )

                        header_rule = next(
                            item
                            for item in page.plans
                            if item.component_id.endswith("-header-rule")
                        )
                        warning = next(
                            item
                            for item in page.plans
                            if item.component_id.endswith("-warning-panel-bg")
                        )
                        self.assertGreaterEqual(
                            warning.proof.rect.y_mm - header_rule.proof.rect.bottom_mm,
                            3.0 - 0.01,
                        )

                        qr_image = next(
                            item for item in page.plans if item.component_id.endswith("-qr-image")
                        )
                        self.assertAlmostEqual(qr_image.proof.rect.width_mm, 54.0)
                        self.assertAlmostEqual(qr_image.proof.rect.height_mm, 54.0)
                        payload_panel = next(
                            item
                            for item in page.plans
                            if item.component_id.endswith("-payload-panel")
                        )
                        self.assertGreaterEqual(payload_panel.proof.rect.height_mm, 106.0)

                        intact = next(
                            item
                            for item in page.plans
                            if item.component_id.endswith("-intact-notice")
                        )
                        footer = next(
                            item
                            for item in page.plans
                            if item.component_id.endswith("-footer-rule")
                        )
                        self.assertLessEqual(
                            intact.proof.rect.bottom_mm + 3.0,
                            footer.proof.rect.y_mm + 0.01,
                        )

    def test_dense_two_column_profile_is_a_real_capacity_rescue(self) -> None:
        surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
        packaged_direct_pdf_assets().register_fonts(surface)
        section = FallbackSection(
            label=None,
            frame=_frame(data=b"x" * 2048),
        )
        rescue_area = PdfRect(0.0, 0.0, 172.0, 88.0)

        _, entries, profile = forge_signing_module._fallback_layout_for_area(
            surface,
            (section,),
            area=rescue_area,
        )

        single_profile = forge_signing_module._fallback_layout_profiles()[0]
        _, single_entries = forge_signing_module._fallback_candidate_for_profile(
            surface,
            (section,),
            area=rescue_area,
            profile=single_profile,
        )
        self.assertGreater(
            len(single_entries),
            forge_signing_module._fallback_capacity(
                rescue_area,
                profile=single_profile,
            ),
        )
        self.assertEqual(profile.column_count, 2)
        self.assertEqual(profile.font_size_pt, 6.0)
        self.assertLess(profile.row_height_mm, single_profile.row_height_mm)
        self.assertLessEqual(
            len(entries),
            forge_signing_module._fallback_capacity(rescue_area, profile=profile),
        )

        with self.assertRaisesRegex(ValueError, "exceeds the single-page capacity"):
            forge_signing_module._fallback_layout_for_area(
                surface,
                (section,),
                area=PdfRect(0.0, 0.0, 172.0, 84.0),
            )


if __name__ == "__main__":
    unittest.main()
