# Copyright (C) 2026 Alex Stoyanov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import unittest

from ethernity.core.bounds import MAX_FALLBACK_LINES
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.encoding.zbase32 import encode_zbase32
from ethernity.render.fallback_text import format_zbase32_lines
from ethernity.render.proofs import (
    RenderProofError,
    build_render_artifact_proof,
    frame_digest,
    qr_payload_digest,
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_render_artifact_proof,
    validate_render_layout_proof,
)
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderLayoutProof,
    RenderLineage,
    RenderPageLayoutProof,
    RenderRectProof,
)


def _qr_payload_digest_for_frame(frame: Frame) -> str:
    return qr_payload_digest(encode_frame(frame))


class TestRenderProofs(unittest.TestCase):
    def test_validate_render_layout_proof_requires_proof(self) -> None:
        with self.assertRaisesRegex(RenderProofError, "missing render layout proof"):
            validate_render_layout_proof(
                artifact_label="rendered recovery document",
                layout_proof=None,
                expected_page_count=1,
            )

    def test_validate_render_layout_proof_rejects_page_count_and_order_mismatch(self) -> None:
        page_one = _layout_page(1)
        page_two = _layout_page(2)
        cases = (
            RenderLayoutProof(backend="direct", page_count=1, pages=(page_one, page_two)),
            RenderLayoutProof(backend="direct", page_count=2, pages=(page_two, page_one)),
        )
        for proof in cases:
            with self.subTest(proof=proof), self.assertRaises(RenderProofError):
                validate_render_layout_proof(
                    artifact_label="rendered recovery document",
                    layout_proof=proof,
                    expected_page_count=2,
                )

    def test_validate_render_layout_proof_rejects_overflow_and_out_of_bounds(self) -> None:
        for page in (
            _layout_page(1, overflow_component_ids=("fallback",)),
            _layout_page(1, out_of_bounds_component_ids=("fallback",)),
        ):
            with (
                self.subTest(page=page),
                self.assertRaisesRegex(
                    RenderProofError,
                    "clipped or out-of-bounds",
                ),
            ):
                validate_render_layout_proof(
                    artifact_label="rendered recovery document",
                    layout_proof=RenderLayoutProof(
                        backend="direct",
                        page_count=1,
                        pages=(page,),
                    ),
                    expected_page_count=1,
                )

    def test_validate_render_artifact_proof_accepts_matching_render_inputs(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x33" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        inputs = RenderInputs(
            frames=(frame,),
            design_name="sentinel",
            output_path="/tmp/out.pdf",
            context={},
            doc_type="main",
            lineage=RenderLineage(kind="root_backup"),
            render_fallback=False,
        )
        proof = RenderArtifactProof(
            output_path="/tmp/out.pdf",
            doc_type="main",
            frame_digests=(frame_digest(frame),),
            encoded_payload_count=1,
            physical_qr_count=1,
            qr_payload_digests=(_qr_payload_digest_for_frame(frame),),
            physical_qr_payload_indexes=(0,),
            physical_qr_payload_digests=(_qr_payload_digest_for_frame(frame),),
        )

        validate_render_artifact_proof(
            artifact_label="rendered QR document",
            inputs=inputs,
            artifact_proof=proof,
        )

    def test_validate_render_artifact_proof_rejects_frame_mismatch(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x44" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        inputs = RenderInputs(
            frames=(frame,),
            design_name="sentinel",
            output_path="/tmp/out.pdf",
            context={},
            doc_type="main",
            lineage=RenderLineage(kind="root_backup"),
            render_fallback=False,
        )
        proof = RenderArtifactProof(
            output_path="/tmp/out.pdf",
            doc_type="main",
            frame_digests=("not-the-frame",),
            encoded_payload_count=1,
            physical_qr_count=1,
            qr_payload_digests=(_qr_payload_digest_for_frame(frame),),
            physical_qr_payload_indexes=(0,),
            physical_qr_payload_digests=(_qr_payload_digest_for_frame(frame),),
        )

        with self.assertRaises(RenderProofError) as ctx:
            validate_render_artifact_proof(
                artifact_label="rendered QR document",
                inputs=inputs,
                artifact_proof=proof,
            )

        self.assertIn("frame digests", str(ctx.exception))

    def test_validate_render_artifact_proof_rejects_duplicate_omitted_qr_payload(self) -> None:
        frames = (
            Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x44" * DOC_ID_LEN,
                index=0,
                total=2,
                data=b"payload-1",
            ),
            Frame(
                version=VERSION,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=b"\x44" * DOC_ID_LEN,
                index=1,
                total=2,
                data=b"payload-2",
            ),
        )
        payload_digests = tuple(_qr_payload_digest_for_frame(frame) for frame in frames)
        inputs = RenderInputs(
            frames=frames,
            design_name="sentinel",
            output_path="/tmp/out.pdf",
            context={},
            doc_type="main",
            lineage=RenderLineage(kind="root_backup"),
            render_fallback=False,
        )
        proof = RenderArtifactProof(
            output_path="/tmp/out.pdf",
            doc_type="main",
            frame_digests=tuple(frame_digest(frame) for frame in frames),
            encoded_payload_count=2,
            physical_qr_count=2,
            qr_payload_digests=payload_digests,
            physical_qr_payload_indexes=(0, 0),
            physical_qr_payload_digests=(payload_digests[0], payload_digests[0]),
        )

        with self.assertRaises(RenderProofError) as ctx:
            validate_render_artifact_proof(
                artifact_label="rendered QR document",
                inputs=inputs,
                artifact_proof=proof,
            )

        self.assertIn("omit or reorder", str(ctx.exception))

    def test_validate_render_artifact_proof_accepts_intentional_repeated_qr_payload(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x44" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        payload_digest = _qr_payload_digest_for_frame(frame)
        inputs = RenderInputs(
            frames=(frame,),
            design_name="sentinel",
            output_path="/tmp/out.pdf",
            context={},
            doc_type="shard",
            lineage=RenderLineage(kind="root_backup"),
            render_fallback=False,
        )
        proof = RenderArtifactProof(
            output_path="/tmp/out.pdf",
            doc_type="shard",
            frame_digests=(frame_digest(frame),),
            encoded_payload_count=1,
            physical_qr_count=2,
            qr_payload_digests=(payload_digest,),
            physical_qr_payload_indexes=(0, 0),
            physical_qr_payload_digests=(payload_digest, payload_digest),
        )

        validate_render_artifact_proof(
            artifact_label="rendered shard document",
            inputs=inputs,
            artifact_proof=proof,
        )

    def test_validate_render_artifact_proof_rejects_physical_qr_count_mismatch(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x55" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        inputs = RenderInputs(
            frames=(frame,),
            design_name="sentinel",
            output_path="/tmp/out.pdf",
            context={},
            doc_type="recovery",
            lineage=RenderLineage(kind="root_backup"),
            render_qr=False,
            render_fallback=False,
        )
        proof = RenderArtifactProof(
            output_path="/tmp/out.pdf",
            doc_type="recovery",
            frame_digests=(frame_digest(frame),),
            encoded_payload_count=1,
            physical_qr_count=1,
        )

        with self.assertRaises(RenderProofError) as ctx:
            validate_render_artifact_proof(
                artifact_label="rendered recovery document",
                inputs=inputs,
                artifact_proof=proof,
            )

        self.assertIn("physical QR count", str(ctx.exception))

    def test_build_render_artifact_proof_requires_physical_qr_count(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x66" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        inputs = RenderInputs(
            frames=(frame,),
            design_name="sentinel",
            output_path="/tmp/out.pdf",
            context={},
            doc_type="recovery",
            lineage=RenderLineage(kind="root_backup"),
            render_qr=False,
            render_fallback=False,
        )

        proof = build_render_artifact_proof(
            inputs,
            encoded_payload_count=1,
            physical_qr_count=0,
            fallback_proof=None,
        )

        self.assertEqual(proof.encoded_payload_count, 1)
        self.assertEqual(proof.physical_qr_count, 0)
        validate_render_artifact_proof(
            artifact_label="rendered recovery document",
            inputs=inputs,
            artifact_proof=proof,
        )

    def test_validate_fallback_render_proof_accepts_matching_consumed_frames(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        proof = RenderFallbackProof(
            section_frame_digests=(frame_digest(frame),),
            section_titles=("Main Frame",),
            expected_section_count=1,
            emitted_block_count=1,
            emitted_line_count=1,
            consumed_section_count=1,
            fully_consumed=True,
            emitted_fallback_lines=("line",),
        )

        validate_fallback_render_proof(
            artifact_label="rendered recovery document",
            frames=(frame,),
            fallback_proof=proof,
        )

    def test_validate_fallback_render_proof_rejects_unconsumed_frames(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x22" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"payload",
        )
        proof = RenderFallbackProof(
            section_frame_digests=(frame_digest(frame),),
            section_titles=("Main Frame",),
            expected_section_count=1,
            emitted_block_count=0,
            emitted_line_count=0,
            consumed_section_count=0,
            fully_consumed=False,
            emitted_fallback_lines=(),
        )

        with self.assertRaises(RenderProofError) as ctx:
            validate_fallback_render_proof(
                artifact_label="rendered recovery document",
                frames=(frame,),
                fallback_proof=proof,
            )

        self.assertIn("did not emit all fallback", str(ctx.exception))
        self.assertEqual(ctx.exception.details["fully_consumed"], False)

    def test_validate_fallback_text_accepts_collapsed_pdf_spacing(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=b"\x55" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"auth",
        )
        lines = _rendered_fallback_lines(frame, line_length=24)

        class _Page:
            def extract_text(self) -> str:
                collapsed = [line.replace(" ", "") for line in lines]
                return "Auth Frame\n" + "\n".join(
                    f"{index:02d}. {line}" for index, line in enumerate(collapsed, start=1)
                )

        class _Reader:
            pages = [_Page()]

        proof = RenderFallbackProof(
            section_frame_digests=(frame_digest(frame),),
            section_titles=("Auth Frame",),
            expected_section_count=1,
            emitted_block_count=1,
            emitted_line_count=len(lines),
            consumed_section_count=1,
            fully_consumed=True,
            emitted_fallback_lines=tuple(lines),
        )

        validate_fallback_text_in_pdf(
            artifact_label="rendered recovery document",
            reader=_Reader(),
            fallback_sections=(FallbackSection(label="Auth Frame", frame=frame),),
            fallback_proof=proof,
        )

    def test_validate_fallback_text_round_trips_more_than_nine_lines(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x66" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"x" * 300,
        )
        lines = _rendered_fallback_lines(frame, line_length=24)
        self.assertGreater(len(lines), 10)
        reader = _reader_with_text(
            "Main Frame\n"
            + "\n".join(f"{index:02d}. {line}" for index, line in enumerate(lines, start=1))
        )

        validate_fallback_text_in_pdf(
            artifact_label="rendered recovery document",
            reader=reader,
            fallback_sections=(FallbackSection(label="Main Frame", frame=frame),),
        )

    def test_nonfallback_pdf_lines_do_not_consume_fallback_line_budget(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x67" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"main",
        )
        reader = _reader_with_text(
            "\n".join(["page metadata"] * (MAX_FALLBACK_LINES + 1))
            + "\n"
            + _numbered_section_text("Main Frame", frame)
        )

        validate_fallback_text_in_pdf(
            artifact_label="rendered recovery document",
            reader=reader,
            fallback_sections=(FallbackSection(label="Main Frame", frame=frame),),
        )

    def test_more_than_max_actual_fallback_lines_are_rejected(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x68" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"x" * 130_000,
        )
        fallback_lines = _rendered_fallback_lines(frame, line_length=4)
        self.assertGreater(len(fallback_lines), MAX_FALLBACK_LINES)
        reader = _reader_with_text(
            "Main Frame\n" + "\n".join(f"1. {line}" for line in fallback_lines)
        )

        with self.assertRaises(RenderProofError):
            validate_fallback_text_in_pdf(
                artifact_label="rendered recovery document",
                reader=reader,
                fallback_sections=(FallbackSection(label="Main Frame", frame=frame),),
            )

    def test_validate_fallback_text_rejects_missing_malformed_clipped_or_reordered_lines(
        self,
    ) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x77" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"x" * 80,
        )
        lines = _rendered_fallback_lines(frame, line_length=24)
        cases = {
            "missing": lines[:-1],
            "malformed": [*lines[:-1], f"{lines[-1]}0"],
            "clipped": [*lines[:-1], lines[-1][:-1]],
            "reordered": [lines[1], lines[0], *lines[2:]],
        }
        for label, actual_lines in cases.items():
            with self.subTest(label=label):
                reader = _reader_with_text(
                    "Main Frame\n"
                    + "\n".join(
                        f"{index:02d}. {line}" for index, line in enumerate(actual_lines, start=1)
                    )
                )
                with self.assertRaises(RenderProofError):
                    validate_fallback_text_in_pdf(
                        artifact_label="rendered recovery document",
                        reader=reader,
                        fallback_sections=(FallbackSection(label="Main Frame", frame=frame),),
                    )

    def test_validate_fallback_text_rejects_mismatched_identity(self) -> None:
        expected = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x88" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"shard",
        )
        actual = Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"\x99" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"shard",
        )
        reader = _reader_with_text(
            "SHARD PAYLOAD\n" + "\n".join(_rendered_fallback_lines(actual, line_length=80))
        )

        with self.assertRaisesRegex(RenderProofError, "document identity"):
            validate_fallback_text_in_pdf(
                artifact_label="rendered shard",
                reader=reader,
                fallback_sections=(FallbackSection(label="SHARD PAYLOAD", frame=expected),),
            )

    def test_validate_fallback_text_rejects_reordered_sections(self) -> None:
        auth = Frame(VERSION, FrameType.AUTH, b"\xaa" * DOC_ID_LEN, 0, 1, b"auth")
        main = Frame(VERSION, FrameType.MAIN_DOCUMENT, b"\xaa" * DOC_ID_LEN, 0, 1, b"main")
        reader = _reader_with_text(
            _numbered_section_text("Main Frame", main)
            + "\n"
            + _numbered_section_text("Auth Frame", auth)
        )

        with self.assertRaisesRegex(RenderProofError, "reordered"):
            validate_fallback_text_in_pdf(
                artifact_label="rendered recovery document",
                reader=reader,
                fallback_sections=(
                    FallbackSection(label="Auth Frame", frame=auth),
                    FallbackSection(label="Main Frame", frame=main),
                ),
            )

    def test_validate_fallback_text_rejects_extra_labeled_foreign_section(self) -> None:
        main = Frame(VERSION, FrameType.MAIN_DOCUMENT, b"\xaa" * DOC_ID_LEN, 0, 1, b"main")
        foreign = Frame(VERSION, FrameType.KEY_DOCUMENT, b"\xaa" * DOC_ID_LEN, 0, 1, b"shard")
        reader = _reader_with_text(
            _numbered_section_text("Main Frame", main)
            + "\nSHARD PAYLOAD\n"
            + "\n".join(_rendered_fallback_lines(foreign, line_length=80))
        )

        with self.assertRaisesRegex(RenderProofError, "unexpected fallback section"):
            validate_fallback_text_in_pdf(
                artifact_label="rendered recovery document",
                reader=reader,
                fallback_sections=(FallbackSection(label="Main Frame", frame=main),),
            )

    def test_validate_numbered_fallback_rejects_foreign_frame_in_same_block(self) -> None:
        expected = Frame(VERSION, FrameType.MAIN_DOCUMENT, b"\xaa" * DOC_ID_LEN, 0, 1, b"main")
        foreign = Frame(VERSION, FrameType.MAIN_DOCUMENT, b"\xbb" * DOC_ID_LEN, 0, 1, b"other")
        expected_lines = _rendered_fallback_lines(expected, line_length=24)
        foreign_lines = _rendered_fallback_lines(foreign, line_length=24)
        reader = _reader_with_text(
            "Main Frame\n"
            + "\n".join(
                f"{index:02d}. {line}"
                for index, line in enumerate((*expected_lines, *foreign_lines), start=1)
            )
        )

        with self.assertRaises(RenderProofError):
            validate_fallback_text_in_pdf(
                artifact_label="rendered recovery document",
                reader=reader,
                fallback_sections=(FallbackSection(label="Main Frame", frame=expected),),
            )

    def test_validate_fallback_text_rejects_duplicate_main_label_group(self) -> None:
        main = Frame(VERSION, FrameType.MAIN_DOCUMENT, b"\xaa" * DOC_ID_LEN, 0, 1, b"main")
        reader = _reader_with_text(
            _numbered_section_text("Main Frame", main) + "\nFooter\nMain Frame\n03. specifications"
        )

        with self.assertRaisesRegex(RenderProofError, "duplicate 'Main Frame'"):
            validate_fallback_text_in_pdf(
                artifact_label="rendered recovery document",
                reader=reader,
                fallback_sections=(FallbackSection(label="Main Frame", frame=main),),
            )

    def test_validate_fallback_text_rejects_unicode_confusable(self) -> None:
        frame = Frame(
            VERSION,
            FrameType.MAIN_DOCUMENT,
            b"\xdd" * DOC_ID_LEN,
            0,
            1,
            b"\x06",
        )
        text = _numbered_section_text("Main Frame", frame)
        self.assertIn("k", text)
        reader = _reader_with_text(text.replace("k", "\N{KELVIN SIGN}", 1))

        with self.assertRaises(RenderProofError):
            validate_fallback_text_in_pdf(
                artifact_label="rendered recovery document",
                reader=reader,
                fallback_sections=(FallbackSection(label="Main Frame", frame=frame),),
            )

    def test_validate_unnumbered_fallback_rejects_extra_foreign_frame(self) -> None:
        expected = Frame(VERSION, FrameType.KEY_DOCUMENT, b"\xbb" * DOC_ID_LEN, 0, 1, b"one")
        foreign = Frame(VERSION, FrameType.KEY_DOCUMENT, b"\xcc" * DOC_ID_LEN, 0, 1, b"two")
        reader = _reader_with_text(
            "MANUAL TRANSCRIPTION\n"
            + "\n".join(
                [
                    *_rendered_fallback_lines(expected, line_length=80),
                    *_rendered_fallback_lines(foreign, line_length=80),
                ]
            )
            + "\nETHERNITY FOOTER"
        )

        with self.assertRaises(RenderProofError):
            validate_fallback_text_in_pdf(
                artifact_label="rendered shard",
                reader=reader,
                fallback_sections=(FallbackSection(label=None, frame=expected),),
            )

    def test_validate_unnumbered_fallback_rejects_extra_recognized_section(self) -> None:
        expected = Frame(VERSION, FrameType.KEY_DOCUMENT, b"\xbb" * DOC_ID_LEN, 0, 1, b"one")
        foreign = Frame(VERSION, FrameType.AUTH, b"\xcc" * DOC_ID_LEN, 0, 1, b"two")
        reader = _reader_with_text(
            "MANUAL TRANSCRIPTION\n"
            + "\n".join(_rendered_fallback_lines(expected, line_length=80))
            + "\nETHERNITY FOOTER\nAUTH FRAME\n"
            + "\n".join(_rendered_fallback_lines(foreign, line_length=80))
        )

        with self.assertRaisesRegex(RenderProofError, "unexpected fallback section"):
            validate_fallback_text_in_pdf(
                artifact_label="rendered shard",
                reader=reader,
                fallback_sections=(FallbackSection(label=None, frame=expected),),
            )


def _rendered_fallback_lines(frame: Frame, *, line_length: int) -> list[str]:
    return format_zbase32_lines(
        encode_zbase32(encode_frame(frame)),
        group_size=4,
        line_length=line_length,
        line_count=None,
    )


def _layout_page(
    page_number: int,
    *,
    overflow_component_ids: tuple[str, ...] = (),
    out_of_bounds_component_ids: tuple[str, ...] = (),
) -> RenderPageLayoutProof:
    return RenderPageLayoutProof(
        page_number=page_number,
        rect=RenderRectProof(x_mm=0, y_mm=0, width_mm=210, height_mm=297),
        component_ids=(),
        overflow_component_ids=overflow_component_ids,
        out_of_bounds_component_ids=out_of_bounds_component_ids,
        components=(),
    )


def _numbered_section_text(label: str, frame: Frame) -> str:
    return (
        label
        + "\n"
        + "\n".join(
            f"{index:02d}. {line}"
            for index, line in enumerate(_rendered_fallback_lines(frame, line_length=24), start=1)
        )
    )


def _reader_with_text(text: str) -> object:
    class _Page:
        def extract_text(self) -> str:
            return text

    class _Reader:
        pages = [_Page()]

    return _Reader()
