import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render import render_frames_to_pdf
from ethernity.render.backend_dispatch import DIRECT_PDF_DESIGN_REGISTRY
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.proofs import validate_pdf_has_pages, validate_render_artifact_proof
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage


def _frame(frame_type: FrameType, *, data: bytes) -> Frame:
    return Frame(
        version=VERSION,
        frame_type=frame_type,
        doc_id=b"\x88" * DOC_ID_LEN,
        index=0,
        total=1,
        data=data,
    )


class TestRenderBackendDispatch(unittest.TestCase):
    def test_direct_backend_registry_declares_supported_design_document_routes(self) -> None:
        expected_default_doc_types = {
            DOC_TYPE_KIT,
            DOC_TYPE_MAIN,
            DOC_TYPE_RECOVERY,
            DOC_TYPE_SHARD,
            DOC_TYPE_SIGNING_KEY_SHARD,
        }
        expected_doc_types_by_design = {
            "archive": expected_default_doc_types,
            "forge": expected_default_doc_types | {DOC_TYPE_KIT_INDEX},
            "ledger": expected_default_doc_types,
            "maritime": expected_default_doc_types,
            "sentinel": expected_default_doc_types | {DOC_TYPE_KIT_INDEX},
        }

        self.assertEqual(set(DIRECT_PDF_DESIGN_REGISTRY), set(expected_doc_types_by_design))
        for design_name, expected_doc_types in expected_doc_types_by_design.items():
            design = DIRECT_PDF_DESIGN_REGISTRY[design_name]
            self.assertEqual(design.style_name, design_name)
            self.assertEqual(set(design.renderers), expected_doc_types)

    def test_direct_backend_routes_supported_forge_recovery_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_recovery.pdf"
            auth_frame = _frame(FrameType.AUTH, data=b"auth")
            main_frame = _frame(FrameType.MAIN_DOCUMENT, data=b"main")
            inputs = RenderInputs(
                frames=(auth_frame, main_frame),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_RECOVERY,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=False,
                render_fallback=True,
                key_lines=("recovery-key-line",),
                recovery_meta=build_recovery_meta(
                    passphrase="alpha bravo charlie",
                    quorum_threshold=2,
                    quorum_shares=3,
                    signing_pub=None,
                ),
                fallback_sections=(
                    FallbackSection(label="AUTH FRAME", frame=auth_frame),
                    FallbackSection(label="MAIN FRAME", frame=main_frame),
                ),
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend recovery document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_sentinel_recovery_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_sentinel_recovery.pdf"
            auth_frame = _frame(FrameType.AUTH, data=b"auth")
            main_frame = _frame(FrameType.MAIN_DOCUMENT, data=b"main")
            inputs = RenderInputs(
                frames=(auth_frame, main_frame),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_RECOVERY,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=False,
                render_fallback=True,
                recovery_meta=build_recovery_meta(
                    passphrase="alpha bravo charlie",
                    quorum_threshold=2,
                    quorum_shares=3,
                    signing_pub=None,
                ),
                fallback_sections=(
                    FallbackSection(label="AUTH FRAME", frame=auth_frame),
                    FallbackSection(label="MAIN FRAME", frame=main_frame),
                ),
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend Sentinel recovery document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_sentinel_main_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_sentinel_main.pdf"
            frames = tuple(
                Frame(
                    version=VERSION,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=b"\x88" * DOC_ID_LEN,
                    index=index,
                    total=2,
                    data=f"sentinel-main-{index}".encode("ascii"),
                )
                for index in range(2)
            )
            inputs = RenderInputs(
                frames=frames,
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_MAIN,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.physical_qr_count, 2)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend Sentinel main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_sentinel_shard_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_sentinel_shard.pdf"
            frame = _frame(FrameType.KEY_DOCUMENT, data=b"sentinel-shard")
            inputs = RenderInputs(
                frames=(frame,),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                    "shard_index": 1,
                    "shard_total": 3,
                    "shard_threshold": 2,
                },
                doc_type=DOC_TYPE_SHARD,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=True,
                fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertGreaterEqual(result.artifact_proof.physical_qr_count, 1)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend Sentinel shard document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_sentinel_signing_key_shard_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_sentinel_signing_key_shard.pdf"
            frame = _frame(FrameType.KEY_DOCUMENT, data=b"sentinel-signing-shard")
            inputs = RenderInputs(
                frames=(frame,),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                    "shard_index": 1,
                    "shard_total": 3,
                    "shard_threshold": 2,
                },
                doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=True,
                fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertGreaterEqual(result.artifact_proof.physical_qr_count, 1)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend Sentinel signing-key shard document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_sentinel_kit_index_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_sentinel_kit_index.pdf"
            inputs = RenderInputs(
                frames=(),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                    "kit_qr_page_count": 1,
                    "kit_qr_chunk_count": 3,
                    "inventory_rows": (
                        {
                            "component_id": "KIT-SHELL",
                            "detail": "Offline recovery kit shell",
                        },
                    ),
                },
                doc_type=DOC_TYPE_KIT_INDEX,
                lineage=RenderLineage(kind="root_backup"),
                qr_payloads=(),
                render_qr=False,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.physical_qr_count, 0)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend Sentinel kit-index document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_sentinel_kit_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_sentinel_kit.pdf"
            frames = tuple(
                Frame(
                    version=VERSION,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=b"\x88" * DOC_ID_LEN,
                    index=index,
                    total=2,
                    data=f"sentinel-kit-{index}".encode("ascii"),
                )
                for index in range(2)
            )
            inputs = RenderInputs(
                frames=frames,
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_KIT,
                lineage=RenderLineage(kind="recovery_kit"),
                qr_payloads=("kit-0", "kit-1"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.physical_qr_count, 2)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend Sentinel kit document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_archive_main_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_archive_main.pdf"
            frames = tuple(
                Frame(
                    version=VERSION,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=b"\x88" * DOC_ID_LEN,
                    index=index,
                    total=2,
                    data=f"archive-main-{index}".encode("ascii"),
                )
                for index in range(2)
            )
            inputs = RenderInputs(
                frames=frames,
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_MAIN,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.physical_qr_count, 2)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend Archive main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_ledger_main_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_ledger_main.pdf"
            frames = tuple(
                Frame(
                    version=VERSION,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=b"\x88" * DOC_ID_LEN,
                    index=index,
                    total=2,
                    data=f"ledger-main-{index}".encode("ascii"),
                )
                for index in range(2)
            )
            inputs = RenderInputs(
                frames=frames,
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_MAIN,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.physical_qr_count, 2)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend Ledger main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_maritime_main_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_maritime_main.pdf"
            frames = tuple(
                Frame(
                    version=VERSION,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=b"\x88" * DOC_ID_LEN,
                    index=index,
                    total=2,
                    data=f"maritime-main-{index}".encode("ascii"),
                )
                for index in range(2)
            )
            inputs = RenderInputs(
                frames=frames,
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_MAIN,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.physical_qr_count, 2)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend Maritime main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_renderer_rejects_unsupported_document(self) -> None:
        with TemporaryDirectory() as tmp:
            frame = _frame(FrameType.MAIN_DOCUMENT, data=b"main")
            inputs = RenderInputs(
                frames=(frame,),
                output_path=Path(tmp) / "main.pdf",
                context={"paper_size": "A4"},
                doc_type=DOC_TYPE_MAIN,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=False,
                render_fallback=False,
            )

            with self.assertRaisesRegex(ValueError, "does not support"):
                render_frames_to_pdf(inputs)

    def test_direct_renderer_preflights_unproven_custom_geometry(self) -> None:
        frame = _frame(FrameType.MAIN_DOCUMENT, data=b"main")
        inputs = RenderInputs(
            frames=(frame,),
            output_path="ignored.pdf",
            context={"paper_size": "A5"},
            page_size=PaperSize("A5", "A5", 148.0, 210.0),
            doc_type=DOC_TYPE_MAIN,
            design_name="sentinel",
            lineage=RenderLineage(kind="root_backup"),
            render_qr=True,
            render_fallback=False,
        )

        with self.assertRaisesRegex(ValueError, "outside the proven responsive envelope"):
            render_frames_to_pdf(inputs)

    def test_render_frames_to_pdf_routes_supported_direct_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "default_direct_main.pdf"
            frame = _frame(FrameType.MAIN_DOCUMENT, data=b"default-direct")
            inputs = RenderInputs(
                frames=(frame,),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_MAIN,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))

    def test_direct_backend_routes_supported_forge_main_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_main.pdf"
            frames = tuple(
                Frame(
                    version=VERSION,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=b"\x88" * DOC_ID_LEN,
                    index=index,
                    total=2,
                    data=f"main-{index}".encode("ascii"),
                )
                for index in range(2)
            )
            inputs = RenderInputs(
                frames=frames,
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_MAIN,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.physical_qr_count, 2)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend main document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_forge_shard_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_shard.pdf"
            frame = _frame(FrameType.KEY_DOCUMENT, data=b"shard")
            inputs = RenderInputs(
                frames=(frame,),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                    "shard_index": 1,
                    "shard_total": 3,
                    "shard_threshold": 2,
                },
                doc_type=DOC_TYPE_SHARD,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=True,
                fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertGreaterEqual(result.artifact_proof.physical_qr_count, 1)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend shard document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_forge_signing_key_shard_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_signing_key_shard.pdf"
            frame = _frame(FrameType.KEY_DOCUMENT, data=b"signing-shard")
            inputs = RenderInputs(
                frames=(frame,),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                    "shard_index": 1,
                    "shard_total": 3,
                    "shard_threshold": 2,
                },
                doc_type=DOC_TYPE_SIGNING_KEY_SHARD,
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=True,
                fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=frame),),
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertGreaterEqual(result.artifact_proof.physical_qr_count, 1)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend signing-key shard document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_forge_kit_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_kit.pdf"
            frames = tuple(
                Frame(
                    version=VERSION,
                    frame_type=FrameType.MAIN_DOCUMENT,
                    doc_id=b"\x88" * DOC_ID_LEN,
                    index=index,
                    total=2,
                    data=f"kit-{index}".encode("ascii"),
                )
                for index in range(2)
            )
            inputs = RenderInputs(
                frames=frames,
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                },
                doc_type=DOC_TYPE_KIT,
                lineage=RenderLineage(kind="recovery_kit"),
                qr_payloads=("kit-0", "kit-1"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.physical_qr_count, 2)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend kit document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )

    def test_direct_backend_routes_supported_forge_kit_index_render(self) -> None:
        with TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "direct_kit_index.pdf"
            inputs = RenderInputs(
                frames=(),
                output_path=output_path,
                context={
                    "paper_size": "A4",
                    "doc_id": "88" * DOC_ID_LEN,
                    "created_timestamp_utc": "2026-07-06 12:00 UTC",
                    "kit_qr_page_count": 1,
                    "kit_qr_chunk_count": 2,
                },
                doc_type=DOC_TYPE_KIT_INDEX,
                lineage=RenderLineage(kind="root_backup"),
                qr_payloads=(),
                render_qr=False,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.physical_qr_count, 0)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))
            validate_render_artifact_proof(
                artifact_label="direct backend kit-index document",
                inputs=inputs,
                artifact_proof=result.artifact_proof,
            )


if __name__ == "__main__":
    unittest.main()
