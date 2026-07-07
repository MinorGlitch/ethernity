import unittest
from dataclasses import dataclass

from ethernity.render.direct_pdf import (
    FpdfSurface,
    Panel,
    PdfColor,
    PdfRect,
    PdfSurface,
    Rule,
    build_page_plan,
)


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
