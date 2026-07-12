import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    FpdfSurface,
    build_ledger_kit_direct_plan,
    build_ledger_main_direct_plan,
    packaged_direct_pdf_assets,
    render_ledger_kit_direct_pdf,
    render_ledger_main_direct_pdf,
    render_ledger_recovery_direct_pdf,
    render_ledger_shard_direct_pdf,
    render_ledger_signing_key_shard_direct_pdf,
)
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


def _base_context() -> dict[str, object]:
    return {
        "paper_size": "A4",
        "doc_id": "88" * DOC_ID_LEN,
        "created_timestamp_utc": "2026-07-06 12:00 UTC",
    }


def _main_inputs(output_path: Path, *, count: int = 4) -> RenderInputs:
    frames = _frames(FrameType.MAIN_DOCUMENT, count, label="ledger-main")
    return RenderInputs(
        frames=frames,
        output_path=output_path,
        context=_base_context(),
        doc_type=DOC_TYPE_MAIN,
        design_name="ledger",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=False,
    )


def _recovery_inputs(output_path: Path) -> RenderInputs:
    auth_frame = _frames(FrameType.AUTH, 1, label="ledger-auth")[0]
    main_frame = _frames(FrameType.MAIN_DOCUMENT, 1, label="ledger-recovery-main")[0]
    return RenderInputs(
        frames=(auth_frame, main_frame),
        output_path=output_path,
        context=_base_context(),
        doc_type=DOC_TYPE_RECOVERY,
        design_name="ledger",
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


def _shard_inputs(output_path: Path, *, doc_type: str = DOC_TYPE_SHARD) -> RenderInputs:
    frame = _frames(FrameType.KEY_DOCUMENT, 1, label=f"ledger-{doc_type}")[0]
    context = _base_context()
    context.update({"shard_index": 1, "shard_total": 3, "shard_threshold": 2})
    return RenderInputs(
        frames=(frame,),
        output_path=output_path,
        context=context,
        doc_type=doc_type,
        design_name="ledger",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=True,
        fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
    )


def _kit_inputs(output_path: Path, *, count: int = 3) -> RenderInputs:
    frames = _frames(FrameType.MAIN_DOCUMENT, count, label="ledger-kit")
    return RenderInputs(
        frames=frames,
        output_path=output_path,
        context=_base_context(),
        doc_type=DOC_TYPE_KIT,
        design_name="ledger",
        lineage=RenderLineage(kind="recovery_kit"),
        qr_payloads=tuple(f"kit-chunk-{index}" for index in range(count)),
        render_qr=True,
        render_fallback=False,
    )


class TestDirectPdfLedger(unittest.TestCase):
    def test_build_main_plan_places_qr_grid(self) -> None:
        with TemporaryDirectory() as tmp:
            inputs = _main_inputs(Path(tmp) / "main.pdf")
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_ledger_main_direct_plan(surface, inputs)

            self.assertEqual(len(plan.page_plans), 1)
            self.assertEqual(plan.artifact_proof.physical_qr_count, 4)
            first_card = next(
                item
                for item in plan.page_plans[0].plans
                if item.component_id == "ledger-main-p1-qr-card-0"
            )
            self.assertGreater(first_card.proof.rect.width_mm, 55.0)
            validate_render_artifact_proof(
                artifact_label="direct Ledger main document",
                inputs=inputs,
                artifact_proof=plan.artifact_proof,
            )

    def test_render_main_writes_valid_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "main.pdf"
            inputs = _main_inputs(output_path)

            result = render_ledger_main_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Ledger main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Ledger main document",
                reader=reader,
                expected_text=("MAIN DOCUMENT", "PAGE"),
            )

    def test_render_recovery_writes_valid_fallback_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "recovery.pdf"
            inputs = _recovery_inputs(output_path)

            result = render_ledger_recovery_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            self.assertIsNotNone(result.fallback_proof)
            validate_render_artifact_proof(
                artifact_label="direct Ledger recovery document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_fallback_text_in_pdf(
                artifact_label="direct Ledger recovery document",
                reader=reader,
                fallback_sections=inputs.fallback_sections or (),
                fallback_proof=result.fallback_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Ledger recovery document",
                reader=reader,
                expected_text=("RECOVERY DOCUMENT", "AUTH FRAME", "Passphrase"),
            )

    def test_render_shard_and_signing_key_shard_write_valid_pdfs(self) -> None:
        with TemporaryDirectory() as tmp:
            for doc_type, expected_title, renderer in (
                (DOC_TYPE_SHARD, "SHARD DOCUMENT", render_ledger_shard_direct_pdf),
                (
                    DOC_TYPE_SIGNING_KEY_SHARD,
                    "SIGNING AUTHORITY SHARD",
                    render_ledger_signing_key_shard_direct_pdf,
                ),
            ):
                output_path = Path(tmp) / f"{doc_type}.pdf"
                inputs = _shard_inputs(output_path, doc_type=doc_type)

                result = renderer(inputs)

                reader = validate_pdf_has_pages(output_path)
                self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
                self.assertIsNotNone(result.fallback_proof)
                validate_render_artifact_proof(
                    artifact_label=f"direct Ledger {doc_type} document",
                    inputs=inputs,
                    artifact_proof=result.artifact_proof,
                )
                validate_fallback_text_in_pdf(
                    artifact_label=f"direct Ledger {doc_type} document",
                    reader=reader,
                    fallback_sections=inputs.fallback_sections or (),
                    fallback_proof=result.fallback_proof,
                )
                validate_text_in_pdf(
                    artifact_label=f"direct Ledger {doc_type} document",
                    reader=reader,
                    expected_text=(expected_title, "SHARD PAYLOAD"),
                )

    def test_build_and_render_kit_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "kit.pdf"
            inputs = _kit_inputs(output_path, count=5)
            surface = FpdfSurface(page_width_mm=A4_WIDTH_MM, page_height_mm=A4_HEIGHT_MM)
            packaged_direct_pdf_assets().register_fonts(surface)

            plan = build_ledger_kit_direct_plan(surface, inputs)
            result = render_ledger_kit_direct_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(len(plan.page_plans), 2)
            self.assertEqual(result.artifact_proof.physical_qr_count, 5)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct Ledger kit document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )
            validate_text_in_pdf(
                artifact_label="direct Ledger kit document",
                reader=reader,
                expected_text=("RECOVERY KIT", "HOW TO REBUILD THE RECOVERY KIT"),
            )


if __name__ == "__main__":
    unittest.main()
