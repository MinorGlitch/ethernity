import unittest
from dataclasses import replace
from math import floor
from pathlib import Path
from tempfile import TemporaryDirectory

import ethernity.render.direct_pdf.sentinel.recovery as sentinel_recovery_module
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize, resolve_paper_size
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.page_geometry import A4_HEIGHT_MM, A4_WIDTH_MM
from ethernity.render.direct_pdf.sentinel.common import (
    build_sentinel_page_layout,
    build_sentinel_surface,
)
from ethernity.render.direct_pdf.sentinel.recovery import (
    build_sentinel_recovery_direct_plan,
    render_sentinel_recovery_direct_pdf,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.proofs import (
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
)
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


def _frame(frame_type: FrameType, *, data: bytes, index: int = 0, total: int = 1) -> Frame:
    return Frame(
        version=VERSION,
        frame_type=frame_type,
        doc_id=b"\x66" * DOC_ID_LEN,
        index=index,
        total=total,
        data=data,
    )


def _inputs(output_path: Path, *, main_data: bytes = b"payload") -> RenderInputs:
    auth_frame = _frame(FrameType.AUTH, data=b"auth-payload")
    main_frame = _frame(FrameType.MAIN_DOCUMENT, data=main_data)
    return RenderInputs(
        frames=(auth_frame, main_frame),
        output_path=output_path,
        context={
            "paper_size": "A4",
            "doc_id": "66" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
        },
        doc_type=DOC_TYPE_RECOVERY,
        design_name="sentinel",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=False,
        render_fallback=True,
        recovery_meta=build_recovery_meta(
            passphrase="alpha bravo charlie delta echo foxtrot",
            quorum_threshold=2,
            quorum_shares=3,
            signing_pub=b"\x31" * 32,
        ),
        fallback_sections=(
            FallbackSection(label="AUTH FRAME", frame=auth_frame),
            FallbackSection(label="MAIN FRAME", frame=main_frame),
        ),
    )


def _with_paper(
    inputs: RenderInputs,
    paper_size: str,
    dimensions_mm: tuple[float, float] | None = None,
) -> RenderInputs:
    context = dict(inputs.context)
    context["paper_size"] = paper_size
    if dimensions_mm is None:
        return replace(inputs, context=context, page_size=resolve_paper_size(paper_size))
    width_mm, height_mm = dimensions_mm
    return replace(
        inputs,
        context=context,
        page_size=PaperSize(
            name=paper_size,
            display_name=paper_size.replace("_", " ").title(),
            width_mm=width_mm,
            height_mm=height_mm,
        ),
    )


class TestDirectPdfSentinelRecovery(unittest.TestCase):
    def test_build_plan_uses_sentinel_shell_and_fallback_table(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "recovery.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_recovery_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 1)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertIn("sentinel-recovery-p1-top-strip", plan.page_plans[0].proof.component_ids)
            self.assertIn(
                "sentinel-recovery-p1-session-panel",
                plan.page_plans[0].proof.component_ids,
            )
            self.assertIn(
                "sentinel-recovery-p1-fallback-table",
                plan.page_plans[0].proof.component_ids,
            )
            self.assertIn(
                "sentinel-recovery-p1-metadata-box-0",
                plan.page_plans[0].proof.component_ids,
            )
            validate_render_artifact_proof(
                artifact_label="direct Sentinel recovery document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Sentinel recovery document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=plan.fallback_proof,
            )

    def test_render_writes_valid_pdf_with_extractable_fallback_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery.pdf"
            inputs = _inputs(output_path)

            result = render_sentinel_recovery_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Sentinel recovery document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Sentinel recovery document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=result.fallback_proof,
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Sentinel recovery document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )

    def test_build_plan_paginates_large_fallback_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "recovery.pdf", main_data=b"x" * 2200)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_sentinel_recovery_direct_plan(surface, inputs)

            self.assertGreater(len(plan.page_plans), 1)
            self.assertEqual(plan.artifact_proof.page_count, len(plan.page_plans))
            self.assertTrue(plan.fallback_proof.fully_consumed)
            for page in plan.page_plans:
                labels = [
                    placement.text
                    for item in page.plans
                    if "fallback-line-number" in item.component_id
                    for placement in getattr(item, "lines", ())
                ]
                if labels:
                    self.assertEqual(labels[0], "01.")
                    self.assertTrue(all(len(label.removesuffix(".")) <= 4 for label in labels))

    def test_fallback_capacity_uses_measured_width_and_physical_page_height(self) -> None:
        paper_cases = (
            ("A4", None),
            ("LETTER", None),
            ("FUTURE_PORTRAIT", (260.0, 360.0)),
            ("FUTURE_TALL", (260.0, 450.0)),
        )
        page_counts: dict[str, int] = {}
        continuation_capacities: dict[str, int] = {}

        with TemporaryDirectory() as tmp:
            for paper_name, dimensions_mm in paper_cases:
                with self.subTest(paper_name=paper_name):
                    inputs = _with_paper(
                        _inputs(Path(tmp) / f"{paper_name.lower()}.pdf", main_data=b"x" * 8000),
                        paper_name,
                        dimensions_mm,
                    )
                    surface = build_sentinel_surface(inputs)
                    packaged_direct_pdf_assets().register_fonts(surface)
                    plan = build_sentinel_recovery_direct_plan(surface, inputs)
                    page_layout = build_sentinel_page_layout(inputs)
                    mapped_area = page_layout.map_rect(
                        sentinel_recovery_module._CONTINUATION_FALLBACK_AREA
                    )
                    expected_capacity = floor(
                        mapped_area.height_mm
                        / sentinel_recovery_module._FALLBACK_MINIMUM_ROW_HEIGHT_MM
                    )

                    self.assertGreater(len(plan.page_plans), 1)
                    self.assertTrue(all(not page.proof.overflow for page in plan.page_plans))
                    page_counts[paper_name] = len(plan.page_plans)
                    continuation_capacities[paper_name] = expected_capacity

                    page_line_lengths: list[int] = []
                    for page in plan.page_plans:
                        expected_body_size_pt = (
                            sentinel_recovery_module._FIRST_FALLBACK_BODY_SIZE_PT
                            if page.page_number == 1
                            else sentinel_recovery_module._CONTINUATION_FALLBACK_BODY_SIZE_PT
                        )
                        payload_plans = tuple(
                            item
                            for item in page.plans
                            if "fallback-line-text" in item.component_id and item.lines
                        )
                        longest_line_length = max(len(item.lines[0].text) for item in payload_plans)
                        page_line_lengths.append(longest_line_length)
                        self.assertGreater(longest_line_length, 59)
                        for item in payload_plans:
                            if len(item.lines[0].text) == longest_line_length:
                                self.assertGreaterEqual(
                                    item.lines[0].width_mm / item.rect.width_mm,
                                    0.9,
                                )
                                self.assertAlmostEqual(
                                    item.proof.font_size_pt,
                                    expected_body_size_pt,
                                )
                    self.assertGreater(page_line_lengths[1], page_line_lengths[0])

                    continuation_page = plan.page_plans[1]
                    row_boxes = tuple(
                        item
                        for item in continuation_page.plans
                        if "fallback-line-box" in item.component_id
                    )
                    self.assertEqual(len(row_boxes), expected_capacity)
                    self.assertAlmostEqual(
                        row_boxes[-1].rect.bottom_mm,
                        mapped_area.bottom_mm,
                        places=2,
                    )
                    footer_rule = next(
                        item
                        for item in continuation_page.plans
                        if item.component_id.endswith("footer-rule")
                    )
                    continuation_table = next(
                        item
                        for item in continuation_page.plans
                        if item.component_id.endswith("continuation-table")
                    )
                    self.assertLessEqual(
                        continuation_table.rect.bottom_mm + 1.0,
                        footer_rule.rect.y_mm,
                    )

        self.assertGreater(
            continuation_capacities["FUTURE_PORTRAIT"],
            continuation_capacities["A4"],
        )
        self.assertGreater(
            continuation_capacities["FUTURE_TALL"],
            continuation_capacities["FUTURE_PORTRAIT"],
        )
        self.assertLess(page_counts["FUTURE_PORTRAIT"], page_counts["A4"])
        self.assertLessEqual(page_counts["FUTURE_TALL"], page_counts["FUTURE_PORTRAIT"])

    def test_responsive_fallback_remains_extractable_on_every_supported_geometry(self) -> None:
        paper_cases = (
            ("A4", None),
            ("LETTER", None),
            ("FUTURE_PORTRAIT", (260.0, 360.0)),
            ("FUTURE_TALL", (260.0, 450.0)),
        )
        with TemporaryDirectory() as tmp:
            for paper_name, dimensions_mm in paper_cases:
                with self.subTest(paper_name=paper_name):
                    output_path = Path(tmp) / f"extract-{paper_name.lower()}.pdf"
                    inputs = _with_paper(
                        _inputs(output_path, main_data=b"x" * 2200),
                        paper_name,
                        dimensions_mm,
                    )

                    result = render_sentinel_recovery_direct_pdf(inputs)

                    reader = validate_pdf_has_pages(output_path)
                    self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
                    self.assertTrue(result.fallback_proof.fully_consumed)
                    assert result.layout_proof is not None
                    self.assertTrue(all(not page.overflow for page in result.layout_proof.pages))
                    validate_fallback_text_in_pdf(
                        artifact_label="direct Sentinel responsive recovery document",
                        reader=reader,
                        fallback_sections=inputs.fallback_sections or (),
                        fallback_proof=result.fallback_proof,
                    )


if __name__ == "__main__":
    unittest.main()
