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

import re
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.render import DocumentOrigin, RenderInputs, render_frames_to_pdf


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
                data=f"payload-{i}".encode(),
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
                design_name="sentinel",
                origin=DocumentOrigin(kind="root_backup"),
                render_fallback=False,
            )
            render_frames_to_pdf(inputs)

            reader = PdfReader(str(output_path))
            # Sentinel has four slots on its first page and nine on continuations.
            self.assertEqual(len(reader.pages), 2)
            for page, expected in zip(reader.pages, (range(1, 5), range(5, 14)), strict=True):
                labels = re.findall(r"\bSEGMENT (\d+)\b", page.extract_text().upper())
                self.assertEqual([int(label) for label in labels], list(expected))


if __name__ == "__main__":
    unittest.main()
