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
from itertools import product
from pathlib import Path

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.formats.extension_mode import UpdateMode
from ethernity.render import DocumentOrigin, RenderInputs, render_frames_to_pdf
from ethernity.render.checks import extract_pdf_text, validate_pdf_has_pages
from ethernity.render.recovery_meta import build_recovery_meta
from ethernity.render.types import FallbackSection
from ethernity.render.validation import validate_rendered_pdf_document


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
    def test_all_designs_print_update_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for design, mode, doc_type, paper_size in product(
                ("sentinel", "forge", "archive", "ledger", "maritime"),
                UpdateMode,
                ("main", "recovery"),
                ("A4", "Letter", "A5"),
            ):
                with self.subTest(design=design, mode=mode, doc_type=doc_type, paper=paper_size):
                    output_path = Path(tmpdir) / f"{design}-{mode}-{doc_type}.pdf"
                    recovery = doc_type == "recovery"
                    inputs = RenderInputs(
                        frames=(_frame(),),
                        output_path=output_path,
                        context={"paper_size": paper_size},
                        doc_type=doc_type,
                        design_name=design,
                        origin=DocumentOrigin(
                            kind="extension",
                            extension_index=3,
                            update_mode=mode,
                            root_doc_id="0123456789abcdef",
                        ),
                        render_qr=not recovery,
                        render_fallback=recovery,
                        recovery_meta=build_recovery_meta(
                            passphrase=None,
                            quorum_threshold=2,
                            quorum_shares=3,
                            signing_pub=b"\x31" * 32,
                        )
                        if recovery
                        else None,
                        fallback_sections=(FallbackSection(label="MAIN FRAME", frame=_frame()),)
                        if recovery
                        else (),
                    )
                    result = render_frames_to_pdf(inputs)
                    validate_rendered_pdf_document(
                        inputs=inputs,
                        result=result,
                        document_label=f"{design} {mode} {doc_type}",
                    )
                    reader = validate_pdf_has_pages(output_path)
                    text = " ".join(extract_pdf_text(reader).lower().split())
                    required = (
                        "original backup and this update; earlier updates are not required"
                        if mode == UpdateMode.CUMULATIVE
                        else "original backup and every update through this one"
                    )
                    self.assertIn(required, text)
                    for page in reader.pages:
                        page_text = " ".join(page.extract_text().lower().split())
                        self.assertIn("original backup id: 0123456789abcdef", page_text)
                        self.assertIn("update 03", page_text)
                        self.assertIn("update id", page_text)
                        self.assertIn("5555555555555555", page_text)

    def test_render_frames_to_pdf_writes_direct_pdf_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.pdf"
            inputs = RenderInputs(
                frames=(_frame(),),
                output_path=output_path,
                context={"paper_size": "A4"},
                doc_type="main",
                origin=DocumentOrigin(kind="root_backup"),
                render_qr=True,
                render_fallback=False,
            )

            result = render_frames_to_pdf(inputs)

            reader = validate_pdf_has_pages(output_path)
            self.assertEqual(result.document_summary.page_count, len(reader.pages))

    def test_render_frames_to_pdf_rejects_empty_frames_when_qr_or_fallback_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = RenderInputs(
                frames=(),
                output_path=Path(tmpdir) / "out.pdf",
                context={"paper_size": "A4"},
                doc_type="main",
                origin=DocumentOrigin(kind="root_backup"),
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
