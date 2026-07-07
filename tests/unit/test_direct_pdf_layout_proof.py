import unittest

from ethernity.render.direct_pdf import (
    FpdfSurface,
    Panel,
    PdfColor,
    PdfRect,
    TextBox,
    TextFitPolicy,
    TextStyle,
    build_direct_layout_proof,
    build_page_plan,
)


class TestDirectPdfLayoutProof(unittest.TestCase):
    def test_build_direct_layout_proof_exposes_component_geometry(self) -> None:
        surface = FpdfSurface(page_width_mm=80, page_height_mm=80)
        panel = Panel(component_id="panel", stroke=PdfColor(0, 0, 0)).plan(
            surface, PdfRect(5, 5, 40, 30)
        )
        text = TextBox(
            component_id="title",
            text="Measured title",
            style=TextStyle(family="Helvetica", size_pt=10),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(8, 10, 40, 8))
        page = build_page_plan(
            page_number=1,
            rect=PdfRect(0, 0, 80, 80),
            plans=(panel, text),
        )

        proof = build_direct_layout_proof((page,))

        self.assertEqual(proof.backend, "direct_pdf")
        self.assertEqual(proof.page_count, 1)
        self.assertFalse(proof.overflow)
        self.assertEqual(proof.pages[0].component_ids, ("panel", "title"))
        self.assertEqual(proof.pages[0].components[0].component_type, "panel")
        self.assertIsNotNone(proof.pages[0].components[1].used_rect)
        self.assertEqual(proof.pages[0].components[1].policy, "fail")
        self.assertEqual(proof.pages[0].components[1].line_count, 1)


if __name__ == "__main__":
    unittest.main()
