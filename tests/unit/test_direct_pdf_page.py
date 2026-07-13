import unittest
from dataclasses import dataclass

from ethernity.render.direct_pdf.components import Panel, Rule
from ethernity.render.direct_pdf.page import (
    ComponentGroup,
    LayoutRegion,
    SeparationConstraint,
    build_page_plan,
)
from ethernity.render.direct_pdf.surface import FpdfSurface, PdfSurface
from ethernity.render.direct_pdf.types import PdfColor, PdfRect


class TestDirectPdfPagePlan(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = FpdfSurface(page_width_mm=80, page_height_mm=80)

    def test_page_plan_aggregates_component_ids_and_overflow_status(self) -> None:
        panel = Panel(component_id="panel", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 5, 40, 30)
        )
        rule = Rule(component_id="rule", color=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 40, 40, 0.4)
        )

        page = build_page_plan(
            page_number=1,
            rect=PdfRect(0, 0, 80, 80),
            plans=(panel, rule),
        )

        self.assertEqual(page.proof.component_ids, ("panel", "rule"))
        self.assertEqual(page.proof.overflow_component_ids, ())
        self.assertFalse(page.proof.overflow)

    def test_page_plan_rejects_duplicate_component_ids(self) -> None:
        first = Panel(component_id="same", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 5, 20, 20)
        )
        second = Rule(component_id="same", color=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 30, 20, 0.4)
        )

        with self.assertRaisesRegex(ValueError, "duplicate component id"):
            build_page_plan(page_number=1, rect=PdfRect(0, 0, 80, 80), plans=(first, second))

    def test_page_plan_rejects_component_rect_outside_page_bounds(self) -> None:
        panel = Panel(component_id="outside", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(70, 70, 20, 20)
        )

        with self.assertRaisesRegex(ValueError, "component outside page bounds: outside"):
            build_page_plan(page_number=1, rect=PdfRect(0, 0, 80, 80), plans=(panel,))

    def test_page_plan_rejects_used_rect_outside_assigned_bounds(self) -> None:
        proof = _FakeProof(
            component_id="bad-text",
            rect=PdfRect(10, 10, 20, 20),
            used_rect=PdfRect(10, 10, 24, 10),
        )
        plan = _FakePlan(component_id="bad-text", proof=proof)

        with self.assertRaisesRegex(
            ValueError,
            "component used rect outside assigned bounds: bad-text",
        ):
            build_page_plan(page_number=1, rect=PdfRect(0, 0, 80, 80), plans=(plan,))

    def test_page_plan_allows_intentional_containment_without_a_constraint(self) -> None:
        background = Panel(component_id="background", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 5, 50, 50)
        )
        child = Panel(component_id="child", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(10, 10, 20, 20)
        )

        page = build_page_plan(
            page_number=1,
            rect=PdfRect(0, 0, 80, 80),
            plans=(background, child),
        )

        self.assertFalse(page.proof.overflow)
        self.assertEqual(page.proof.separation_constraints, ())

    def test_page_plan_allows_boundary_touching_with_zero_clearance(self) -> None:
        left = Panel(component_id="left", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 5, 20, 20)
        )
        right = Panel(component_id="right", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(25, 5, 20, 20)
        )

        page = build_page_plan(
            page_number=1,
            rect=PdfRect(0, 0, 80, 80),
            plans=(left, right),
            separation_constraints=(
                SeparationConstraint(
                    constraint_id="columns-do-not-overlap",
                    first=ComponentGroup("left-column", ("left",)),
                    second=ComponentGroup("right-column", ("right",)),
                ),
            ),
        )

        proof = page.proof.separation_constraints[0]
        self.assertTrue(proof.satisfied)
        self.assertEqual(proof.measured_clearance_mm, 0.0)
        self.assertEqual(proof.checked_pair_count, 1)

    def test_page_plan_accepts_clearance_equal_to_declared_minimum(self) -> None:
        left = Panel(component_id="left", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 5, 20, 20)
        )
        right = Panel(component_id="right", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(27, 5, 20, 20)
        )

        page = build_page_plan(
            page_number=1,
            rect=PdfRect(0, 0, 80, 80),
            plans=(left, right),
            separation_constraints=(
                SeparationConstraint(
                    constraint_id="column-gutter",
                    first=ComponentGroup("left-column", ("left",)),
                    second=ComponentGroup("right-column", ("right",)),
                    minimum_clearance_mm=2.0,
                ),
            ),
        )

        self.assertEqual(page.proof.separation_constraints[0].measured_clearance_mm, 2.0)

    def test_page_plan_rejects_overlap_with_zero_clearance(self) -> None:
        left = Panel(component_id="left", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 5, 20, 20)
        )
        right = Panel(component_id="right", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(24, 5, 20, 20)
        )

        with self.assertRaisesRegex(
            ValueError,
            r"layout separation constraint 'columns-do-not-overlap' violated:.*"
            r"rectangles overlap",
        ):
            build_page_plan(
                page_number=1,
                rect=PdfRect(0, 0, 80, 80),
                plans=(left, right),
                separation_constraints=(
                    SeparationConstraint(
                        constraint_id="columns-do-not-overlap",
                        first=ComponentGroup("left-column", ("left",)),
                        second=ComponentGroup("right-column", ("right",)),
                    ),
                ),
            )

    def test_page_plan_rejects_clearance_below_declared_minimum(self) -> None:
        left = Panel(component_id="left", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 5, 20, 20)
        )
        right = Panel(component_id="right", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(27, 5, 20, 20)
        )

        with self.assertRaisesRegex(
            ValueError,
            r"layout separation constraint 'column-gutter' violated:.*"
            r"required 2\.100 mm, measured 2\.000 mm",
        ):
            build_page_plan(
                page_number=1,
                rect=PdfRect(0, 0, 80, 80),
                plans=(left, right),
                separation_constraints=(
                    SeparationConstraint(
                        constraint_id="column-gutter",
                        first=ComponentGroup("left-column", ("left",)),
                        second=ComponentGroup("right-column", ("right",)),
                        minimum_clearance_mm=2.1,
                    ),
                ),
            )

    def test_page_plan_rejects_constraint_with_missing_component_id(self) -> None:
        qr = Panel(component_id="qr", stroke=PdfColor(0, 0, 0)).plan(
            self.surface, PdfRect(5, 5, 20, 20)
        )

        with self.assertRaisesRegex(
            ValueError,
            "constraint 'qr-footer' group 'qr-grid' references missing component id: missing-qr",
        ):
            build_page_plan(
                page_number=1,
                rect=PdfRect(0, 0, 80, 80),
                plans=(qr,),
                separation_constraints=(
                    SeparationConstraint(
                        constraint_id="qr-footer",
                        first=ComponentGroup("qr-grid", ("qr", "missing-qr")),
                        second=LayoutRegion("footer-zone", PdfRect(5, 60, 70, 10)),
                    ),
                ),
            )

    def test_component_group_rejects_duplicate_component_ids(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "duplicate component id in component group: qr",
        ):
            ComponentGroup("qr-grid", ("qr", "qr"))

    def test_page_plan_rejects_duplicate_constraint_ids(self) -> None:
        first = SeparationConstraint(
            constraint_id="safe-zones",
            first=LayoutRegion("header-zone", PdfRect(0, 0, 80, 10)),
            second=LayoutRegion("footer-zone", PdfRect(0, 70, 80, 10)),
        )
        second = SeparationConstraint(
            constraint_id="safe-zones",
            first=LayoutRegion("content-zone", PdfRect(0, 15, 80, 40)),
            second=LayoutRegion("footer-zone", PdfRect(0, 70, 80, 10)),
        )

        with self.assertRaisesRegex(
            ValueError,
            "duplicate separation constraint id in page plan: safe-zones",
        ):
            build_page_plan(
                page_number=1,
                rect=PdfRect(0, 0, 80, 80),
                plans=(),
                separation_constraints=(first, second),
            )

    def test_page_plan_rejects_forge_style_qr_footer_collision_when_constrained(self) -> None:
        qr_last_row = Panel(component_id="qr-last-row", stroke=PdfColor(0, 0, 0)).plan(
            FpdfSurface(page_width_mm=210, page_height_mm=297),
            PdfRect(17, 220, 55, 60),
        )
        page_rect = PdfRect(0, 0, 210, 297)

        unconstrained = build_page_plan(page_number=2, rect=page_rect, plans=(qr_last_row,))
        self.assertFalse(unconstrained.proof.overflow)

        with self.assertRaisesRegex(
            ValueError,
            r"constraint 'qr-footer' violated: component 'qr-last-row'.*"
            r"region 'footer-zone'.*rectangles overlap",
        ):
            build_page_plan(
                page_number=2,
                rect=page_rect,
                plans=(qr_last_row,),
                separation_constraints=(
                    SeparationConstraint(
                        constraint_id="qr-footer",
                        first=ComponentGroup("qr-grid", ("qr-last-row",)),
                        second=LayoutRegion("footer-zone", PdfRect(14, 263, 182, 20)),
                        minimum_clearance_mm=3.5,
                    ),
                ),
            )


@dataclass(frozen=True)
class _FakeProof:
    component_id: str
    rect: PdfRect
    used_rect: PdfRect
    overflow: bool = False


@dataclass(frozen=True)
class _FakePlan:
    component_id: str
    proof: _FakeProof

    def paint(self, surface: PdfSurface) -> None:
        _ = surface


if __name__ == "__main__":
    unittest.main()
