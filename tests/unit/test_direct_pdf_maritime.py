import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import ethernity.render.direct_pdf.maritime as maritime_module
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render.direct_pdf.assets import packaged_direct_pdf_assets
from ethernity.render.direct_pdf.components import TextPlacementProof
from ethernity.render.direct_pdf.maritime import (
    build_maritime_kit_direct_plan,
    build_maritime_main_direct_plan,
    build_maritime_recovery_direct_plan,
    build_maritime_shard_direct_plan,
    build_maritime_signing_key_shard_direct_plan,
    render_maritime_kit_direct_pdf,
    render_maritime_main_direct_pdf,
    render_maritime_recovery_direct_pdf,
    render_maritime_shard_direct_pdf,
    render_maritime_signing_key_shard_direct_pdf,
)
from ethernity.render.direct_pdf.page_geometry import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    LETTER_HEIGHT_MM,
    LETTER_WIDTH_MM,
)
from ethernity.render.direct_pdf.structured_common import (
    FallbackLineEntry,
    FallbackPage,
    FallbackPageEntry,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import PdfRect
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.proofs import (
    validate_fallback_text_in_pdf,
    validate_pdf_has_pages,
    validate_render_artifact_proof,
    validate_text_in_pdf,
)
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage

_PAPER_DIMENSIONS = {
    "A4": (A4_WIDTH_MM, A4_HEIGHT_MM),
    "LETTER": (LETTER_WIDTH_MM, LETTER_HEIGHT_MM),
}
_RECOVERY_PASSPHRASE_CASES = (
    ("typical", " ".join(f"word{index:02d}" for index in range(1, 25))),
    ("eight-character", " ".join(f"word{index:04d}" for index in range(1, 25))),
)


def _frames(
    frame_type: FrameType,
    count: int,
    *,
    label: str,
    data_size: int | None = None,
) -> tuple[Frame, ...]:
    return tuple(
        Frame(
            version=VERSION,
            frame_type=frame_type,
            doc_id=b"\x88" * DOC_ID_LEN,
            index=index,
            total=count,
            data=(
                (f"{label}-{index}-".encode("ascii") + b"x" * data_size)[:data_size]
                if data_size is not None
                else f"{label}-{index}".encode("ascii")
            ),
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
    frames = _frames(FrameType.MAIN_DOCUMENT, count, label="maritime-main")
    return RenderInputs(
        frames=frames,
        output_path=output_path,
        context=_base_context(paper_size=paper_size),
        doc_type=DOC_TYPE_MAIN,
        design_name="maritime",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=False,
    )


def _recovery_inputs(
    output_path: Path,
    *,
    paper_size: str = "A4",
    data_size: int | None = None,
) -> RenderInputs:
    auth_data_size = min(data_size, 512) if data_size is not None else None
    auth_frame = _frames(
        FrameType.AUTH,
        1,
        label="maritime-auth",
        data_size=auth_data_size,
    )[0]
    main_frame = _frames(
        FrameType.MAIN_DOCUMENT,
        1,
        label="maritime-recovery-main",
        data_size=data_size,
    )[0]
    return RenderInputs(
        frames=(auth_frame, main_frame),
        output_path=output_path,
        context=_base_context(paper_size=paper_size),
        doc_type=DOC_TYPE_RECOVERY,
        design_name="maritime",
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
    frame = _frames(
        FrameType.KEY_DOCUMENT,
        1,
        label=f"maritime-{doc_type}",
        data_size=data_size,
    )[0]
    context = _base_context(paper_size=paper_size)
    context.update({"shard_index": 1, "shard_total": 3, "shard_threshold": 2})
    return RenderInputs(
        frames=(frame,),
        output_path=output_path,
        context=context,
        doc_type=doc_type,
        design_name="maritime",
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
    frames = _frames(FrameType.MAIN_DOCUMENT, count, label="maritime-kit")
    return RenderInputs(
        frames=frames,
        output_path=output_path,
        context=_base_context(paper_size=paper_size),
        doc_type=DOC_TYPE_KIT,
        design_name="maritime",
        lineage=RenderLineage(kind="recovery_kit"),
        qr_payloads=tuple(f"kit-chunk-{index}" for index in range(count)),
        render_qr=True,
        render_fallback=False,
    )


def _surface_for(paper_size: str) -> FpdfSurface:
    width_mm, height_mm = _PAPER_DIMENSIONS[paper_size]
    surface = FpdfSurface(page_width_mm=width_mm, page_height_mm=height_mm)
    packaged_direct_pdf_assets().register_fonts(surface)
    return surface


def _pdf_text(reader: object) -> str:
    pages = getattr(reader, "pages")
    return "\n".join((page.extract_text() or "") for page in pages).upper()


def _page_items(page_plan: object, marker: str) -> list[object]:
    return [plan for plan in getattr(page_plan, "plans") if marker in plan.component_id]


class TestDirectPdfMaritime(unittest.TestCase):
    def _assert_fallback_rows_inside_blocks(self, page_plan: object) -> None:
        blocks = _page_items(page_plan, "-fallback-block-")
        rows = [
            item
            for item in getattr(page_plan, "plans")
            if any(
                marker in item.component_id
                for marker in ("-fallback-title-", "-fallback-number-", "-fallback-line-")
            )
        ]
        for index, first in enumerate(blocks):
            for second in blocks[index + 1 :]:
                self.assertTrue(
                    first.proof.rect.right_mm <= second.proof.rect.x_mm
                    or second.proof.rect.right_mm <= first.proof.rect.x_mm
                    or first.proof.rect.bottom_mm <= second.proof.rect.y_mm
                    or second.proof.rect.bottom_mm <= first.proof.rect.y_mm
                )
        for row in rows:
            self.assertTrue(
                any(
                    row.proof.rect.x_mm >= block.proof.rect.x_mm
                    and row.proof.rect.right_mm <= block.proof.rect.right_mm
                    and row.proof.rect.y_mm >= block.proof.rect.y_mm
                    and row.proof.rect.bottom_mm <= block.proof.rect.bottom_mm
                    for block in blocks
                ),
                row.component_id,
            )

    def _assert_render_geometry(
        self,
        *,
        plan: object,
        result: object,
        reader: object,
        paper_size: str,
    ) -> None:
        width_mm, height_mm = _PAPER_DIMENSIONS[paper_size]
        page_plans = getattr(plan, "page_plans")
        reader_pages = getattr(reader, "pages")
        self.assertEqual(len(page_plans), len(reader_pages))
        for page_plan, reader_page in zip(page_plans, reader_pages, strict=True):
            self.assertAlmostEqual(page_plan.rect.width_mm, width_mm)
            self.assertAlmostEqual(page_plan.rect.height_mm, height_mm)
            self.assertFalse(page_plan.proof.overflow)
            self.assertTrue(page_plan.proof.separation_constraints)
            self.assertTrue(
                all(proof.satisfied for proof in page_plan.proof.separation_constraints)
            )
            rendered_width_mm = float(reader_page.mediabox.width) * 25.4 / 72.0
            rendered_height_mm = float(reader_page.mediabox.height) * 25.4 / 72.0
            self.assertAlmostEqual(rendered_width_mm, width_mm, places=1)
            self.assertAlmostEqual(rendered_height_mm, height_mm, places=1)
        layout_proof = getattr(result, "layout_proof")
        self.assertIsNotNone(layout_proof)
        self.assertFalse(layout_proof.overflow)

    def test_build_main_plan_places_qr_field(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _main_inputs(Path(tmp) / "main.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_maritime_main_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 1)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 4)
            field = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "maritime-main-p1-qr-field"
            )
            self.assertGreater(field.proof.rect.width_mm, 175.0)
            validate_render_artifact_proof(
                artifact_label="direct Maritime main document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )

    def test_render_main_writes_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "main.pdf"
            inputs = _main_inputs(output_path)

            result = render_maritime_main_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Maritime main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Maritime main document",
                reader=reader,
                expected_text=("MAIN DOCUMENT", "CREATED"),
            )

    def test_render_recovery_writes_valid_fallback_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery.pdf"
            inputs = _recovery_inputs(output_path)

            result = render_maritime_recovery_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            self.assertIsNotNone(result.fallback_proof)
            validate_render_artifact_proof(
                artifact_label="direct Maritime recovery document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Maritime recovery document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Maritime recovery document",
                reader=reader,
                expected_text=("RECOVERY DOCUMENT", "AUTH FRAME", "PASSPHRASE"),
            )

    def test_recovery_renders_normal_24_word_passphrase_on_supported_pages(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for passphrase_case, passphrase in _RECOVERY_PASSPHRASE_CASES:
                recovery_meta = build_recovery_meta(
                    passphrase=passphrase,
                    quorum_threshold=None,
                    quorum_shares=None,
                    signing_pub=b"\x31" * 32,
                )
                for paper_size in _PAPER_DIMENSIONS:
                    with self.subTest(case=passphrase_case, paper_size=paper_size):
                        output_path = root / (
                            f"recovery-{passphrase_case}-passphrase-{paper_size}.pdf"
                        )
                        inputs = replace(
                            _recovery_inputs(
                                output_path,
                                paper_size=paper_size,
                                data_size=4000,
                            ),
                            recovery_meta=recovery_meta,
                        )

                        plan = build_maritime_recovery_direct_plan(
                            _surface_for(paper_size),
                            inputs,
                        )
                        result = render_maritime_recovery_direct_pdf(inputs)
                        reader = validate_pdf_has_pages(output_path)

                        self.assertGreater(len(plan.page_plans), 1)
                        fallback_proof = plan.fallback_proof
                        if fallback_proof is None:
                            raise AssertionError(
                                "Maritime recovery plan omitted its fallback proof"
                            )
                        self.assertTrue(fallback_proof.fully_consumed)
                        first_word = passphrase.split()[0]
                        passphrase_plans = [
                            item
                            for page_plan in plan.page_plans
                            for item in page_plan.plans
                            if "-meta-value-" in item.component_id
                            and isinstance(item.proof, TextPlacementProof)
                            and any(
                                first_word in placement.text
                                for placement in getattr(item, "lines", ())
                            )
                        ]
                        passphrase_proofs = [
                            item.proof
                            for item in passphrase_plans
                            if isinstance(item.proof, TextPlacementProof)
                        ]
                        self.assertEqual(len(passphrase_proofs), len(plan.page_plans))
                        self.assertTrue(
                            all(
                                tuple(placement.text for placement in getattr(item, "lines", ()))
                                == recovery_meta.passphrase_lines
                                for item in passphrase_plans
                            )
                        )
                        self.assertTrue(all(proof.line_count == 4 for proof in passphrase_proofs))
                        self.assertTrue(all(not proof.overflow for proof in passphrase_proofs))
                        self.assertGreaterEqual(
                            min(proof.font_size_pt for proof in passphrase_proofs),
                            7.2,
                        )
                        for page_plan in plan.page_plans:
                            instruction_shell = next(
                                item
                                for item in page_plan.plans
                                if item.component_id.endswith("-instructions-shell")
                            )
                            fallback_blocks = [
                                item
                                for item in page_plan.plans
                                if "-fallback-block-" in item.component_id
                            ]
                            self.assertGreaterEqual(
                                min(block.proof.rect.y_mm for block in fallback_blocks)
                                - instruction_shell.proof.rect.bottom_mm,
                                2.0,
                            )
                            self._assert_fallback_rows_inside_blocks(page_plan)
                        pdf_text = _pdf_text(reader)
                        for word in passphrase.upper().split():
                            self.assertIn(word, pdf_text)
                        self.assertIn("3131 3131", pdf_text)
                        validate_fallback_text_in_pdf(
                            artifact_label="direct Maritime normal-passphrase recovery document",
                            reader=reader,
                            fallback_sections=inputs.fallback_sections or (),
                            fallback_proof=fallback_proof,
                        )
                        self._assert_render_geometry(
                            plan=plan,
                            result=result,
                            reader=reader,
                            paper_size=paper_size,
                        )

    def test_render_shard_and_signing_key_shard_write_valid_pdfs(self) -> None:
        with TemporaryDirectory() as tmp:
            for doc_type, expected_title, builder, renderer in (
                (
                    DOC_TYPE_SHARD,
                    "SHARD DOCUMENT",
                    build_maritime_shard_direct_plan,
                    render_maritime_shard_direct_pdf,
                ),
                (
                    DOC_TYPE_SIGNING_KEY_SHARD,
                    "SIGNING AUTHORITY SHARD",
                    build_maritime_signing_key_shard_direct_plan,
                    render_maritime_signing_key_shard_direct_pdf,
                ),
            ):
                output_path = Path(tmp) / f"{doc_type}.pdf"
                inputs = _shard_inputs(output_path, doc_type=doc_type)

                plan = builder(_surface_for("A4"), inputs)
                result = renderer(inputs)

                reader = validate_pdf_has_pages(output_path)
                page_plan = plan.page_plans[0]
                fallback_blocks = _page_items(page_plan, "-fallback-block-")
                fallback_lines = _page_items(page_plan, "-fallback-line-")
                self.assertEqual(len(fallback_blocks), 1)
                outer_block = fallback_blocks[0]
                self.assertAlmostEqual(outer_block.proof.rect.x_mm, 14.0)
                self.assertAlmostEqual(outer_block.proof.rect.width_mm, A4_WIDTH_MM - 28.0)
                self.assertAlmostEqual(
                    page_plan.rect.height_mm - outer_block.proof.rect.bottom_mm,
                    21.0,
                )
                self.assertTrue(fallback_lines)
                self.assertTrue(
                    all(
                        line.proof.rect.width_mm >= outer_block.proof.rect.width_mm * 0.9
                        for line in fallback_lines
                    )
                )
                self.assertGreaterEqual(
                    min(line.proof.font_size_pt for line in fallback_lines),
                    8.5,
                )
                self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
                self.assertIsNotNone(result.fallback_proof)
                validate_render_artifact_proof(
                    artifact_label=f"direct Maritime {doc_type} document",
                    inputs=inputs,
                    artifact_proof=result.artifact_proof,
                )
                validate_fallback_text_in_pdf(
                    artifact_label=f"direct Maritime {doc_type} document",
                    reader=reader,
                    fallback_sections=inputs.fallback_sections or (),
                    fallback_proof=result.fallback_proof,
                )
                validate_text_in_pdf(
                    artifact_label=f"direct Maritime {doc_type} document",
                    reader=reader,
                    expected_text=(expected_title, "SHARD PAYLOAD"),
                )

    def test_build_and_render_kit_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "kit.pdf"
            inputs = _kit_inputs(output_path, count=5)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_maritime_kit_direct_plan(surface, inputs)
            result = render_maritime_kit_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(len(plan.page_plans), 2)
            self.assertEqual(result.artifact_proof.physical_qr_count, 5)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Maritime kit document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Maritime kit document",
                reader=reader,
                expected_text=("RECOVERY KIT", "HOW TO REBUILD THE RECOVERY KIT"),
            )

    def test_main_and_kit_boundaries_are_responsive_labeled_and_footer_safe(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for paper_size in _PAPER_DIMENSIONS:
                with self.subTest(paper_size=paper_size, doc_type=DOC_TYPE_MAIN):
                    output_path = root / f"main-{paper_size}.pdf"
                    inputs = _main_inputs(output_path, count=20, paper_size=paper_size)
                    plan = build_maritime_main_direct_plan(_surface_for(paper_size), inputs)
                    result = render_maritime_main_direct_pdf(inputs)
                    reader = validate_pdf_has_pages(output_path)

                    self.assertEqual(len(plan.page_plans), 3)
                    self.assertEqual(len(_page_items(plan.page_plans[-1], "-qr-card-bg-")), 2)
                    self.assertEqual(len(_page_items(plan.page_plans[-1], "-qr-label-")), 2)
                    for page_plan in plan.page_plans:
                        cards = _page_items(page_plan, "-qr-card-bg-")
                        labels = _page_items(page_plan, "-qr-label-")
                        fields = [
                            item
                            for item in page_plan.plans
                            if item.component_id.endswith("-qr-field")
                        ]
                        self.assertEqual(len(cards), len(labels))
                        self.assertGreaterEqual(
                            page_plan.rect.height_mm
                            - max(field.proof.rect.bottom_mm for field in fields),
                            20.0,
                        )
                        for label in labels:
                            payload_index = label.component_id.rsplit("-", 1)[-1]
                            image = next(
                                item
                                for item in page_plan.plans
                                if item.component_id.endswith(f"-qr-image-{payload_index}")
                            )
                            self.assertLessEqual(
                                label.proof.rect.bottom_mm,
                                image.proof.rect.y_mm,
                            )
                    text = _pdf_text(reader)
                    self.assertIn("PAGE 3 / 3", text)
                    self.assertIn("SEGMENT 01 / 20", text)
                    self.assertIn("SEGMENT 20 / 20", text)
                    self._assert_render_geometry(
                        plan=plan,
                        result=result,
                        reader=reader,
                        paper_size=paper_size,
                    )

                with self.subTest(paper_size=paper_size, doc_type=DOC_TYPE_KIT):
                    output_path = root / f"kit-{paper_size}.pdf"
                    inputs = _kit_inputs(output_path, count=14, paper_size=paper_size)
                    plan = build_maritime_kit_direct_plan(_surface_for(paper_size), inputs)
                    result = render_maritime_kit_direct_pdf(inputs)
                    reader = validate_pdf_has_pages(output_path)

                    self.assertEqual(len(plan.page_plans), 3)
                    self.assertEqual(len(_page_items(plan.page_plans[1], "-qr-card-bg-")), 5)
                    self.assertEqual(len(_page_items(plan.page_plans[1], "-qr-label-")), 5)
                    instruction_page = plan.page_plans[-1]
                    footer_items = _page_items(instruction_page, "-insert-footer-")
                    self.assertGreaterEqual(
                        instruction_page.rect.height_mm
                        - max(item.proof.rect.bottom_mm for item in footer_items),
                        20.0,
                    )
                    text = _pdf_text(reader)
                    self.assertIn("PART 01 / 14", text)
                    self.assertIn("PART 14 / 14", text)
                    self.assertIn("PAGE 3 / 3", text)
                    self._assert_render_geometry(
                        plan=plan,
                        result=result,
                        reader=reader,
                        paper_size=paper_size,
                    )

    def test_fallback_boundaries_are_responsive_numbered_and_footer_safe(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for paper_size in _PAPER_DIMENSIONS:
                with self.subTest(paper_size=paper_size, doc_type=DOC_TYPE_RECOVERY):
                    output_path = root / f"recovery-{paper_size}.pdf"
                    inputs = _recovery_inputs(
                        output_path,
                        paper_size=paper_size,
                        data_size=2400,
                    )
                    plan = build_maritime_recovery_direct_plan(_surface_for(paper_size), inputs)
                    result = render_maritime_recovery_direct_pdf(inputs)
                    reader = validate_pdf_has_pages(output_path)

                    self.assertGreater(len(plan.page_plans), 1)
                    first_lines = _page_items(plan.page_plans[0], "-fallback-line-")
                    final_lines = _page_items(plan.page_plans[-1], "-fallback-line-")
                    self.assertLess(len(final_lines), len(first_lines))
                    for page_plan in plan.page_plans:
                        fallback_blocks = _page_items(page_plan, "-fallback-block-")
                        self._assert_fallback_rows_inside_blocks(page_plan)
                        self.assertGreaterEqual(
                            page_plan.rect.height_mm
                            - max(block.proof.rect.bottom_mm for block in fallback_blocks),
                            20.0,
                        )
                    text = _pdf_text(reader)
                    page_count = len(plan.page_plans)
                    self.assertIn(f"PAGE {page_count} / {page_count}", text)
                    self._assert_render_geometry(
                        plan=plan,
                        result=result,
                        reader=reader,
                        paper_size=paper_size,
                    )

                for doc_type, builder, renderer in (
                    (
                        DOC_TYPE_SHARD,
                        build_maritime_shard_direct_plan,
                        render_maritime_shard_direct_pdf,
                    ),
                    (
                        DOC_TYPE_SIGNING_KEY_SHARD,
                        build_maritime_signing_key_shard_direct_plan,
                        render_maritime_signing_key_shard_direct_pdf,
                    ),
                ):
                    with self.subTest(paper_size=paper_size, doc_type=doc_type):
                        output_path = root / f"{doc_type}-{paper_size}.pdf"
                        inputs = _shard_inputs(
                            output_path,
                            doc_type=doc_type,
                            paper_size=paper_size,
                            data_size=2048,
                        )
                        plan = builder(_surface_for(paper_size), inputs)
                        result = renderer(inputs)
                        reader = validate_pdf_has_pages(output_path)

                        self.assertEqual(len(plan.page_plans), 1)
                        self.assertEqual(result.artifact_proof.physical_qr_count, 1)
                        self.assertIsNotNone(result.fallback_proof)
                        self.assertTrue(result.fallback_proof.fully_consumed)
                        for page_plan in plan.page_plans:
                            fallback_blocks = _page_items(page_plan, "-fallback-block-")
                            fallback_numbers = _page_items(page_plan, "-fallback-number-")
                            fallback_lines = _page_items(page_plan, "-fallback-line-")
                            self.assertEqual(len(fallback_blocks), 1)
                            self.assertAlmostEqual(fallback_blocks[0].proof.rect.x_mm, 14.0)
                            self.assertAlmostEqual(
                                fallback_blocks[0].proof.rect.width_mm,
                                page_plan.rect.width_mm - 28.0,
                            )
                            self.assertAlmostEqual(
                                page_plan.rect.height_mm - fallback_blocks[0].proof.rect.bottom_mm,
                                21.0,
                            )
                            self.assertGreaterEqual(
                                min(item.proof.font_size_pt for item in fallback_numbers),
                                6.5,
                            )
                            self.assertGreaterEqual(
                                min(item.proof.font_size_pt for item in fallback_lines),
                                6.0,
                            )
                            panel_midpoint = (
                                fallback_blocks[0].proof.rect.x_mm
                                + fallback_blocks[0].proof.rect.width_mm / 2.0
                            )
                            self.assertTrue(
                                any(
                                    line.proof.rect.x_mm >= panel_midpoint
                                    for line in fallback_lines
                                )
                            )
                            self._assert_fallback_rows_inside_blocks(page_plan)
                            self.assertGreaterEqual(
                                page_plan.rect.height_mm
                                - max(block.proof.rect.bottom_mm for block in fallback_blocks),
                                20.0,
                            )
                        text = _pdf_text(reader)
                        self.assertIn("PAGE 1 / 1", text)
                        self._assert_render_geometry(
                            plan=plan,
                            result=result,
                            reader=reader,
                            paper_size=paper_size,
                        )

    def test_tall_recovery_page_measures_four_digit_number_gutter(self) -> None:
        with TemporaryDirectory() as tmp:
            page = PaperSize("MARITIME_TALL", "Maritime tall", 200.0, 10_000.0)
            base_inputs = _recovery_inputs(
                Path(tmp) / "recovery-maritime-tall.pdf",
                data_size=100_000,
            )
            inputs = replace(
                base_inputs,
                context={**base_inputs.context, "paper_size": page.name},
                page_size=page,
            )
            surface = FpdfSurface(
                page_width_mm=page.width_mm,
                page_height_mm=page.height_mm,
            )
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_maritime_recovery_direct_plan(surface, inputs)

            four_digit_numbers = tuple(
                item
                for page_plan in plan.page_plans
                for item in page_plan.plans
                if "-fallback-number-" in item.component_id
                and any(placement.text == "1000." for placement in getattr(item, "lines", ()))
            )
            self.assertTrue(four_digit_numbers)
            self.assertTrue(all(not item.proof.overflow for item in four_digit_numbers))
            self.assertTrue(all(item.proof.rect.width_mm > 6.0 for item in four_digit_numbers))
            self.assertTrue(
                all(
                    constraint.satisfied
                    for page_plan in plan.page_plans
                    for constraint in page_plan.proof.separation_constraints
                )
            )

    def test_five_digit_number_gutter_preserves_payload_width(self) -> None:
        surface = FpdfSurface(page_width_mm=200.0, page_height_mm=270.0)
        packaged_direct_pdf_assets().register_fonts(surface)
        entry = FallbackLineEntry(section_index=0, line_number=50_000, text="yyyy " * 17)
        fallback_page = FallbackPage(
            page_number=1,
            entries=(
                FallbackPageEntry(
                    entry=entry,
                    row_index=0,
                    display_line_number=50_000,
                ),
            ),
        )

        plans = maritime_module._fallback_block_plans(
            surface,
            fallback_page,
            prefix="maritime-five-digit",
            area=PdfRect(14.0, 50.0, 172.0, 6.0),
        )

        number = next(item for item in plans if "-fallback-number-" in item.component_id)
        payload = next(item for item in plans if "-fallback-line-" in item.component_id)
        self.assertGreater(number.proof.rect.width_mm, 6.0)
        self.assertFalse(number.proof.overflow)
        self.assertFalse(payload.proof.overflow)

    def test_compact_shard_fallback_line_length_tracks_measured_page_width(self) -> None:
        page_sizes = (
            PaperSize("A4", "A4", 210.0, 297.0),
            PaperSize("LETTER", "Letter", 215.9, 279.4),
            PaperSize("FUTURE-SHARD-WIDE", "Future shard wide", 260.0, 360.0),
        )
        longest_lines: dict[tuple[str, str], int] = {}
        with TemporaryDirectory() as tmp:
            for doc_type, builder in (
                (DOC_TYPE_SHARD, build_maritime_shard_direct_plan),
                (DOC_TYPE_SIGNING_KEY_SHARD, build_maritime_signing_key_shard_direct_plan),
            ):
                for page_size in page_sizes:
                    with self.subTest(doc_type=doc_type, page_size=page_size.name):
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
                        panel = _page_items(page_plan, "-fallback-block-")[0]
                        lines = _page_items(page_plan, "-fallback-line-")

                        self.assertTrue(lines)
                        self.assertEqual(
                            len({round(line.proof.rect.x_mm, 2) for line in lines}),
                            1,
                        )
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
                        longest_lines[(doc_type, page_size.name)] = max(
                            len(line.lines[0].text) for line in lines
                        )

            for doc_type in (DOC_TYPE_SHARD, DOC_TYPE_SIGNING_KEY_SHARD):
                self.assertLess(
                    longest_lines[(doc_type, "A4")],
                    longest_lines[(doc_type, "LETTER")],
                )
                self.assertLess(
                    longest_lines[(doc_type, "LETTER")],
                    longest_lines[(doc_type, "FUTURE-SHARD-WIDE")],
                )

    def test_main_uses_explicit_future_portrait_dimensions(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "main-future-portrait.pdf"
            base_inputs = _main_inputs(
                output_path,
                count=20,
                paper_size="A4",
            )
            context = dict(base_inputs.context)
            context["paper_size"] = "FUTURE-PORTRAIT"
            inputs = replace(
                base_inputs,
                context=context,
                page_size=PaperSize(
                    "FUTURE-PORTRAIT",
                    "Future portrait",
                    200.0,
                    270.0,
                ),
            )
            surface = FpdfSurface(page_width_mm=200.0, page_height_mm=270.0)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_maritime_main_direct_plan(surface, inputs)
            result = render_maritime_main_direct_pdf(inputs)
            reader = validate_pdf_has_pages(output_path)

            self.assertEqual(len(plan.page_plans), 3)
            self.assertFalse(result.layout_proof.overflow)
            self.assertIn("SEGMENT 20 / 20", _pdf_text(reader))
            for page_plan, reader_page in zip(plan.page_plans, reader.pages, strict=True):
                self.assertAlmostEqual(page_plan.rect.width_mm, 200.0)
                self.assertAlmostEqual(page_plan.rect.height_mm, 270.0)
                self.assertFalse(page_plan.proof.overflow)
                self.assertTrue(
                    all(proof.satisfied for proof in page_plan.proof.separation_constraints)
                )
                self.assertAlmostEqual(
                    float(reader_page.mediabox.width) * 25.4 / 72.0,
                    200.0,
                    places=1,
                )
                self.assertAlmostEqual(
                    float(reader_page.mediabox.height) * 25.4 / 72.0,
                    270.0,
                    places=1,
                )

    def test_shard_renders_support_manifest_minimum_custom_page_size(self) -> None:
        page_size = PaperSize(
            "CUSTOM-200X270",
            "Custom 200 x 270",
            200.0,
            270.0,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for doc_type, builder, renderer in (
                (
                    DOC_TYPE_SHARD,
                    build_maritime_shard_direct_plan,
                    render_maritime_shard_direct_pdf,
                ),
                (
                    DOC_TYPE_SIGNING_KEY_SHARD,
                    build_maritime_signing_key_shard_direct_plan,
                    render_maritime_signing_key_shard_direct_pdf,
                ),
            ):
                with self.subTest(doc_type=doc_type):
                    output_path = root / f"{doc_type}-custom-200x270.pdf"
                    base_inputs = _shard_inputs(
                        output_path,
                        doc_type=doc_type,
                        paper_size="A4",
                        data_size=2048,
                    )
                    context = dict(base_inputs.context)
                    context["paper_size"] = page_size.name
                    inputs = replace(
                        base_inputs,
                        context=context,
                        page_size=page_size,
                    )
                    surface = FpdfSurface(
                        page_width_mm=page_size.width_mm,
                        page_height_mm=page_size.height_mm,
                    )
                    packaged_direct_pdf_assets().register_fonts(surface)

                    plan = builder(surface, inputs)
                    result = renderer(inputs)
                    reader = validate_pdf_has_pages(output_path)

                    self.assertEqual(len(plan.page_plans), 1)
                    self.assertEqual(result.artifact_proof.physical_qr_count, 1)
                    self.assertEqual(len(plan.page_plans), len(reader.pages))
                    layout_proof = result.layout_proof
                    if layout_proof is None:
                        raise AssertionError("Maritime render did not return a layout proof")
                    self.assertFalse(layout_proof.overflow)
                    text_components = [
                        component
                        for page in layout_proof.pages
                        for component in page.components
                        if component.font_size_pt is not None
                    ]
                    self.assertTrue(text_components)
                    self.assertGreaterEqual(
                        min(component.font_size_pt or 0.0 for component in text_components),
                        5.8,
                    )
                    instruction_lines = [
                        item
                        for page_plan in plan.page_plans
                        for item in page_plan.plans
                        if "-instruction-line-" in item.component_id
                    ]
                    self.assertTrue(instruction_lines)
                    self.assertTrue(
                        all(
                            isinstance(item.proof, TextPlacementProof) for item in instruction_lines
                        )
                    )
                    instruction_proofs = [
                        item.proof
                        for item in instruction_lines
                        if isinstance(item.proof, TextPlacementProof)
                    ]
                    self.assertTrue(all(not proof.overflow for proof in instruction_proofs))
                    self.assertGreaterEqual(
                        min(proof.font_size_pt for proof in instruction_proofs),
                        8.8,
                    )
                    first_instruction_proof = next(
                        item.proof
                        for item in plan.page_plans[0].plans
                        if item.component_id.endswith("instruction-line-0")
                        and isinstance(item.proof, TextPlacementProof)
                    )
                    self.assertEqual(first_instruction_proof.line_count, 2)
                    for page_plan, reader_page in zip(
                        plan.page_plans,
                        reader.pages,
                        strict=True,
                    ):
                        self.assertAlmostEqual(page_plan.rect.width_mm, page_size.width_mm)
                        self.assertAlmostEqual(page_plan.rect.height_mm, page_size.height_mm)
                        self.assertFalse(page_plan.proof.overflow)
                        self.assertTrue(page_plan.proof.separation_constraints)
                        self.assertTrue(
                            all(proof.satisfied for proof in page_plan.proof.separation_constraints)
                        )
                        fallback_blocks = _page_items(page_plan, "-fallback-block-")
                        self.assertEqual(len(fallback_blocks), 1)
                        self.assertAlmostEqual(fallback_blocks[0].proof.rect.x_mm, 14.0)
                        self.assertAlmostEqual(
                            fallback_blocks[0].proof.rect.width_mm,
                            page_size.width_mm - 28.0,
                        )
                        self.assertAlmostEqual(
                            page_plan.rect.height_mm - fallback_blocks[0].proof.rect.bottom_mm,
                            21.0,
                        )
                        self._assert_fallback_rows_inside_blocks(page_plan)
                        self.assertAlmostEqual(
                            float(reader_page.mediabox.width) * 25.4 / 72.0,
                            page_size.width_mm,
                            places=1,
                        )
                        self.assertAlmostEqual(
                            float(reader_page.mediabox.height) * 25.4 / 72.0,
                            page_size.height_mm,
                            places=1,
                        )


if __name__ == "__main__":
    unittest.main()
