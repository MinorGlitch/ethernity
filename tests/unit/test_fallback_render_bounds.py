import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.core.bounds import MAX_FALLBACK_LINES, MAX_MAIN_FRAME_DATA_BYTES
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.page_sizes import PaperSize, resolve_paper_size
from ethernity.render import render_frames_to_pdf
from ethernity.render.designs import list_design_manifests
from ethernity.render.direct_pdf.fallback_layout import (
    FallbackSectionLines,
    fallback_entries,
    paginate_fallback_entries,
)
from ethernity.render.doc_types import DOC_TYPE_RECOVERY
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import FallbackSection, RenderInputs, RenderLineage

_FALLBACK_GROUP_SIZE = 4


def _maximum_main_frame() -> Frame:
    return Frame(
        version=VERSION,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=b"\x00" * DOC_ID_LEN,
        index=0,
        total=1,
        data=b"\x00" * MAX_MAIN_FRAME_DATA_BYTES,
    )


def _zbase32_char_count(byte_count: int) -> int:
    return (byte_count * 8 + 4) // 5


def _fallback_payload_char_count(line: str) -> int:
    return sum(character not in {" ", "-"} for character in line)


def _recovery_inputs(
    output_path: Path,
    *,
    design_name: str,
    paper_size: PaperSize,
) -> RenderInputs:
    doc_id = b"\x33" * DOC_ID_LEN
    auth_frame = Frame(
        version=VERSION,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=b"a" * 500,
    )
    main_frame = Frame(
        version=VERSION,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=doc_id,
        index=0,
        total=1,
        data=b"m" * 12_000,
    )
    return RenderInputs(
        frames=(auth_frame, main_frame),
        output_path=output_path,
        context={
            "paper_size": paper_size.name,
            "doc_id": doc_id.hex(),
            "created_timestamp_utc": "2026-07-13 12:00 UTC",
        },
        doc_type=DOC_TYPE_RECOVERY,
        design_name=design_name,
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
        page_size=paper_size,
    )


class TestFallbackRenderBounds(unittest.TestCase):
    def test_every_recovery_renderer_fits_maximum_main_frame_under_line_cap(self) -> None:
        encoded_char_count = _zbase32_char_count(len(encode_frame(_maximum_main_frame())))
        minimum_payload_chars = math.ceil(encoded_char_count / MAX_FALLBACK_LINES)
        manifests = tuple(
            manifest
            for manifest in list_design_manifests().values()
            if DOC_TYPE_RECOVERY in manifest.documents
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for manifest in manifests:
                page_support = manifest.page_support_for(DOC_TYPE_RECOVERY)
                paper_sizes = (
                    resolve_paper_size("A4"),
                    resolve_paper_size("LETTER"),
                    PaperSize(
                        "MINIMUM",
                        f"{manifest.name} minimum recovery page",
                        page_support.minimum_width_mm,
                        page_support.minimum_height_mm,
                    ),
                )
                for paper_size in paper_sizes:
                    with self.subTest(design=manifest.name, paper_size=paper_size.name):
                        inputs = _recovery_inputs(
                            root / manifest.name / paper_size.name.lower() / "recovery.pdf",
                            design_name=manifest.name,
                            paper_size=paper_size,
                        )
                        Path(inputs.output_path).parent.mkdir(parents=True, exist_ok=True)

                        result = render_frames_to_pdf(inputs)

                        self.assertIsNotNone(result.fallback_proof)
                        self.assertIsNotNone(result.layout_proof)
                        assert result.fallback_proof is not None
                        assert result.layout_proof is not None
                        self.assertFalse(result.layout_proof.overflow)
                        emitted = iter(result.fallback_proof.emitted_fallback_lines)
                        for section in inputs.fallback_sections or ():
                            remaining = _zbase32_char_count(len(encode_frame(section.frame)))
                            while remaining > 0:
                                line_payload_chars = _fallback_payload_char_count(next(emitted))
                                self.assertLessEqual(line_payload_chars, remaining)
                                remaining -= line_payload_chars
                                if remaining > 0:
                                    self.assertGreaterEqual(
                                        line_payload_chars,
                                        minimum_payload_chars,
                                    )
                        with self.assertRaises(StopIteration):
                            next(emitted)

    def test_structured_display_numbers_reset_per_page_and_section_block(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=b"\x01" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"auth",
        )
        sections = (
            FallbackSectionLines(
                section_index=0,
                title="AUTH FRAME",
                lines=("a", "b", "c"),
                frame=frame,
            ),
            FallbackSectionLines(
                section_index=1,
                title="MAIN FRAME",
                lines=("d", "e"),
                frame=frame,
            ),
        )

        pages = paginate_fallback_entries(fallback_entries(sections), capacity=3)

        self.assertEqual(
            tuple(entry.display_line_number for entry in pages[0].entries),
            (None, 1, 2),
        )
        self.assertEqual(
            tuple(entry.display_line_number for entry in pages[1].entries),
            (1, None, 1),
        )
        self.assertEqual(
            tuple(entry.display_line_number for entry in pages[2].entries),
            (1,),
        )

    def test_structured_continuation_capacity_keeps_title_with_first_line(self) -> None:
        frame = _maximum_main_frame()
        sections = (
            FallbackSectionLines(0, "AUTH", ("a", "b", "c"), frame),
            FallbackSectionLines(1, "MAIN", ("d", "e"), frame),
        )

        pages = paginate_fallback_entries(
            fallback_entries(sections),
            capacity=3,
            continuation_capacity=2,
        )

        self.assertEqual(len(pages), 4)
        for page in pages:
            if page.entries and page.entries[-1].display_line_number is None:
                self.fail("fallback page ended with an orphan section title")

    def test_structured_title_page_with_one_row_capacity_fails_fast(self) -> None:
        frame = _maximum_main_frame()
        sections = (FallbackSectionLines(0, "AUTH", ("a",), frame),)

        with self.assertRaisesRegex(ValueError, "keep a section title"):
            paginate_fallback_entries(fallback_entries(sections), capacity=1)


if __name__ == "__main__":
    unittest.main()
