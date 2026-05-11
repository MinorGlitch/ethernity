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

from ethernity.cli.features.backup.execution import _validate_rendered_pdf_artifact
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.proofs import RenderProofError, frame_digest
from ethernity.render.types import RenderArtifactProof, RenderInputs, RenderResult


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Reader:
    def __init__(self, text: str) -> None:
        self.pages = [_Page(text)]


class TestBackupRenderProofs(unittest.TestCase):
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
            template_path="/tmp/recovery.html.j2",
            output_path="/tmp/recovery.pdf",
            context={},
            doc_type="recovery",
        )
        result = RenderResult(
            artifact_proof=RenderArtifactProof(
                output_path="/tmp/recovery.pdf",
                doc_type="recovery",
                frame_digests=(frame_digest(frame),),
                qr_payload_count=1,
            )
        )

        with mock.patch(
            "ethernity.cli.features.backup.execution.validate_pdf_has_pages",
            return_value=_Reader("Recovery Document"),
        ):
            with self.assertRaises(RenderProofError) as ctx:
                _validate_rendered_pdf_artifact(
                    inputs=inputs,
                    result=result,
                    artifact_label="rendered recovery document",
                    fallback_frames=(frame,),
                )

        self.assertIn("missing fallback render proof", str(ctx.exception))

    def test_kit_index_artifact_validation_checks_expected_inventory_text(self) -> None:
        inputs = RenderInputs(
            frames=(),
            template_path="/tmp/kit_index.html.j2",
            output_path="/tmp/recovery_kit_index.pdf",
            context={},
            doc_type="kit_index",
            qr_payloads=(),
            render_qr=False,
            render_fallback=False,
        )
        result = RenderResult(
            artifact_proof=RenderArtifactProof(
                output_path="/tmp/recovery_kit_index.pdf",
                doc_type="kit_index",
                frame_digests=(),
                qr_payload_count=0,
            )
        )

        with mock.patch(
            "ethernity.cli.features.backup.execution.validate_pdf_has_pages",
            return_value=_Reader("Recovery Kit Index"),
        ):
            with self.assertRaises(RenderProofError) as ctx:
                _validate_rendered_pdf_artifact(
                    inputs=inputs,
                    result=result,
                    artifact_label="rendered recovery kit index",
                    expected_text=("QR-DOC-01",),
                )

        self.assertIn("missing expected inventory rows", str(ctx.exception))
