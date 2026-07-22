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
from unittest import mock

from ethernity.cli.shared.render_validation import (
    validate_rendered_fallback_artifact,
    validate_rendered_pdf_artifact,
)
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType, encode_frame
from ethernity.render.proofs import RenderProofError, frame_digest, qr_payload_digest
from ethernity.render.types import (
    FallbackSection,
    RenderArtifactProof,
    RenderFallbackProof,
    RenderInputs,
    RenderLayoutProof,
    RenderLineage,
    RenderResult,
)


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Reader:
    def __init__(self, text: str) -> None:
        self.pages = [_Page(text)]


class TestRenderValidation(unittest.TestCase):
    def test_fallback_artifact_validation_preserves_proof_check_order(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        inputs = RenderInputs(
            frames=(frame,),
            design_name="sentinel",
            output_path="/tmp/recovery.pdf",
            context={},
            doc_type="recovery",
            lineage=RenderLineage(kind="root_backup"),
            fallback_sections=(FallbackSection(label="MAIN FRAME", frame=frame),),
        )
        fallback_proof = RenderFallbackProof(
            section_frame_digests=(frame_digest(frame),),
            section_titles=("MAIN FRAME",),
            expected_section_count=1,
            emitted_block_count=1,
            emitted_line_count=1,
            consumed_section_count=1,
            fully_consumed=True,
        )
        result = RenderResult(
            artifact_proof=RenderArtifactProof(
                output_path="/tmp/recovery.pdf",
                doc_type="recovery",
                frame_digests=(frame_digest(frame),),
                encoded_payload_count=1,
                physical_qr_count=1,
                fallback_proof=fallback_proof,
            ),
            layout_proof=RenderLayoutProof(backend="direct", page_count=1, pages=()),
        )
        reader = _Reader("Recovery Document")
        calls: list[str] = []

        with (
            mock.patch(
                "ethernity.render.validation.validate_render_artifact_proof",
                side_effect=lambda **_kwargs: calls.append("artifact"),
            ),
            mock.patch(
                "ethernity.render.validation.validate_pdf_has_pages",
                side_effect=lambda *_args, **_kwargs: calls.append("pages") or reader,
            ),
            mock.patch(
                "ethernity.render.validation.validate_render_layout_proof",
                side_effect=lambda **_kwargs: calls.append("layout"),
            ),
            mock.patch(
                "ethernity.render.validation.validate_fallback_render_proof",
                side_effect=lambda **_kwargs: calls.append("fallback_proof"),
            ) as validate_fallback_proof,
            mock.patch(
                "ethernity.render.validation.validate_fallback_text_in_pdf",
                side_effect=lambda **_kwargs: calls.append("fallback_text"),
            ) as validate_fallback_text,
        ):
            validate_rendered_fallback_artifact(
                inputs=inputs,
                result=result,
                artifact_label="rendered recovery document",
            )

        self.assertEqual(
            calls,
            ["artifact", "pages", "layout", "fallback_proof", "fallback_text"],
        )
        self.assertIs(
            validate_fallback_proof.call_args.kwargs["fallback_proof"],
            fallback_proof,
        )
        self.assertIs(validate_fallback_text.call_args.kwargs["reader"], reader)

    def test_artifact_validation_requires_render_result(self) -> None:
        inputs = RenderInputs(
            frames=(),
            design_name="sentinel",
            output_path="/tmp/qr.pdf",
            context={},
            doc_type="qr",
            lineage=RenderLineage(kind="root_backup"),
            render_fallback=False,
        )

        with self.assertRaises(RenderProofError) as ctx:
            validate_rendered_pdf_artifact(
                inputs=inputs,
                result=object(),
                artifact_label="rendered QR document",
            )

        self.assertIn("renderer did not return RenderResult", str(ctx.exception))

    def test_artifact_validation_requires_render_artifact_proof(self) -> None:
        inputs = RenderInputs(
            frames=(),
            design_name="sentinel",
            output_path="/tmp/qr.pdf",
            context={},
            doc_type="qr",
            lineage=RenderLineage(kind="root_backup"),
            render_fallback=False,
        )

        with self.assertRaises(RenderProofError) as ctx:
            validate_rendered_pdf_artifact(
                inputs=inputs,
                result=RenderResult(),
                artifact_label="rendered QR document",
            )

        self.assertIn("missing render artifact proof", str(ctx.exception))

    def test_recovery_artifact_validation_requires_fallback_proof(self) -> None:
        frame = Frame(
            version=VERSION,
            frame_type=FrameType.MAIN_DOCUMENT,
            doc_id=b"\x11" * DOC_ID_LEN,
            index=0,
            total=1,
            data=b"ciphertext",
        )
        inputs = RenderInputs(
            frames=(frame,),
            design_name="sentinel",
            output_path="/tmp/recovery.pdf",
            context={},
            doc_type="recovery",
            lineage=RenderLineage(kind="root_backup"),
            fallback_sections=(FallbackSection(label="MAIN FRAME", frame=frame),),
        )
        result = RenderResult(
            artifact_proof=RenderArtifactProof(
                output_path="/tmp/recovery.pdf",
                doc_type="recovery",
                frame_digests=(frame_digest(frame),),
                encoded_payload_count=1,
                physical_qr_count=1,
                qr_payload_digests=(qr_payload_digest(encode_frame(frame)),),
                physical_qr_payload_indexes=(0,),
                physical_qr_payload_digests=(qr_payload_digest(encode_frame(frame)),),
            )
        )

        with mock.patch(
            "ethernity.render.validation.validate_pdf_has_pages",
            return_value=_Reader("Recovery Document"),
        ):
            with self.assertRaises(RenderProofError) as ctx:
                validate_rendered_pdf_artifact(
                    inputs=inputs,
                    result=result,
                    artifact_label="rendered recovery document",
                )

        self.assertIn("missing fallback render proof", str(ctx.exception))

    def test_kit_index_artifact_validation_checks_expected_inventory_text(self) -> None:
        inputs = RenderInputs(
            frames=(),
            design_name="sentinel",
            output_path="/tmp/recovery_kit_index.pdf",
            context={},
            doc_type="kit_index",
            lineage=RenderLineage(kind="root_backup"),
            qr_payloads=(),
            render_qr=False,
            render_fallback=False,
        )
        result = RenderResult(
            artifact_proof=RenderArtifactProof(
                output_path="/tmp/recovery_kit_index.pdf",
                doc_type="kit_index",
                frame_digests=(),
                encoded_payload_count=0,
                physical_qr_count=0,
            )
        )

        with mock.patch(
            "ethernity.render.validation.validate_pdf_has_pages",
            return_value=_Reader("Recovery Kit Index"),
        ):
            with self.assertRaises(RenderProofError) as ctx:
                validate_rendered_pdf_artifact(
                    inputs=inputs,
                    result=result,
                    artifact_label="rendered recovery kit index",
                    expected_text=("QR-DOC-01",),
                )

        self.assertIn("missing expected inventory rows", str(ctx.exception))
