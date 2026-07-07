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

from pypdf import PdfReader

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render import RenderInputs, RenderLineage, render_frames_to_pdf


class TestPdfPageCount(unittest.TestCase):
    def test_multi_page_output(self) -> None:
        doc_id = b"\x77" * DOC_ID_LEN
        frames = [
            Frame(
                version=1,
                frame_type=FrameType.MAIN_DOCUMENT,
                doc_id=doc_id,
                index=i,
                total=13,
                data=f"payload-{i}".encode("utf-8"),
            )
            for i in range(13)
        ]
        context = {
            "paper_size": "A4",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.pdf"
            inputs = RenderInputs(
                frames=frames,
                output_path=output_path,
                context=context,
                doc_type="main",
                lineage=RenderLineage(kind="root_backup"),
                render_fallback=False,
            )
            render_frames_to_pdf(inputs)

            reader = PdfReader(str(output_path))
            self.assertEqual(len(reader.pages), 2)


if __name__ == "__main__":
    unittest.main()
