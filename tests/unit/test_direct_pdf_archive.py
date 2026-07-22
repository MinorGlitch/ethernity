import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render import render_frames_to_pdf
from ethernity.render.direct_pdf.archive import (
    build_archive_kit_direct_plan,
    build_archive_main_direct_plan,
    build_archive_recovery_direct_plan,
    build_archive_shard_direct_plan,
    build_archive_signing_key_shard_direct_plan,
    render_archive_kit_direct_pdf,
    render_archive_main_direct_pdf,
    render_archive_recovery_direct_pdf,
    render_archive_shard_direct_pdf,
    render_archive_signing_key_shard_direct_pdf,
)
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.page_geometry import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    LETTER_HEIGHT_MM,
    LETTER_WIDTH_MM,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.proofs import (
    extract_pdf_text,
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

_PAPER_DIMENSIONS = {
    "A4": (A4_WIDTH_MM, A4_HEIGHT_MM),
    "LETTER": (LETTER_WIDTH_MM, LETTER_HEIGHT_MM),
}


def _frames(frame_type: FrameType, count: int, *, label: str) -> tuple[Frame, ...]:
    return tuple(
        Frame(
            version=VERSION,
            frame_type=frame_type,
            doc_id=b"\x88" * DOC_ID_LEN,
            index=index,
            total=count,
            data=f"{label}-{index}".encode("ascii"),
        )
        for index in range(count)
    )


def _base_context(*, paper_size: str = "A4") -> dict[str, object]:
    return {
        "paper_size": paper_size,
        "doc_id": "88" * DOC_ID_LEN,
        "created_timestamp_utc": "2026-07-06 12:00 UTC",
    }


def _main_inputs(
    output_path: Path,
    *,
    count: int = 4,
    paper_size: str = "A4",
) -> RenderInputs:
    frames = _frames(FrameType.MAIN_DOCUMENT, count, label="archive-main")
    return RenderInputs(
        frames=frames,
        output_path=output_path,
        context=_base_context(paper_size=paper_size),
        doc_type=DOC_TYPE_MAIN,
        design_name="archive",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=False,
    )


def _recovery_inputs(
    output_path: Path,
    *,
    paper_size: str = "A4",
    auth_size: int | None = None,
    main_size: int | None = None,
) -> RenderInputs:
    auth_frame = _frames(FrameType.AUTH, 1, label="archive-auth")[0]
    main_frame = _frames(FrameType.MAIN_DOCUMENT, 1, label="archive-recovery-main")[0]
    if auth_size is not None:
        auth_frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=auth_frame.doc_id,
            index=0,
            total=1,
            data=b"a" * auth_size,
        )
    if main_size is not None:
        main_frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=main_frame.doc_id,
            index=0,
            total=1,
            data=b"m" * main_size,
        )
    return RenderInputs(
        frames=(auth_frame, main_frame),
        output_path=output_path,
        context=_base_context(paper_size=paper_size),
        doc_type=DOC_TYPE_RECOVERY,
        design_name="archive",
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


def _shard_inputs(
    output_path: Path,
    *,
    doc_type: str = DOC_TYPE_SHARD,
    paper_size: str = "A4",
    data_size: int | None = None,
) -> RenderInputs:
    frame = _frames(FrameType.KEY_DOCUMENT, 1, label=f"archive-{doc_type}")[0]
    if data_size is not None:
        frame = replace(frame, data=b"s" * data_size)
    context = _base_context(paper_size=paper_size)
    context.update({"shard_index": 1, "shard_total": 3, "shard_threshold": 2})
    return RenderInputs(
        frames=(frame,),
        output_path=output_path,
        context=context,
        doc_type=doc_type,
        design_name="archive",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=True,
        fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
    )


def _kit_inputs(
    output_path: Path,
    *,
    count: int = 3,
    paper_size: str = "A4",
) -> RenderInputs:
    frames = _frames(FrameType.MAIN_DOCUMENT, count, label="archive-kit")
    return RenderInputs(
        frames=frames,
        output_path=output_path,
        context=_base_context(paper_size=paper_size),
        doc_type=DOC_TYPE_KIT,
        design_name="archive",
        lineage=RenderLineage(kind="recovery_kit"),
        qr_payloads=tuple(f"kit-chunk-{index}" for index in range(count)),
        render_qr=True,
        render_fallback=False,
    )


class TestDirectPdfArchive(unittest.TestCase):
    def test_build_main_plan_places_qr_grid(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _main_inputs(Path(tmp) / "main.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_archive_main_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 1)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 4)
            first_card = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "archive-main-p1-qr-card-0"
            )
            self.assertGreater(first_card.proof.rect.width_mm, 55.0)
            validate_render_artifact_proof(
                artifact_label="direct Archive main document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )

    def test_build_main_plan_spreads_nine_qrs_then_fits_twelve_on_continuation(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _main_inputs(Path(tmp) / "main.pdf", count=21)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_archive_main_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 2)
            first_page, continuation_page = plan.page_plans
            first_cards = [item for item in first_page.plans if "-qr-card-" in item.component_id]
            continuation_cards = [
                item for item in continuation_page.plans if "-qr-card-" in item.component_id
            ]
            self.assertEqual(len(first_cards), 9)
            self.assertEqual(len(continuation_cards), 12)

            first_x_positions = sorted({item.proof.rect.x_mm for item in first_cards})
            first_y_positions = sorted({item.proof.rect.y_mm for item in first_cards})
            self.assertEqual(len(first_x_positions), 3)
            self.assertEqual(len(first_y_positions), 3)
            horizontal_gaps = [
                right - (left + first_cards[0].proof.rect.width_mm)
                for left, right in zip(first_x_positions, first_x_positions[1:])
            ]
            vertical_gaps = [
                lower - (upper + first_cards[0].proof.rect.height_mm)
                for upper, lower in zip(first_y_positions, first_y_positions[1:])
            ]
            self.assertAlmostEqual(horizontal_gaps[0], horizontal_gaps[1])
            self.assertAlmostEqual(vertical_gaps[0], vertical_gaps[1])
            self.assertGreater(vertical_gaps[0], 3.2)

            continuation_rows = {item.proof.rect.y_mm for item in continuation_cards}
            continuation_footer = next(
                item
                for item in continuation_page.plans
                if item.component_id == "archive-main-p2-footer-rule"
            )
            self.assertEqual(len(continuation_rows), 4)
            self.assertLessEqual(
                max(item.proof.rect.bottom_mm for item in continuation_cards),
                continuation_footer.proof.rect.y_mm,
            )

    def test_render_main_writes_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "main.pdf"
            inputs = _main_inputs(output_path)

            result = render_archive_main_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Archive main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Archive main document",
                reader=reader,
                expected_text=("MAIN DOCUMENT", "MODE", "SEGMENT 01"),
            )

    def test_main_plan_and_render_are_responsive_to_letter(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "main-letter.pdf"
            inputs = _main_inputs(output_path, count=21, paper_size="LETTER")
            surface = FpdfSurface(page_width_mm=215.9, page_height_mm=279.4)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_archive_main_direct_plan(surface, inputs)
            result = render_archive_main_direct_pdf(inputs)

            self.assertEqual(len(plan.page_plans), 2)
            first_page, continuation_page = plan.page_plans
            first_cards = [item for item in first_page.plans if "-qr-card-" in item.component_id]
            continuation_cards = [
                item for item in continuation_page.plans if "-qr-card-" in item.component_id
            ]
            footer_rule = next(
                item
                for item in continuation_page.plans
                if item.component_id == "archive-main-p2-footer-rule"
            )
            first_y_positions = sorted({item.proof.rect.y_mm for item in first_cards})
            first_vertical_gaps = [
                lower - (upper + first_cards[0].proof.rect.height_mm)
                for upper, lower in zip(first_y_positions, first_y_positions[1:])
            ]
            self.assertEqual(len(first_cards), 9)
            self.assertAlmostEqual(first_vertical_gaps[0], first_vertical_gaps[1])
            self.assertEqual(len(continuation_cards), 12)
            self.assertAlmostEqual(continuation_page.rect.width_mm, 215.9)
            self.assertAlmostEqual(continuation_page.rect.height_mm, 279.4)
            self.assertLessEqual(
                max(item.proof.rect.bottom_mm for item in continuation_cards),
                footer_rule.proof.rect.y_mm,
            )

            reader = validate_pdf_has_pages(output_path)
            width_mm = float(reader.pages[0].mediabox.width) * 25.4 / 72.0
            height_mm = float(reader.pages[0].mediabox.height) * 25.4 / 72.0
            self.assertAlmostEqual(width_mm, 215.9, places=1)
            self.assertAlmostEqual(height_mm, 279.4, places=1)
            self.assertFalse(result.layout_proof.overflow)

    def test_render_recovery_writes_valid_fallback_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery.pdf"
            inputs = _recovery_inputs(output_path)

            result = render_archive_recovery_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            self.assertIsNotNone(result.fallback_proof)
            validate_render_artifact_proof(
                artifact_label="direct Archive recovery document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Archive recovery document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Archive recovery document",
                reader=reader,
                expected_text=("RECOVERY DOCUMENT", "FALLBACK BLOCKS", "AUTH FRAME"),
            )

    def test_recovery_fallback_uses_measured_width_and_available_rows(self) -> None:
        page_sizes = (
            (PaperSize("A4", "A4", 210.0, 297.0), 6),
            (PaperSize("LETTER", "Letter", 215.9, 279.4), 6),
            (PaperSize("FUTURE-RECOVERY", "Future recovery", 260.0, 360.0), 3),
        )
        longest_rows: dict[str, int] = {}
        with TemporaryDirectory() as tmp:
            for page_size, maximum_pages in page_sizes:
                with self.subTest(page_size=page_size.name):
                    base_inputs = _recovery_inputs(
                        Path(tmp) / f"recovery-capacity-{page_size.name}.pdf",
                        auth_size=512,
                        main_size=12_000,
                    )
                    inputs = replace(
                        base_inputs,
                        context={**base_inputs.context, "paper_size": page_size.name},
                        page_size=page_size,
                    )
                    surface = FpdfSurface(
                        page_width_mm=page_size.width_mm,
                        page_height_mm=page_size.height_mm,
                    )
                    packaged_direct_pdf_assets().register_fonts(surface)

                    plan = build_archive_recovery_direct_plan(surface, inputs)

                    self.assertLessEqual(len(plan.page_plans), maximum_pages)
                    lines = [
                        item
                        for page_plan in plan.page_plans
                        for item in page_plan.plans
                        if "-fallback-line-" in item.component_id
                    ]
                    longest_row = max(len(item.lines[0].text) for item in lines)
                    longest_rows[page_size.name] = longest_row
                    full_rows = [item for item in lines if len(item.lines[0].text) == longest_row]
                    self.assertGreaterEqual(
                        min(
                            item.proof.used_rect.width_mm / item.proof.rect.width_mm
                            for item in full_rows
                        ),
                        0.95,
                    )
                    for page_plan in plan.page_plans[:-1]:
                        panel = next(
                            item
                            for item in page_plan.plans
                            if item.component_id.endswith("-fallback-panel")
                        )
                        fallback_content = [
                            item
                            for item in page_plan.plans
                            if "-fallback-title-" in item.component_id
                            or "-fallback-line-" in item.component_id
                        ]
                        unused_height_mm = panel.proof.rect.bottom_mm - max(
                            item.proof.used_rect.bottom_mm for item in fallback_content
                        )
                        self.assertGreaterEqual(unused_height_mm, 0.0)
                        self.assertLessEqual(unused_height_mm, 2 * 4.25)

        self.assertLessEqual(longest_rows["A4"], longest_rows["LETTER"])
        self.assertLess(longest_rows["LETTER"], longest_rows["FUTURE-RECOVERY"])

    def test_public_render_fits_24_word_passphrase_on_a4_and_letter(self) -> None:
        with TemporaryDirectory() as tmp:
            for phrase_name, phrase in _RECOVERY_PASSPHRASES:
                self.assertEqual(len(phrase.split()), 24)
                recovery_meta = build_recovery_meta(
                    passphrase=phrase,
                    quorum_threshold=None,
                    quorum_shares=None,
                    signing_pub=b"\x31" * 32,
                )
                for paper_size in ("A4", "LETTER"):
                    with self.subTest(phrase=phrase_name, paper_size=paper_size):
                        output_path = (
                            Path(tmp) / f"recovery-24-words-{phrase_name}-{paper_size.lower()}.pdf"
                        )
                        inputs = replace(
                            _recovery_inputs(output_path, paper_size=paper_size),
                            recovery_meta=recovery_meta,
                        )

                        result = render_frames_to_pdf(inputs)
                        reader = validate_pdf_has_pages(output_path)

                        validate_render_layout_proof(
                            artifact_label="public Archive 24-word recovery document",
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
                        for page in result.layout_proof.pages:
                            passphrase = next(
                                component
                                for component in page.components
                                if component.component_id.endswith("-meta-value-4")
                            )
                            self.assertGreaterEqual(passphrase.line_count, 4)
                            self.assertLessEqual(passphrase.line_count, 8)
                            self.assertGreaterEqual(passphrase.font_size_pt or 0.0, 6.4)
                            constraint_ids = {
                                constraint.constraint_id
                                for constraint in page.separation_constraints
                            }
                            self.assertTrue(
                                {
                                    f"archive-recovery-p{page.page_number}"
                                    "-metadata-header-rule-clearance",
                                    f"archive-recovery-p{page.page_number}"
                                    "-header-instructions-clearance",
                                    f"archive-recovery-p{page.page_number}"
                                    "-instructions-fallback-clearance",
                                    f"archive-recovery-p{page.page_number}"
                                    "-fallback-validation-clearance",
                                    f"archive-recovery-p{page.page_number}"
                                    "-validation-footer-clearance",
                                }.issubset(constraint_ids)
                            )
                        extracted_text = " ".join(extract_pdf_text(reader).split())
                        self.assertIn(
                            " ".join(recovery_meta.passphrase_lines),
                            extracted_text,
                        )

    def test_recovery_metadata_keeps_credential_and_grouped_signing_key_on_one_row(
        self,
    ) -> None:
        cases = (
            (
                "passphrase",
                build_recovery_meta(
                    passphrase="demo-render-passphrase",
                    quorum_threshold=None,
                    quorum_shares=None,
                    signing_pub=b"\x31" * 32,
                ),
                "archive-recovery-p1-meta-label-4",
                "archive-recovery-p1-meta-label-2",
                26.0,
            ),
            (
                "quorum",
                build_recovery_meta(
                    passphrase=None,
                    quorum_threshold=2,
                    quorum_shares=3,
                    signing_pub=b"\x31" * 32,
                ),
                "archive-recovery-p1-meta-label-2",
                "archive-recovery-p1-meta-label-4",
                26.0,
            ),
        )
        with TemporaryDirectory() as tmp:
            for (
                case_name,
                recovery_meta,
                expected_label,
                omitted_label,
                signing_key_y_mm,
            ) in cases:
                for paper_size, (width_mm, height_mm) in _PAPER_DIMENSIONS.items():
                    with self.subTest(case=case_name, paper_size=paper_size):
                        inputs = replace(
                            _recovery_inputs(
                                Path(tmp) / f"archive-{case_name}-{paper_size.lower()}.pdf",
                                paper_size=paper_size,
                            ),
                            recovery_meta=recovery_meta,
                        )
                        surface = FpdfSurface(
                            page_width_mm=width_mm,
                            page_height_mm=height_mm,
                        )
                        packaged_direct_pdf_assets().register_fonts(surface)

                        plan = build_archive_recovery_direct_plan(surface, inputs)

                        first_page = plan.page_plans[0]
                        component_ids = {item.component_id for item in first_page.plans}
                        self.assertIn(expected_label, component_ids)
                        self.assertNotIn(omitted_label, component_ids)
                        signing_key = next(
                            item
                            for item in first_page.plans
                            if item.component_id == "archive-recovery-p1-meta-value-3"
                        )
                        signing_label = next(
                            item
                            for item in first_page.plans
                            if item.component_id == "archive-recovery-p1-meta-label-3"
                        )
                        self.assertEqual(
                            "".join(
                                token for line in signing_key.lines for token in line.text.split()
                            ),
                            "31" * 32,
                        )
                        self.assertEqual(
                            tuple(
                                len(token)
                                for line in signing_key.lines
                                for token in line.text.split()
                            ),
                            (4,) * 16,
                        )
                        self.assertEqual(len(signing_key.lines), 2)
                        self.assertEqual(signing_key.fit.style.size_pt, 6.4)
                        self.assertFalse(signing_key.proof.overflow)
                        width_scale = (width_mm - 28.0) / 182.0
                        signing_x_mm = 14.0 + (133.0 - 14.0) * width_scale
                        signing_width_mm = 63.0 * width_scale
                        self.assertAlmostEqual(signing_label.proof.rect.x_mm, signing_x_mm)
                        self.assertAlmostEqual(signing_label.proof.rect.y_mm, signing_key_y_mm)
                        self.assertAlmostEqual(signing_label.proof.rect.width_mm, signing_width_mm)
                        self.assertAlmostEqual(signing_key.proof.rect.x_mm, signing_x_mm)
                        self.assertAlmostEqual(signing_key.proof.rect.y_mm, signing_key_y_mm + 2.7)
                        self.assertAlmostEqual(signing_key.proof.rect.width_mm, signing_width_mm)

                        document_id = next(
                            item
                            for item in first_page.plans
                            if item.component_id == "archive-recovery-p1-meta-value-0"
                        )
                        created = next(
                            item
                            for item in first_page.plans
                            if item.component_id == "archive-recovery-p1-meta-value-1"
                        )
                        self.assertAlmostEqual(document_id.proof.rect.width_mm, 22.0 * width_scale)
                        self.assertAlmostEqual(created.proof.rect.width_mm, 28.0 * width_scale)
                        credential = next(
                            item for item in first_page.plans if item.component_id == expected_label
                        )
                        self.assertAlmostEqual(credential.proof.rect.y_mm, 26.0)
                        self.assertAlmostEqual(credential.proof.rect.width_mm, 63.0 * width_scale)
                        self.assertLessEqual(
                            credential.proof.rect.right_mm,
                            signing_key.proof.rect.x_mm,
                        )

    def test_public_render_paginates_100_word_literal_passphrase(self) -> None:
        phrase = " ".join(f"word{index:04d}" for index in range(100))
        recovery_meta = build_recovery_meta(
            passphrase=phrase,
            quorum_threshold=None,
            quorum_shares=None,
            signing_pub=b"\x31" * 32,
        )
        with TemporaryDirectory() as tmp:
            for paper_size in ("A4", "LETTER"):
                with self.subTest(paper_size=paper_size):
                    output_path = Path(tmp) / f"recovery-100-words-{paper_size.lower()}.pdf"
                    inputs = replace(
                        _recovery_inputs(output_path, paper_size=paper_size),
                        recovery_meta=recovery_meta,
                    )

                    result = render_frames_to_pdf(inputs)
                    reader = validate_pdf_has_pages(output_path)

                    validate_render_layout_proof(
                        artifact_label="public Archive 100-word recovery document",
                        layout_proof=result.layout_proof,
                        expected_page_count=len(reader.pages),
                    )
                    self.assertGreater(len(reader.pages), 1)
                    validate_text_in_pdf(
                        artifact_label="public Archive 100-word recovery document",
                        reader=reader,
                        expected_text=(
                            "METADATA CONTINUATION",
                            "Join every printed passphrase line",
                            "word0000",
                            "word0099",
                        ),
                    )

    def test_render_shard_and_signing_key_shard_write_valid_pdfs(self) -> None:
        with TemporaryDirectory() as tmp:
            for doc_type, expected_title, builder, renderer in (
                (
                    DOC_TYPE_SHARD,
                    "SHARD DOCUMENT",
                    build_archive_shard_direct_plan,
                    render_archive_shard_direct_pdf,
                ),
                (
                    DOC_TYPE_SIGNING_KEY_SHARD,
                    "SIGNING AUTHORITY SHARD",
                    build_archive_signing_key_shard_direct_plan,
                    render_archive_signing_key_shard_direct_pdf,
                ),
            ):
                output_path = Path(tmp) / f"{doc_type}.pdf"
                inputs = _shard_inputs(output_path, doc_type=doc_type, data_size=2048)
                surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
                packaged_direct_pdf_assets().register_fonts(surface)

                plan = builder(surface, inputs)
                result = renderer(inputs)

                reader = validate_pdf_has_pages(output_path)
                fallback_panel = next(
                    item
                    for item in plan.page_plans[0].plans
                    if item.component_id.endswith("-fallback-panel")
                )
                fallback_lines = [
                    item
                    for item in plan.page_plans[0].plans
                    if "-fallback-line-" in item.component_id
                ]
                self.assertEqual(len(reader.pages), 1)
                self.assertEqual(result.artifact_proof.physical_qr_count, 1)
                self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
                self.assertAlmostEqual(fallback_panel.proof.rect.x_mm, 14.0)
                self.assertAlmostEqual(fallback_panel.proof.rect.width_mm, A4_WIDTH_MM - 28.0)
                self.assertAlmostEqual(
                    plan.page_plans[0].rect.height_mm - fallback_panel.proof.rect.bottom_mm,
                    20.5,
                )
                self.assertTrue(fallback_lines)
                self.assertGreaterEqual(
                    min(line.proof.font_size_pt for line in fallback_lines),
                    6.5,
                )
                panel_midpoint = (
                    fallback_panel.proof.rect.x_mm + fallback_panel.proof.rect.width_mm / 2.0
                )
                self.assertTrue(
                    any(line.proof.rect.x_mm >= panel_midpoint for line in fallback_lines)
                )
                self.assertIsNotNone(result.fallback_proof)
                validate_render_artifact_proof(
                    artifact_label=f"direct Archive {doc_type} document",
                    inputs=inputs,
                    artifact_proof=result.artifact_proof,
                )
                validate_fallback_text_in_pdf(
                    artifact_label=f"direct Archive {doc_type} document",
                    reader=reader,
                    fallback_sections=inputs.fallback_sections or (),
                    fallback_proof=result.fallback_proof,
                )
                validate_text_in_pdf(
                    artifact_label=f"direct Archive {doc_type} document",
                    reader=reader,
                    expected_text=(expected_title, "RAW TEXT FALLBACK"),
                )

    def test_short_shard_fallback_panel_stays_full_width_at_bottom_on_responsive_pages(
        self,
    ) -> None:
        page_sizes = (
            PaperSize("A4", "A4", 210.0, 297.0),
            PaperSize("LETTER", "Letter", 215.9, 279.4),
            PaperSize("FUTURE-PORTRAIT", "Future portrait", 260.0, 360.0),
        )
        longest_lines: dict[tuple[str, str], int] = {}
        with TemporaryDirectory() as tmp:
            for page_size in page_sizes:
                for doc_type, builder in (
                    (DOC_TYPE_SHARD, build_archive_shard_direct_plan),
                    (DOC_TYPE_SIGNING_KEY_SHARD, build_archive_signing_key_shard_direct_plan),
                ):
                    with self.subTest(page_size=page_size.name, doc_type=doc_type):
                        base_inputs = _shard_inputs(
                            Path(tmp) / f"{doc_type}-{page_size.name}.pdf",
                            doc_type=doc_type,
                            data_size=400,
                        )
                        inputs = replace(
                            base_inputs,
                            context={**base_inputs.context, "paper_size": page_size.name},
                            page_size=page_size,
                        )
                        surface = FpdfSurface(
                            page_width_mm=page_size.width_mm,
                            page_height_mm=page_size.height_mm,
                        )
                        packaged_direct_pdf_assets().register_fonts(surface)

                        page_plan = builder(surface, inputs).page_plans[0]

                        panel = next(
                            item
                            for item in page_plan.plans
                            if item.component_id.endswith("-fallback-panel")
                        )
                        lines = [
                            item
                            for item in page_plan.plans
                            if "-fallback-line-" in item.component_id
                        ]
                        self.assertAlmostEqual(panel.proof.rect.x_mm, 14.0)
                        self.assertAlmostEqual(
                            panel.proof.rect.width_mm,
                            page_size.width_mm - 28.0,
                        )
                        self.assertAlmostEqual(
                            page_plan.rect.height_mm - panel.proof.rect.bottom_mm,
                            20.5,
                        )
                        self.assertTrue(lines)
                        self.assertTrue(
                            all(
                                line.proof.rect.width_mm >= panel.proof.rect.width_mm * 0.9
                                for line in lines
                            )
                        )
                        self.assertGreaterEqual(
                            min(line.proof.font_size_pt for line in lines),
                            8.5,
                        )
                        self.assertFalse(
                            any(
                                item.component_id.endswith("-fallback-column-rule")
                                for item in page_plan.plans
                            )
                        )
                        longest_lines[(doc_type, page_size.name)] = max(
                            len(line.lines[0].text) for line in lines
                        )

            for doc_type in (DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD):
                self.assertLessEqual(
                    longest_lines[(doc_type, "A4")],
                    longest_lines[(doc_type, "LETTER")],
                )
                self.assertLess(
                    longest_lines[(doc_type, "A4")],
                    longest_lines[(doc_type, "FUTURE-PORTRAIT")],
                )

    def test_build_and_render_kit_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "kit.pdf"
            inputs = _kit_inputs(output_path, count=5)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_archive_kit_direct_plan(surface, inputs)
            result = render_archive_kit_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(len(plan.page_plans), 2)
            self.assertEqual(result.artifact_proof.physical_qr_count, 5)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Archive kit document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Archive kit document",
                reader=reader,
                expected_text=(
                    "RECOVERY KIT",
                    "PART 01",
                    "HOW TO REBUILD THE RECOVERY KIT",
                    "PAGE 2 / 2",
                ),
            )

    def test_all_archive_documents_render_on_registered_and_future_sizes(self) -> None:
        paper_sizes = (
            ("A4", 210.0, 297.0, False),
            ("LETTER", 215.9, 279.4, False),
            ("FUTURE-PORTRAIT", 200.0, 320.0, True),
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for paper_size, expected_width_mm, expected_height_mm, explicit_size in paper_sizes:
                input_paper_size = "A4" if explicit_size else paper_size
                cases = (
                    (
                        DOC_TYPE_MAIN,
                        _main_inputs(
                            root / f"main-{paper_size}.pdf",
                            count=21,
                            paper_size=input_paper_size,
                        ),
                        render_archive_main_direct_pdf,
                    ),
                    (
                        DOC_TYPE_KIT,
                        _kit_inputs(
                            root / f"kit-{paper_size}.pdf",
                            count=14,
                            paper_size=input_paper_size,
                        ),
                        render_archive_kit_direct_pdf,
                    ),
                    (
                        DOC_TYPE_RECOVERY,
                        _recovery_inputs(
                            root / f"recovery-{paper_size}.pdf",
                            paper_size=input_paper_size,
                            auth_size=500,
                            main_size=4_000,
                        ),
                        render_archive_recovery_direct_pdf,
                    ),
                    (
                        DOC_TYPE_SHARD,
                        _shard_inputs(
                            root / f"shard-{paper_size}.pdf",
                            doc_type=DOC_TYPE_SHARD,
                            paper_size=input_paper_size,
                        ),
                        render_archive_shard_direct_pdf,
                    ),
                    (
                        DOC_TYPE_SIGNING_KEY_SHARD,
                        _shard_inputs(
                            root / f"signing-{paper_size}.pdf",
                            doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
                            paper_size=input_paper_size,
                        ),
                        render_archive_signing_key_shard_direct_pdf,
                    ),
                )
                for doc_type, inputs, renderer in cases:
                    with self.subTest(paper_size=paper_size, doc_type=doc_type):
                        if explicit_size:
                            inputs = replace(
                                inputs,
                                context={**inputs.context, "paper_size": paper_size},
                                page_size=PaperSize(
                                    paper_size,
                                    "Future portrait",
                                    expected_width_mm,
                                    expected_height_mm,
                                ),
                            )
                        result = renderer(inputs)
                        reader = validate_pdf_has_pages(inputs.output_path)

                        self.assertFalse(result.layout_proof.overflow)
                        self.assertEqual(result.layout_proof.page_count, len(reader.pages))
                        self.assertTrue(
                            all(page.separation_constraints for page in result.layout_proof.pages)
                        )
                        self.assertTrue(
                            all(
                                constraint.satisfied
                                for page in result.layout_proof.pages
                                for constraint in page.separation_constraints
                            )
                        )
                        for page in reader.pages:
                            width_mm = float(page.mediabox.width) * 25.4 / 72.0
                            height_mm = float(page.mediabox.height) * 25.4 / 72.0
                            self.assertAlmostEqual(width_mm, expected_width_mm, places=1)
                            self.assertAlmostEqual(height_mm, expected_height_mm, places=1)


if __name__ == "__main__":
    unittest.main()
