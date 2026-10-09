import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render import render_frames_to_pdf
from ethernity.render.designs import list_design_definitions
from ethernity.render.doc_types import (
    DOC_TYPE_KIT,
    DOC_TYPE_KIT_INDEX,
    DOC_TYPE_MAIN,
    DOC_TYPE_RECOVERY,
    DOC_TYPE_SHARD,
    DOC_TYPE_SIGNING_KEY_SHARD,
)
from ethernity.render.types import DocumentOrigin, RenderInputs


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

        self.assertEqual(set(list_design_definitions()), set(expected_doc_types_by_design))
        for design_name, expected_doc_types in expected_doc_types_by_design.items():
            design = list_design_definitions()[design_name]
            self.assertEqual(design.name, design_name)
            self.assertEqual(set(design.documents), expected_doc_types)

    def test_main_document_requires_qr_rendering(self) -> None:
        with TemporaryDirectory() as tmp:
            frame = _frame(FrameType.MAIN_DOCUMENT, data=b"main")
            inputs = RenderInputs(
                frames=(frame,),
                output_path=Path(tmp) / "main.pdf",
                context={"paper_size": "A4"},
                doc_type=DOC_TYPE_MAIN,
                origin=DocumentOrigin(kind="root_backup"),
                render_qr=False,
                render_fallback=False,
            )

            with self.assertRaisesRegex(ValueError, "requires QR rendering"):
                render_frames_to_pdf(inputs)

    def test_direct_renderer_preflights_unproven_custom_geometry(self) -> None:
        frame = _frame(FrameType.MAIN_DOCUMENT, data=b"main")
        inputs = RenderInputs(
            frames=(frame,),
            output_path="ignored.pdf",
            context={"paper_size": "A6"},
            page_size=PaperSize("A6", "A6", 105.0, 148.0),
            doc_type=DOC_TYPE_MAIN,
            design_name="sentinel",
            origin=DocumentOrigin(kind="root_backup"),
            render_qr=True,
            render_fallback=False,
        )

        with self.assertRaisesRegex(ValueError, "outside the supported dimensions"):
            render_frames_to_pdf(inputs)


if __name__ == "__main__":
    unittest.main()
