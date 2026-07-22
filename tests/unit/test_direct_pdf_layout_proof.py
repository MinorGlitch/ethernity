import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.qr.codec import qr_bytes
from ethernity.render.direct_pdf.components import ImageBox, Panel, TextBox
from ethernity.render.direct_pdf.debug import write_direct_layout_debug_json
from ethernity.render.direct_pdf.layout_proof import build_direct_layout_proof
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    SeparationConstraint,
    build_page_plan,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.text_fit import TextFitPolicy
from ethernity.render.direct_pdf.types import PdfColor, PdfRect, TextStyle
from ethernity.render.types import RenderInputs, RenderLineage


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

    def test_build_direct_layout_proof_identifies_text_components(self) -> None:
        surface = FpdfSurface(page_width_mm=80, page_height_mm=80)
        text = TextBox(
            component_id="title",
            text="Measured title",
            style=TextStyle(family="Helvetica", size_pt=10),
            policy=TextFitPolicy.FAIL,
        ).plan(surface, PdfRect(8, 10, 40, 8))
        page = build_page_plan(
            page_number=1,
            rect=PdfRect(0, 0, 80, 80),
            plans=(text,),
        )

        proof = build_direct_layout_proof((page,))

        self.assertEqual(proof.pages[0].components[0].component_type, "text")

    def test_build_direct_layout_proof_serializes_separation_constraint_results(self) -> None:
        surface = FpdfSurface(page_width_mm=80, page_height_mm=80)
        left = Panel(component_id="left", stroke=PdfColor(0, 0, 0)).plan(
            surface, PdfRect(5, 5, 20, 20)
        )
        right = Panel(component_id="right", stroke=PdfColor(0, 0, 0)).plan(
            surface, PdfRect(30, 5, 20, 20)
        )
        page = build_page_plan(
            page_number=1,
            rect=PdfRect(0, 0, 80, 80),
            plans=(left, right),
            separation_constraints=(
                SeparationConstraint(
                    constraint_id="content-columns",
                    first=ComponentGroup("left-column", ("left",)),
                    second=ComponentGroup("right-column", ("right",)),
                    minimum_clearance_mm=3.0,
                ),
            ),
        )

        proof = build_direct_layout_proof((page,))

        constraint = proof.pages[0].separation_constraints[0]
        self.assertEqual(constraint.constraint_id, "content-columns")
        self.assertEqual(constraint.first_region_id, "left-column")
        self.assertEqual(constraint.second_region_id, "right-column")
        self.assertEqual(constraint.minimum_clearance_mm, 3.0)
        self.assertEqual(constraint.measured_clearance_mm, 5.0)
        self.assertEqual(constraint.checked_pair_count, 1)
        self.assertTrue(constraint.satisfied)

    def test_layout_debug_json_serializes_separation_constraint_results(self) -> None:
        surface = FpdfSurface(page_width_mm=80, page_height_mm=80)
        left = Panel(component_id="left", stroke=PdfColor(0, 0, 0)).plan(
            surface, PdfRect(5, 5, 20, 20)
        )
        right = Panel(component_id="right", stroke=PdfColor(0, 0, 0)).plan(
            surface, PdfRect(30, 5, 20, 20)
        )
        page = build_page_plan(
            page_number=1,
            rect=PdfRect(0, 0, 80, 80),
            plans=(left, right),
            separation_constraints=(
                SeparationConstraint(
                    constraint_id="content-columns",
                    first=ComponentGroup("left-column", ("left",)),
                    second=ComponentGroup("right-column", ("right",)),
                    minimum_clearance_mm=3.0,
                ),
            ),
        )

        with TemporaryDirectory() as tmp:
            debug_path = Path(tmp) / "layout.json"
            inputs = RenderInputs(
                frames=(),
                output_path=Path(tmp) / "unused.pdf",
                context={},
                doc_type="main",
                lineage=RenderLineage(kind="root_backup"),
                render_qr=False,
                render_fallback=False,
                layout_debug_json_path=debug_path,
            )

            write_direct_layout_debug_json(
                inputs=inputs,
                page_plans=(page,),
                style_name="test",
            )

            constraint = json.loads(debug_path.read_text(encoding="utf-8"))["pages"][0][
                "separation_constraints"
            ][0]
            self.assertEqual(constraint["constraint_id"], "content-columns")
            self.assertEqual(constraint["measured_clearance_mm"], 5.0)
            self.assertEqual(constraint["checked_pair_count"], 1)
            self.assertTrue(constraint["satisfied"])

    def test_layout_debug_counts_only_qr_image_components(self) -> None:
        surface = FpdfSurface(page_width_mm=80, page_height_mm=80)
        frame = Panel(component_id="sample-qr-image-frame", stroke=PdfColor(0, 0, 0)).plan(
            surface,
            PdfRect(5, 5, 25, 25),
        )
        qr_image = ImageBox(
            component_id="sample-qr-image",
            image=qr_bytes("layout-debug-qr"),
            image_type="PNG",
        ).plan(surface, PdfRect(7, 7, 21, 21))
        logo = ImageBox(
            component_id="sample-logo-image",
            image=qr_bytes("not-semantic-qr"),
            image_type="PNG",
        ).plan(surface, PdfRect(40, 5, 20, 20))
        page = build_page_plan(
            page_number=1,
            rect=PdfRect(0, 0, 80, 80),
            plans=(frame, qr_image, logo),
        )

        with TemporaryDirectory() as tmp:
            debug_path = Path(tmp) / "layout.json"
            inputs = RenderInputs(
                frames=(),
                output_path=Path(tmp) / "unused.pdf",
                context={},
                doc_type="main",
                lineage=RenderLineage(kind="root_backup"),
                render_qr=False,
                render_fallback=False,
                layout_debug_json_path=debug_path,
            )
            write_direct_layout_debug_json(
                inputs=inputs,
                page_plans=(page,),
                style_name="test",
            )
            qr_count = json.loads(debug_path.read_text(encoding="utf-8"))["pages"][0]["qr_count"]

        self.assertEqual(qr_count, 1)


if __name__ == "__main__":
    unittest.main()
