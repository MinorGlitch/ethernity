import unittest

from ethernity.qr.codec import qr_bytes
from ethernity.render.direct_pdf.components import (
    Ellipse,
    ImageBox,
    Line,
    Panel,
    Rule,
)
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import PdfColor, PdfRect


class TestDirectPdfBoxComponents(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = FpdfSurface(page_width_mm=100, page_height_mm=100)

    def test_panel_requires_stroke_or_fill(self) -> None:
        with self.assertRaisesRegex(ValueError, "stroke or fill is required"):
            Panel(component_id="empty-panel")

    def test_panel_plan_records_geometry_layout(self) -> None:
        rect = PdfRect(10, 12, 30, 18)
        panel = Panel(
            component_id="metadata-panel",
            stroke=PdfColor(10, 20, 30),
            fill=PdfColor(240, 240, 240),
            line_width_mm=0.4,
        )

        plan = panel.plan(self.surface, rect)

        self.assertEqual(plan.rect, rect)
        self.assertEqual(plan.layout.component_type, "panel")
        self.assertFalse(plan.layout.overflow)

    def test_panel_plan_records_corner_radius(self) -> None:
        rect = PdfRect(10, 12, 30, 18)
        panel = Panel(
            component_id="rounded-panel",
            stroke=PdfColor(10, 20, 30),
            line_width_mm=0.4,
            corner_radius_mm=3.0,
        )

        plan = panel.plan(self.surface, rect)

        self.assertEqual(plan.corner_radius_mm, 3.0)
        self.assertFalse(plan.layout.overflow)

    def test_panel_rejects_oversized_corner_radius(self) -> None:
        panel = Panel(
            component_id="rounded-panel",
            stroke=PdfColor(10, 20, 30),
            corner_radius_mm=6.0,
        )

        with self.assertRaisesRegex(ValueError, "rounded-panel corner radius is too large"):
            panel.plan(self.surface, PdfRect(10, 12, 20, 10))

    def test_ellipse_plan_records_geometry_layout(self) -> None:
        rect = PdfRect(10, 12, 8, 8)
        ellipse = Ellipse(
            component_id="step-marker",
            stroke=PdfColor(0, 0, 0),
            fill=PdfColor(0, 0, 0),
            line_width_mm=0.2,
        )

        plan = ellipse.plan(self.surface, rect)

        self.assertEqual(plan.rect, rect)
        self.assertEqual(plan.layout.component_type, "ellipse")
        self.assertFalse(plan.layout.overflow)

    def test_rule_plan_rejects_zero_height(self) -> None:
        rule = Rule(component_id="divider", color=PdfColor(0, 0, 0))

        with self.assertRaisesRegex(ValueError, "divider height must be positive"):
            rule.plan(self.surface, PdfRect(0, 0, 20, 0))

    def test_line_plan_records_bounded_geometry_layout(self) -> None:
        line = Line(component_id="hatch-line", color=PdfColor(225, 225, 225))

        plan = line.plan(
            self.surface,
            start_x_mm=10,
            start_y_mm=12,
            end_x_mm=18,
            end_y_mm=20,
        )

        self.assertEqual(plan.layout.component_type, "line")
        self.assertEqual(plan.layout.rect, PdfRect(10, 12, 8, 8))
        self.assertFalse(plan.layout.overflow)

    def test_line_plan_rejects_zero_length(self) -> None:
        line = Line(component_id="empty-line", color=PdfColor(225, 225, 225))

        with self.assertRaisesRegex(ValueError, "empty-line line must have non-zero length"):
            line.plan(self.surface, start_x_mm=10, start_y_mm=12, end_x_mm=10, end_y_mm=12)

    def test_image_box_rejects_empty_image(self) -> None:
        with self.assertRaisesRegex(ValueError, "image must be non-empty"):
            ImageBox(component_id="qr", image=b"")

    def test_image_box_plan_records_geometry_layout(self) -> None:
        rect = PdfRect(12, 12, 28, 28)
        image = qr_bytes("box-component-layout", scale=2)
        image_box = ImageBox(component_id="qr-1", image=image, image_type="PNG")

        plan = image_box.plan(self.surface, rect)

        self.assertEqual(plan.rect, rect)
        self.assertEqual(plan.image, image)
        self.assertEqual(plan.layout.component_type, "image")
        self.assertFalse(plan.layout.overflow)


if __name__ == "__main__":
    unittest.main()
