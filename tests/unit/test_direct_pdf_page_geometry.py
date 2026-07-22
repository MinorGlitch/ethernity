from __future__ import annotations

import unittest
from dataclasses import replace

from ethernity.encoding.framing import DOC_ID_LEN, Frame, FrameType
from ethernity.page_sizes import PaperSize
from ethernity.render.direct_pdf.page_geometry import (
    PageGeometry,
    page_geometry,
    registered_paper_sizes,
    resolve_page_geometry,
)
from ethernity.render.types import RenderInputs, RenderLineage


def _inputs(paper_size: str) -> RenderInputs:
    frame = Frame(
        version=1,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=b"\x42" * DOC_ID_LEN,
        index=0,
        total=1,
        data=b"page-geometry",
    )
    return RenderInputs(
        frames=(frame,),
        output_path="ignored.pdf",
        context={"paper_size": paper_size},
        doc_type="main",
        lineage=RenderLineage(kind="root_backup"),
        render_qr=True,
        render_fallback=False,
    )


class TestDirectPdfPageGeometry(unittest.TestCase):
    def test_page_geometry_rejects_uncontracted_landscape_orientation(self) -> None:
        with self.assertRaisesRegex(ValueError, "portrait orientation"):
            PageGeometry("LANDSCAPE", 297.0, 210.0)

    def test_registered_geometry_is_case_insensitive(self) -> None:
        geometry = page_geometry("Letter")

        self.assertEqual(geometry.paper_size, "LETTER")
        self.assertAlmostEqual(geometry.width_mm, 215.9)
        self.assertAlmostEqual(geometry.height_mm, 279.4)

    def test_default_resolution_accepts_every_registered_size(self) -> None:
        self.assertEqual(registered_paper_sizes(), frozenset({"a4", "letter"}))

        for paper_size in registered_paper_sizes():
            with self.subTest(paper_size=paper_size):
                self.assertEqual(
                    resolve_page_geometry(_inputs(paper_size)), page_geometry(paper_size)
                )

    def test_renderer_can_restrict_a_registered_size_explicitly(self) -> None:
        with self.assertRaisesRegex(ValueError, "supports paper sizes: A4"):
            resolve_page_geometry(
                _inputs("LETTER"),
                supported_paper_sizes=frozenset({"A4"}),
            )

    def test_unknown_size_reports_the_central_registry(self) -> None:
        with self.assertRaisesRegex(ValueError, "registered paper sizes: A4, LETTER"):
            page_geometry("TABLOID")

    def test_explicit_dimensions_support_future_unregistered_page_sizes(self) -> None:
        inputs = replace(
            _inputs("A4"),
            context={"paper_size": "future-portrait"},
            page_size=PaperSize("FUTURE-PORTRAIT", "Future portrait", 190.0, 260.0),
        )

        geometry = resolve_page_geometry(inputs)

        self.assertEqual(geometry.paper_size, "FUTURE-PORTRAIT")
        self.assertEqual(geometry.rect.width_mm, 190.0)
        self.assertEqual(geometry.rect.height_mm, 260.0)

    def test_explicit_dimensions_do_not_require_a_context_name(self) -> None:
        inputs = replace(
            _inputs("A4"),
            context={},
            page_size=PaperSize("CUSTOM", "Custom", 190.0, 260.0),
        )

        geometry = resolve_page_geometry(inputs)

        self.assertEqual(geometry.paper_size, "CUSTOM")
        self.assertEqual(geometry.rect.width_mm, 190.0)
        self.assertEqual(geometry.rect.height_mm, 260.0)

    def test_registered_name_rejects_mismatched_explicit_dimensions(self) -> None:
        inputs = replace(
            _inputs("A4"),
            page_size=PaperSize("A4", "A4", 190.0, 260.0),
        )

        with self.assertRaisesRegex(ValueError, "typed dimensions.*do not match"):
            resolve_page_geometry(inputs)

    def test_typed_page_size_must_match_display_context_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicts with context paper_size"):
            replace(
                _inputs("A4"),
                page_size=PaperSize("CUSTOM", "Custom", 190.0, 260.0),
            )


if __name__ == "__main__":
    unittest.main()
