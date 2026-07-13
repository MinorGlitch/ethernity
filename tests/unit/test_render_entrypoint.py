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

import tempfile
import unittest
from pathlib import Path

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render import RenderInputs, RenderLineage, render_frames_to_pdf
from ethernity.render.proofs import validate_pdf_has_pages


def _frame() -> Frame:
    return Frame(
        version=1,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=b"\x55" * DOC_ID_LEN,
        index=0,
        total=1,
        data=b"payload",
    )


class TestRenderEntrypoint(unittest.TestCase):
    def test_render_frames_to_pdf_writes_direct_pdf_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.pdf"
            inputs = RenderInputs(
                frames=(_frame(),),
                output_path=output_path,
                context={"paper_size": "A4"},
                doc_type="main",
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.artifact_proof.page_count, len(reader.pages))

    def test_render_frames_to_pdf_rejects_empty_frames_when_qr_or_fallback_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = RenderInputs(
                frames=(),
                output_path=Path(tmpdir) / "out.pdf",
                context={"paper_size": "A4"},
                doc_type="main",
                lineage=RenderLineage(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
            )

            with self.assertRaisesRegex(
                ValueError,
                "frames cannot be empty when QR or fallback rendering is enabled",
            ):
                render_frames_to_pdf(inputs)


if __name__ == "__main__":
    unittest.main()
