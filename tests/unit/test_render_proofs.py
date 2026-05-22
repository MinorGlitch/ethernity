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

from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.render.proofs import (
    RenderProofError,
    build_render_artifact_proof,
    frame_digest,
    qr_payload_digest,
    validate_fallback_render_proof,
    validate_fallback_text_in_pdf,
    validate_render_artifact_proof,
)
from ethernity.render.types import (
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderLineage,
)


def _qr_payload_digest_for_frame(frame: Frame) -> str:
    return qr_payload_digest(encode_frame(frame))


class TestRenderProofs(unittest.TestCase):
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
            template_path="/tmp/template.html.j2",
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
            template_path="/tmp/template.html.j2",
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
            template_path="/tmp/template.html.j2",
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
            template_path="/tmp/template.html.j2",
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
            template_path="/tmp/template.html.j2",
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
            template_path="/tmp/template.html.j2",
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
        class _Page:
            def extract_text(self) -> str:
                return "Auth Frame\nybndrfg8ejkmcpqx\n"

        class _Reader:
            pages = [_Page()]

        proof = RenderFallbackProof(
            section_frame_digests=(),
            section_titles=("Auth Frame",),
            expected_section_count=0,
            emitted_block_count=1,
            emitted_line_count=1,
            consumed_section_count=0,
            fully_consumed=True,
            emitted_fallback_lines=("ybndr fg8e jkmc pqx",),
        )

        validate_fallback_text_in_pdf(
            artifact_label="rendered recovery document",
            reader=_Reader(),
            fallback_proof=proof,
        )
