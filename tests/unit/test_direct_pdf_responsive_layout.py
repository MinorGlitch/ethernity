from __future__ import annotations

import unittest

from hypothesis import given, strategies as st

from ethernity.render.direct_pdf.responsive_layout import (
    GridPolicy,
    Insets,
    inset_rect,
    resolve_grid,
    resolve_page_regions,
)
from ethernity.render.direct_pdf.types import PdfRect


class TestDirectPdfResponsiveLayout(unittest.TestCase):
    def test_page_regions_follow_arbitrary_page_dimensions(self) -> None:
        regions = resolve_page_regions(
            PdfRect(0.0, 0.0, 203.0, 254.0),
            safe_insets=Insets(top_mm=11.0, right_mm=13.0, bottom_mm=17.0, left_mm=19.0),
            header_height_mm=24.0,
            footer_height_mm=12.0,
            header_body_gap_mm=3.0,
            body_footer_gap_mm=5.0,
        )

        self.assertEqual(regions.safe, PdfRect(19.0, 11.0, 171.0, 226.0))
        self.assertEqual(regions.header, PdfRect(19.0, 11.0, 171.0, 24.0))
        self.assertEqual(regions.body, PdfRect(19.0, 38.0, 171.0, 182.0))
        self.assertEqual(regions.footer, PdfRect(19.0, 225.0, 171.0, 12.0))

    def test_page_regions_fail_when_fixed_regions_exhaust_body(self) -> None:
        with self.assertRaisesRegex(ValueError, "leave no usable body"):
            resolve_page_regions(
                PdfRect(0.0, 0.0, 100.0, 80.0),
                safe_insets=Insets.uniform(10.0),
                header_height_mm=35.0,
                footer_height_mm=25.0,
                header_body_gap_mm=1.0,
            )

    def test_inset_rect_fails_instead_of_returning_zero_area(self) -> None:
        with self.assertRaisesRegex(ValueError, "leave no usable rectangle"):
            inset_rect(PdfRect(0.0, 0.0, 20.0, 20.0), Insets.uniform(10.0))

    def test_grid_maximizes_capacity_before_item_size(self) -> None:
        grid = resolve_grid(
            PdfRect(10.0, 20.0, 182.0, 225.0),
            GridPolicy(
                max_columns=3,
                max_rows=4,
                preferred_item_width_mm=58.0,
                preferred_item_height_mm=58.0,
                minimum_item_width_mm=42.0,
                minimum_item_height_mm=42.0,
                minimum_column_gap_mm=3.0,
                minimum_row_gap_mm=3.0,
                preserve_item_aspect_ratio=True,
            ),
        )

        self.assertEqual((grid.columns, grid.rows, grid.capacity), (3, 4, 12))
        self.assertAlmostEqual(grid.item_width_mm, 54.0)
        self.assertAlmostEqual(grid.item_height_mm, 54.0)

    def test_grid_uses_physical_minimums_to_reject_too_small_pages(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot satisfy minimum grid geometry"):
            resolve_grid(
                PdfRect(0.0, 0.0, 80.0, 80.0),
                GridPolicy(
                    max_columns=3,
                    max_rows=4,
                    preferred_item_width_mm=90.0,
                    preferred_item_height_mm=90.0,
                    minimum_item_width_mm=90.0,
                    minimum_item_height_mm=90.0,
                ),
            )

    def test_grid_places_partial_rows_without_assuming_a_page_name(self) -> None:
        grid = resolve_grid(
            PdfRect(10.0, 20.0, 180.0, 220.0),
            GridPolicy(
                max_columns=3,
                max_rows=4,
                preferred_item_width_mm=50.0,
                preferred_item_height_mm=50.0,
                minimum_item_width_mm=40.0,
                minimum_item_height_mm=40.0,
                minimum_column_gap_mm=4.0,
                minimum_row_gap_mm=4.0,
                horizontal_distribution="space_between",
                vertical_distribution="center",
            ),
        )

        rects = grid.item_rects(5)

        self.assertEqual(len(rects), 5)
        self.assertAlmostEqual(rects[0].x_mm, 10.0)
        self.assertAlmostEqual(rects[2].right_mm, 190.0)
        self.assertAlmostEqual(rects[3].x_mm, 10.0)
        self.assertAlmostEqual(rects[4].right_mm, 190.0)
        self.assertGreater(rects[0].y_mm, 20.0)
        self.assertLess(rects[-1].bottom_mm, 240.0)

    def test_grid_rejects_more_items_than_measured_capacity(self) -> None:
        grid = resolve_grid(
            PdfRect(0.0, 0.0, 100.0, 100.0),
            GridPolicy(
                max_columns=2,
                max_rows=2,
                preferred_item_width_mm=45.0,
                preferred_item_height_mm=45.0,
                minimum_item_width_mm=40.0,
                minimum_item_height_mm=40.0,
            ),
        )

        with self.assertRaisesRegex(ValueError, "exceeds resolved grid capacity"):
            grid.item_rects(5)

    @given(
        width_mm=st.floats(
            min_value=90.0,
            max_value=400.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        height_mm=st.floats(
            min_value=90.0,
            max_value=500.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_resolved_grid_never_places_items_outside_arbitrary_container(
        self,
        width_mm: float,
        height_mm: float,
    ) -> None:
        container = PdfRect(7.0, 11.0, width_mm, height_mm)
        grid = resolve_grid(
            container,
            GridPolicy(
                max_columns=3,
                max_rows=4,
                preferred_item_width_mm=58.0,
                preferred_item_height_mm=58.0,
                minimum_item_width_mm=40.0,
                minimum_item_height_mm=40.0,
                minimum_column_gap_mm=2.0,
                minimum_row_gap_mm=2.0,
                preserve_item_aspect_ratio=True,
                horizontal_distribution="space_between",
                vertical_distribution="space_between",
            ),
        )

        rects = grid.item_rects(grid.capacity, reserve_all_rows=True)

        for rect in rects:
            self.assertGreaterEqual(rect.x_mm, container.x_mm - 0.01)
            self.assertGreaterEqual(rect.y_mm, container.y_mm - 0.01)
            self.assertLessEqual(rect.right_mm, container.right_mm + 0.01)
            self.assertLessEqual(rect.bottom_mm, container.bottom_mm + 0.01)
        for index, first in enumerate(rects):
            for second in rects[index + 1 :]:
                separated = (
                    first.right_mm <= second.x_mm + 0.01
                    or second.right_mm <= first.x_mm + 0.01
                    or first.bottom_mm <= second.y_mm + 0.01
                    or second.bottom_mm <= first.y_mm + 0.01
                )
                self.assertTrue(separated)


if __name__ == "__main__":
    unittest.main()
