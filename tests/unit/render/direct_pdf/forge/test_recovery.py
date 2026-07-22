import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import ethernity.render.direct_pdf.forge.recovery as forge_recovery_module
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render import render_frames_to_pdf
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.forge.recovery import (
    build_forge_recovery_direct_plan,
    render_forge_recovery_direct_pdf,
)
from ethernity.render.direct_pdf.page_geometry import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    LETTER_HEIGHT_MM,
    LETTER_WIDTH_MM,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.proofs import (
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_render_layout_proof,
    validate_text_in_pdf,
)
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage

_TWENTY_FOUR_WORD_PASSPHRASE = (
    "able acid also apex arch atom aunt away baby back bake bald "
    "ball band bank base bath bear beat been bell belt best beta"
)
_WORST_CASE_TWENTY_FOUR_WORD_PASSPHRASE = (
    "abstract accident acoustic announce attitude bachelor broccoli business category champion "
    "cinnamon congress convince cupboard daughter december distance document elephant envelope "
    "exercise festival frequent generate"
)
_RECOVERY_PASSPHRASES = (
    ("typical", _TWENTY_FOUR_WORD_PASSPHRASE),
    ("worst-case", _WORST_CASE_TWENTY_FOUR_WORD_PASSPHRASE),
)


def _frame(frame_type: FrameType, *, data: bytes, index: int = 0, total: int = 1) -> Frame:
    return Frame(
        version=VERSION,
        frame_type=frame_type,
        doc_id=b"\x77" * DOC_ID_LEN,
        index=index,
        total=total,
        data=data,
    )


def _inputs(
    output_path: Path,
    *,
    main_data: bytes = b"payload",
    paper_size: str = "A4",
    page_size: PaperSize | None = None,
) -> RenderInputs:
    auth_frame = _frame(FrameType.AUTH, data=b"auth-payload")
    main_frame = _frame(FrameType.MAIN_DOCUMENT, data=main_data)
    return RenderInputs(
        frames=(auth_frame, main_frame),
        output_path=output_path,
        context={
            "paper_size": page_size.name if page_size is not None else paper_size,
            "doc_id": "77" * DOC_ID_LEN,
            "created_timestamp_utc": "2026-07-06 12:00 UTC",
        },
        doc_type=DOC_TYPE_RECOVERY,
        design_name="forge",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=False,
        render_fallback=True,
        key_lines=("recovery-key-line",),
        recovery_meta=build_recovery_meta(
            passphrase="alpha bravo charlie delta echo foxtrot golf hotel",
            quorum_threshold=2,
            quorum_shares=3,
            signing_pub=b"\x12" * 32,
        ),
        fallback_sections=(
            FallbackSection(label="AUTH FRAME", frame=auth_frame),
            FallbackSection(label="MAIN FRAME", frame=main_frame),
        ),
        page_size=page_size,
    )


class TestDirectPdfForgeRecovery(unittest.TestCase):
    def test_build_plan_consumes_real_render_inputs_and_fallback_proof(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "recovery.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_recovery_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 2)
            self.assertFalse(plan.page_plans[0].proof.overflow)
            self.assertNotIn(
                "forge-recovery-p1-fallback-panel",
                plan.page_plans[0].proof.component_ids,
            )
            self.assertIn(
                "forge-recovery-p1-fallback-line-box-1",
                plan.page_plans[0].proof.component_ids,
            )
            validate_render_artifact_proof(
                artifact_label="direct Forge recovery document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )
            validate_fallback_render_proof(
                artifact_label="direct Forge recovery document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=plan.fallback_proof,
            )
            self.assertIn("AUTH FRAME", plan.fallback_proof.section_titles)

    def test_render_writes_valid_pdf_with_extractable_fallback_text(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery.pdf"
            inputs = _inputs(output_path)

            result = render_forge_recovery_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Forge recovery document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_render_layout_proof(
                artifact_label="direct Forge recovery document",
                layout_proof=result.layout_proof,
                expected_page_count=len(reader.pages),
            )
            validate_fallback_render_proof(
                artifact_label="direct Forge recovery document",
                frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                fallback_proof=result.fallback_proof,
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Forge recovery document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )

    def test_public_render_fits_24_word_passphrase_on_a4_and_letter(self) -> None:
        with TemporaryDirectory() as tmp:
            for phrase_name, phrase in _RECOVERY_PASSPHRASES:
                self.assertEqual(len(phrase.split()), 24)
                recovery_meta = build_recovery_meta(
                    passphrase=phrase,
                    quorum_threshold=None,
                    quorum_shares=None,
                    signing_pub=b"\x12" * 32,
                )
                for paper_size in ("A4", "LETTER"):
                    with self.subTest(phrase=phrase_name, paper_size=paper_size):
                        output_path = (
                            Path(tmp) / f"recovery-24-words-{phrase_name}-{paper_size.lower()}.pdf"
                        )
                        inputs = replace(
                            _inputs(output_path, paper_size=paper_size),
                            recovery_meta=recovery_meta,
                        )

                        result = render_frames_to_pdf(inputs)
                        reader = validate_pdf_has_pages(output_path)

                        validate_render_layout_proof(
                            artifact_label="public Forge 24-word recovery document",
                            layout_proof=result.layout_proof,
                            expected_page_count=len(reader.pages),
                        )
                        assert result.layout_proof is not None
                        self.assertTrue(
                            all(
                                constraint.satisfied
                                for page in result.layout_proof.pages
                                for constraint in page.separation_constraints
                            )
                        )
                        passphrase = next(
                            component
                            for component in result.layout_proof.pages[0].components
                            if component.component_id.endswith("-metadata-value-0")
                        )
                        self.assertEqual(passphrase.line_count, 4)
                        self.assertGreaterEqual(passphrase.font_size_pt or 0.0, 9.0)
                        validate_text_in_pdf(
                            artifact_label="public Forge 24-word recovery document",
                            reader=reader,
                            expected_text=recovery_meta.passphrase_lines,
                        )

    def test_build_plan_paginates_large_fallback_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery.pdf"
            inputs = _inputs(output_path, main_data=b"x" * 1000)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_recovery_direct_plan(surface, inputs)
            result = render_forge_recovery_direct_pdf(inputs)
            reader = validate_pdf_has_pages(output_path)

            self.assertGreater(len(plan.page_plans), 1)
            self.assertEqual(plan.artifact_proof.page_count, len(plan.page_plans))
            self.assertTrue(plan.fallback_proof.fully_consumed)
            self.assertEqual(max(map(len, plan.fallback_proof.emitted_fallback_lines)), 44)
            fallback_text_components = [
                item.proof
                for page in plan.page_plans
                for item in page.plans
                if "fallback-line-text" in item.component_id
            ]
            self.assertTrue(fallback_text_components)
            self.assertTrue(all(not component.overflow for component in fallback_text_components))
            self.assertGreaterEqual(
                min(component.font_size_pt or 0.0 for component in fallback_text_components),
                7.0,
            )
            for page in plan.page_plans:
                line_number_items = [
                    item for item in page.plans if "fallback-line-number" in item.component_id
                ]
                self.assertTrue(all(item.proof.font_size_pt >= 6.5 for item in line_number_items))
                labels = [
                    placement.text
                    for item in line_number_items
                    for placement in getattr(item, "lines", ())
                ]
                if labels:
                    self.assertEqual(labels[0], "01.")
                    self.assertTrue(all(len(label.removesuffix(".")) <= 4 for label in labels))
            validate_render_layout_proof(
                artifact_label="large direct Forge recovery document",
                layout_proof=result.layout_proof,
                expected_page_count=len(reader.pages),
            )
            validate_fallback_text_in_pdf(
                artifact_label="large direct Forge recovery document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )

    def test_custom_paginator_resets_display_numbers_per_page_and_section(self) -> None:
        entries = (
            forge_recovery_module._FallbackTitleEntry(section_index=0, title="AUTH FRAME"),
            *(
                forge_recovery_module._FallbackLineEntry(
                    section_index=0,
                    line_number=index,
                    text="yyyy",
                )
                for index in range(1, 71)
            ),
            forge_recovery_module._FallbackTitleEntry(section_index=1, title="MAIN FRAME"),
            *(
                forge_recovery_module._FallbackLineEntry(
                    section_index=1,
                    line_number=index,
                    text="yyyy",
                )
                for index in range(1, 8)
            ),
        )

        inputs = _inputs(Path("unused.pdf"))
        assert inputs.recovery_meta is not None
        surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
        packaged_direct_pdf_assets().register_fonts(surface)
        geometry = forge_recovery_module._forge_recovery_geometry(
            surface,
            inputs,
            inputs.recovery_meta,
        )
        pages = forge_recovery_module._paginate_fallback_entries(
            entries,
            geometry=geometry,
            first_page_single_section=False,
        )

        self.assertGreater(len(pages), 1)
        for page in pages:
            current_block: list[int] = []
            for page_entry in page.entries:
                if page_entry.display_line_number is None:
                    if current_block:
                        self.assertEqual(current_block, list(range(1, len(current_block) + 1)))
                        current_block = []
                    continue
                current_block.append(page_entry.display_line_number)
                self.assertLessEqual(len(str(page_entry.display_line_number)), 4)
            if current_block:
                self.assertEqual(current_block, list(range(1, len(current_block) + 1)))

    def test_letter_plan_reclaims_continuation_body_and_stays_above_footer(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery-letter.pdf"
            inputs = _inputs(output_path, main_data=b"x" * 1000, paper_size="LETTER")
            surface = FpdfSurface(
                page_width_mm=LETTER_WIDTH_MM,
                page_height_mm=LETTER_HEIGHT_MM,
            )
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_recovery_direct_plan(surface, inputs)
            result = render_forge_recovery_direct_pdf(inputs)

            self.assertGreater(len(plan.page_plans), 1)
            for page in plan.page_plans:
                self.assertAlmostEqual(page.rect.width_mm, LETTER_WIDTH_MM)
                self.assertAlmostEqual(page.rect.height_mm, LETTER_HEIGHT_MM)
                self.assertTrue(all(item.satisfied for item in page.proof.separation_constraints))
            continuation = plan.page_plans[1]
            intro = next(
                item
                for item in continuation.plans
                if item.component_id == "forge-recovery-p2-continuation-panel"
            )
            header_rule = next(
                item
                for item in continuation.plans
                if item.component_id == "forge-recovery-p2-header-rule"
            )
            fallback_boxes = tuple(
                item for item in continuation.plans if "-fallback-line-box-" in item.component_id
            )
            footer_rule = next(
                item
                for item in continuation.plans
                if item.component_id == "forge-recovery-p2-footer-rule"
            )
            self.assertTrue(fallback_boxes)
            self.assertLessEqual(
                header_rule.proof.rect.bottom_mm + 2.0,
                intro.proof.rect.y_mm,
            )
            self.assertLessEqual(
                intro.proof.rect.bottom_mm + 3.0,
                min(item.proof.rect.y_mm for item in fallback_boxes),
            )
            self.assertLessEqual(
                max(item.proof.rect.bottom_mm for item in fallback_boxes) + 3.0,
                footer_rule.proof.rect.y_mm,
            )
            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            width_mm = float(reader.pages[0].mediabox.width) * 25.4 / 72.0
            height_mm = float(reader.pages[0].mediabox.height) * 25.4 / 72.0
            self.assertAlmostEqual(width_mm, LETTER_WIDTH_MM, places=1)
            self.assertAlmostEqual(height_mm, LETTER_HEIGHT_MM, places=1)

    def test_first_page_warning_starts_after_measured_header(self) -> None:
        with TemporaryDirectory() as tmp:
            for paper_size, width_mm, height_mm in (
                ("A4", A4_WIDTH_MM, A4_HEIGHT_MM),
                ("LETTER", LETTER_WIDTH_MM, LETTER_HEIGHT_MM),
            ):
                with self.subTest(paper_size=paper_size):
                    inputs = _inputs(
                        Path(tmp) / f"recovery-{paper_size.lower()}.pdf",
                        paper_size=paper_size,
                    )
                    surface = FpdfSurface(page_width_mm=width_mm, page_height_mm=height_mm)
                    packaged_direct_pdf_assets().register_fonts(surface)

                    first_page = build_forge_recovery_direct_plan(surface, inputs).page_plans[0]
                    header_rule = next(
                        item
                        for item in first_page.plans
                        if item.component_id == "forge-recovery-p1-header-rule"
                    )
                    warning = next(
                        item
                        for item in first_page.plans
                        if item.component_id == "forge-recovery-p1-warning-panel"
                    )

                    self.assertLessEqual(
                        header_rule.proof.rect.bottom_mm + 2.0,
                        warning.proof.rect.y_mm,
                    )
                    header_clearance = next(
                        constraint
                        for constraint in first_page.proof.separation_constraints
                        if constraint.constraint_id == "forge-recovery-p1-content-after-header"
                    )
                    self.assertAlmostEqual(header_clearance.measured_clearance_mm, 2.0)

    def test_passphrase_continuation_starts_after_measured_header(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _inputs(Path(tmp) / "recovery-long-passphrase.pdf", paper_size="LETTER")
            inputs = replace(
                inputs,
                recovery_meta=build_recovery_meta(
                    passphrase=" ".join(f"word{index:04d}" for index in range(240)),
                    quorum_threshold=None,
                    quorum_shares=None,
                    signing_pub=b"\x12" * 32,
                ),
            )
            surface = FpdfSurface(
                page_width_mm=LETTER_WIDTH_MM,
                page_height_mm=LETTER_HEIGHT_MM,
            )
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_forge_recovery_direct_plan(surface, inputs)
            continuation_pages = tuple(
                page
                for page in plan.page_plans
                if any(
                    item.component_id.endswith("-passphrase-continuation-title")
                    for item in page.plans
                )
            )

            self.assertTrue(continuation_pages)
            for page in continuation_pages:
                header_rule = next(
                    item for item in page.plans if item.component_id.endswith("-header-rule")
                )
                title = next(
                    item
                    for item in page.plans
                    if item.component_id.endswith("-passphrase-continuation-title")
                )
                self.assertLessEqual(
                    header_rule.proof.rect.bottom_mm + 2.0,
                    title.proof.rect.y_mm,
                )

    def test_large_custom_pages_expand_line_number_gutter_for_three_digit_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            page_sizes = (PaperSize("TALL_RECOVERY", "Tall recovery", 220.0, 800.0),)
            for paper in page_sizes:
                with self.subTest(paper_size=paper.name):
                    inputs = _inputs(
                        Path(tmp) / f"recovery-{paper.name.lower()}.pdf",
                        main_data=b"x" * 4_000,
                        page_size=paper,
                    )
                    surface = FpdfSurface(
                        page_width_mm=paper.width_mm,
                        page_height_mm=paper.height_mm,
                    )
                    packaged_direct_pdf_assets().register_fonts(surface)

                    plan = build_forge_recovery_direct_plan(surface, inputs)

                    line_numbers = tuple(
                        item
                        for page in plan.page_plans
                        for item in page.plans
                        if "fallback-line-number" in item.component_id
                    )
                    self.assertTrue(line_numbers)
                    self.assertTrue(all(not item.proof.overflow for item in line_numbers))
                    self.assertGreaterEqual(
                        min(item.proof.font_size_pt for item in line_numbers),
                        6.5,
                    )
                    maximum_display_number = max(
                        int(placement.text.removesuffix("."))
                        for item in line_numbers
                        for placement in getattr(item, "lines", ())
                    )
                    self.assertGreaterEqual(maximum_display_number, 100)
                    three_digit_numbers = tuple(
                        item
                        for item in line_numbers
                        if any(
                            len(placement.text.removesuffix(".")) >= 3
                            for placement in getattr(item, "lines", ())
                        )
                    )
                    self.assertTrue(three_digit_numbers)
                    self.assertTrue(
                        all(item.proof.rect.width_mm > 8.5 for item in three_digit_numbers)
                    )
                    self.assertTrue(
                        all(
                            constraint.satisfied
                            for page in plan.page_plans
                            for constraint in page.proof.separation_constraints
                        )
                    )

    def test_fallback_capacity_uses_measured_width_and_full_continuation_height(self) -> None:
        with TemporaryDirectory() as tmp:
            papers = (
                PaperSize("A4", "A4", A4_WIDTH_MM, A4_HEIGHT_MM),
                PaperSize("LETTER", "Letter", LETTER_WIDTH_MM, LETTER_HEIGHT_MM),
                PaperSize("FUTURE", "Future", 260.0, 360.0),
            )
            metrics: dict[str, tuple[int, int]] = {}
            for paper in papers:
                with self.subTest(paper_size=paper.name):
                    inputs = _inputs(
                        Path(tmp) / f"recovery-capacity-{paper.name.lower()}.pdf",
                        main_data=b"x" * 2_048,
                        page_size=paper,
                    )
                    surface = FpdfSurface(
                        page_width_mm=paper.width_mm,
                        page_height_mm=paper.height_mm,
                    )
                    packaged_direct_pdf_assets().register_fonts(surface)
                    assert inputs.recovery_meta is not None
                    geometry = forge_recovery_module._forge_recovery_geometry(
                        surface,
                        inputs,
                        inputs.recovery_meta,
                    )
                    _, fallback_pages = forge_recovery_module._responsive_fallback_layout(
                        surface,
                        inputs.fallback_sections or (),
                        geometry=geometry,
                        first_page_single_section=True,
                    )
                    measured_line_length = forge_recovery_module._fallback_line_length_for_geometry(
                        surface,
                        geometry=geometry,
                        first_maximum_display_number=(
                            forge_recovery_module._maximum_fallback_display_number(
                                fallback_pages[:1]
                            )
                        ),
                        continuation_maximum_display_number=(
                            forge_recovery_module._maximum_fallback_display_number(
                                fallback_pages[1:]
                            )
                        ),
                    )
                    plan = build_forge_recovery_direct_plan(surface, inputs)
                    result = render_forge_recovery_direct_pdf(inputs)
                    reader = validate_pdf_has_pages(inputs.output_path)

                    self.assertEqual(
                        max(map(len, plan.fallback_proof.emitted_fallback_lines)),
                        measured_line_length,
                    )
                    self.assertEqual(len(reader.pages), len(fallback_pages))
                    validate_fallback_text_in_pdf(
                        artifact_label=f"{paper.name} Forge recovery document",
                        reader=reader,
                        fallback_sections=inputs.fallback_sections or (),
                        fallback_proof=result.fallback_proof,
                    )
                    full_lines = tuple(
                        item
                        for page in plan.page_plans
                        for item in page.plans
                        if "fallback-line-text" in item.component_id
                        and any(
                            len(placement.text) == measured_line_length
                            for placement in getattr(item, "lines", ())
                        )
                    )
                    self.assertTrue(full_lines)
                    self.assertGreaterEqual(
                        min(
                            item.proof.used_rect.width_mm / item.proof.rect.width_mm
                            for item in full_lines
                        ),
                        0.95,
                    )
                    for fallback_page in fallback_pages[1:-1]:
                        self.assertEqual(
                            max(entry.row_index for entry in fallback_page.entries),
                            fallback_page.rows_per_column - 1,
                        )
                    metrics[paper.name] = (measured_line_length, len(fallback_pages))

            self.assertGreaterEqual(metrics["LETTER"][0], metrics["A4"][0])
            self.assertGreater(metrics["FUTURE"][0], metrics["LETTER"][0])
            self.assertEqual(metrics["A4"][1], 3)
            self.assertEqual(metrics["LETTER"][1], 3)
            self.assertEqual(metrics["FUTURE"][1], 2)

    def test_narrow_tall_pages_reflow_payload_after_three_digit_gutter(self) -> None:
        with TemporaryDirectory() as tmp:
            page_sizes = (
                PaperSize("NARROW_TALL", "Narrow tall", 210.0, 450.0),
                PaperSize("NARROW_EXTREME", "Narrow extreme", 210.0, 3_000.0),
            )
            for paper in page_sizes:
                with self.subTest(paper_size=paper.name):
                    inputs = _inputs(
                        Path(tmp) / f"recovery-{paper.name.lower()}.pdf",
                        main_data=b"x" * 4_000,
                        page_size=paper,
                    )
                    surface = FpdfSurface(
                        page_width_mm=paper.width_mm,
                        page_height_mm=paper.height_mm,
                    )
                    packaged_direct_pdf_assets().register_fonts(surface)

                    plan = build_forge_recovery_direct_plan(surface, inputs)

                    payload_text = tuple(
                        item
                        for page in plan.page_plans
                        for item in page.plans
                        if "fallback-line-text" in item.component_id
                    )
                    line_numbers = tuple(
                        item
                        for page in plan.page_plans
                        for item in page.plans
                        if "fallback-line-number" in item.component_id
                    )
                    self.assertTrue(payload_text)
                    self.assertTrue(line_numbers)
                    self.assertTrue(all(not item.proof.overflow for item in payload_text))
                    self.assertGreaterEqual(
                        min(item.proof.font_size_pt for item in payload_text),
                        7.0,
                    )
                    self.assertGreaterEqual(
                        max(
                            int(placement.text.removesuffix("."))
                            for item in line_numbers
                            for placement in getattr(item, "lines", ())
                        ),
                        100,
                    )
                    self.assertLess(
                        max(map(len, plan.fallback_proof.emitted_fallback_lines)),
                        44,
                    )
                    self.assertTrue(
                        all(
                            constraint.satisfied
                            for page in plan.page_plans
                            for constraint in page.proof.separation_constraints
                        )
                    )
                    validate_fallback_render_proof(
                        artifact_label="narrow tall Forge recovery document",
                        frames=tuple(section.frame for section in inputs.fallback_sections or ()),
                        fallback_proof=plan.fallback_proof,
                    )

    def test_sparse_very_tall_page_uses_actual_gutter_instead_of_unused_capacity(self) -> None:
        with TemporaryDirectory() as tmp:
            paper = PaperSize("SPARSE_TALL", "Sparse tall", 210.0, 3_000.0)
            inputs = _inputs(
                Path(tmp) / "recovery-sparse-tall.pdf",
                main_data=b"short payload",
                page_size=paper,
            )
            surface = FpdfSurface(
                page_width_mm=paper.width_mm,
                page_height_mm=paper.height_mm,
            )
            packaged_direct_pdf_assets().register_fonts(surface)
            assert inputs.recovery_meta is not None
            geometry = forge_recovery_module._forge_recovery_geometry(
                surface,
                inputs,
                inputs.recovery_meta,
            )

            _, pages = forge_recovery_module._responsive_fallback_layout(
                surface,
                inputs.fallback_sections or (),
                geometry=geometry,
                first_page_single_section=True,
            )
            actual_first_maximum = forge_recovery_module._maximum_fallback_display_number(pages[:1])
            actual_continuation_maximum = forge_recovery_module._maximum_fallback_display_number(
                pages[1:]
            )
            settled_line_length = forge_recovery_module._fallback_line_length_for_geometry(
                surface,
                geometry=geometry,
                first_maximum_display_number=actual_first_maximum,
                continuation_maximum_display_number=actual_continuation_maximum,
            )
            minimum_gutter_line_length = forge_recovery_module._fallback_line_length_for_geometry(
                surface,
                geometry=geometry,
                first_maximum_display_number=0,
                continuation_maximum_display_number=0,
            )
            capacity_reserved_line_length = (
                forge_recovery_module._fallback_line_length_for_geometry(
                    surface,
                    geometry=geometry,
                    first_maximum_display_number=(
                        2
                        * forge_recovery_module._fallback_rows_per_column(
                            geometry.first_page_fallback_area
                        )
                    ),
                    continuation_maximum_display_number=(
                        2
                        * forge_recovery_module._fallback_rows_per_column(
                            geometry.continuation_fallback_area
                        )
                    ),
                )
            )
            plan = build_forge_recovery_direct_plan(surface, inputs)
            payload_text = tuple(
                item
                for page in plan.page_plans
                for item in page.plans
                if "fallback-line-text" in item.component_id
            )

            self.assertLess(max(actual_first_maximum, actual_continuation_maximum), 100)
            self.assertEqual(settled_line_length, minimum_gutter_line_length)
            self.assertGreater(settled_line_length, capacity_reserved_line_length)
            self.assertTrue(payload_text)
            self.assertTrue(all(not item.proof.overflow for item in payload_text))
            self.assertGreaterEqual(
                min(item.proof.font_size_pt for item in payload_text),
                forge_recovery_module._FALLBACK_PAYLOAD_MIN_FIT_SIZE_PT,
            )

    def test_full_tall_page_reflows_for_actual_three_digit_gutter(self) -> None:
        with TemporaryDirectory() as tmp:
            paper = PaperSize("DENSE_TALL", "Dense tall", 210.0, 800.0)
            inputs = _inputs(
                Path(tmp) / "recovery-dense-tall.pdf",
                main_data=b"x" * 6_000,
                page_size=paper,
            )
            surface = FpdfSurface(
                page_width_mm=paper.width_mm,
                page_height_mm=paper.height_mm,
            )
            packaged_direct_pdf_assets().register_fonts(surface)
            assert inputs.recovery_meta is not None
            geometry = forge_recovery_module._forge_recovery_geometry(
                surface,
                inputs,
                inputs.recovery_meta,
            )

            resolved_sections, pages = forge_recovery_module._responsive_fallback_layout(
                surface,
                inputs.fallback_sections or (),
                geometry=geometry,
                first_page_single_section=True,
            )
            actual_first_maximum = forge_recovery_module._maximum_fallback_display_number(pages[:1])
            actual_continuation_maximum = forge_recovery_module._maximum_fallback_display_number(
                pages[1:]
            )
            initial_line_length = forge_recovery_module._fallback_line_length_for_geometry(
                surface,
                geometry=geometry,
                first_maximum_display_number=0,
                continuation_maximum_display_number=0,
            )
            settled_line_length = forge_recovery_module._fallback_line_length_for_geometry(
                surface,
                geometry=geometry,
                first_maximum_display_number=actual_first_maximum,
                continuation_maximum_display_number=actual_continuation_maximum,
            )
            full_continuation_pages = tuple(
                page
                for page in pages[1:]
                if max(entry.row_index for entry in page.entries) == page.rows_per_column - 1
            )
            plan = build_forge_recovery_direct_plan(surface, inputs)
            payload_text = tuple(
                item
                for page in plan.page_plans
                for item in page.plans
                if "fallback-line-text" in item.component_id
            )

            self.assertGreaterEqual(actual_continuation_maximum, 100)
            self.assertLess(settled_line_length, initial_line_length)
            self.assertEqual(
                max(len(line) for section in resolved_sections for line in section.lines),
                settled_line_length,
            )
            self.assertTrue(full_continuation_pages)
            self.assertTrue(
                any(
                    forge_recovery_module._maximum_fallback_display_number((page,)) >= 100
                    for page in full_continuation_pages
                )
            )
            self.assertTrue(payload_text)
            self.assertTrue(all(not item.proof.overflow for item in payload_text))
            self.assertGreaterEqual(
                min(item.proof.font_size_pt for item in payload_text),
                forge_recovery_module._FALLBACK_PAYLOAD_MIN_FIT_SIZE_PT,
            )


if __name__ == "__main__":
    unittest.main()
