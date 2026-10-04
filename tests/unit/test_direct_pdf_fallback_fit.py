from __future__ import annotations

import unittest
from dataclasses import replace

from ethernity.encoding.chunking import fallback_lines_to_frame
from ethernity.encoding.framing import DOC_ID_LEN, VERSION, Frame, FrameType
from ethernity.render.direct_pdf.fallback_fit import (
    SinglePageFallbackProfile,
    fit_single_page_fallback,
)
from ethernity.render.direct_pdf.fallback_layout import FallbackTitleEntry, fallback_entries
from ethernity.render.direct_pdf.surface import FpdfSurface
from ethernity.render.direct_pdf.types import PdfRect, TextStyle
from ethernity.render.types import FallbackSection


def _section(data: bytes = b"x" * 1000) -> FallbackSection:
    return FallbackSection(
        label="SHARD PAYLOAD",
        frame=Frame(
            version=VERSION,
            frame_type=FrameType.KEY_DOCUMENT,
            doc_id=b"s" * DOC_ID_LEN,
            index=0,
            total=1,
            data=data,
        ),
    )


class TestSinglePageFallbackFit(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = FpdfSurface(page_width_mm=210.0, page_height_mm=297.0)
        self.profile = SinglePageFallbackProfile(
            columns=1,
            row_height_mm=3.0,
            body_style=TextStyle(family="Courier", size_pt=6.0),
            column_gap_mm=4.0,
        )
        self.area = PdfRect(0.0, 0.0, 180.0, 63.0)

    def test_preserves_caller_preference_and_round_trips_payload(self) -> None:
        section = _section()
        result = fit_single_page_fallback(
            self.surface,
            (section,),
            area=self.area,
            profiles=(self.profile, replace(self.profile, columns=2)),
            group_size=4,
            overflow_message="too large",
        )
        self.assertEqual(result.profile_index, 0)
        self.assertEqual(fallback_lines_to_frame(result.sections[0].lines), section.frame)

    def test_dense_columns_rescue_a_profile_without_room_for_all_rows(self) -> None:
        section = _section()
        profiles = (
            replace(self.profile, row_height_mm=12.0),
            replace(self.profile, columns=2),
        )
        result = fit_single_page_fallback(
            self.surface,
            (section,),
            area=self.area,
            profiles=profiles,
            group_size=4,
            overflow_message="too large",
        )
        self.assertEqual(result.profile_index, 1)
        self.assertEqual(fallback_lines_to_frame(result.sections[0].lines), section.frame)
        with self.assertRaisesRegex(ValueError, "too large"):
            fit_single_page_fallback(
                self.surface,
                (section,),
                area=replace(self.area, height_mm=1.0),
                profiles=profiles,
                group_size=4,
                overflow_message="too large",
            )

    def test_zero_capacity_profile_can_yield_to_a_fitting_profile(self) -> None:
        result = fit_single_page_fallback(
            self.surface,
            (_section(b"short"),),
            area=self.area,
            profiles=(replace(self.profile, row_height_mm=100.0), self.profile),
            group_size=4,
            overflow_message="too large",
        )
        self.assertEqual(result.profile_index, 1)

    def test_local_title_policy_changes_capacity_without_changing_encoding(self) -> None:
        section = _section(b"short")
        initial = fit_single_page_fallback(
            self.surface,
            (section,),
            area=self.area,
            profiles=(self.profile,),
            group_size=4,
            overflow_message="too large",
        )
        area = replace(self.area, height_mm=(len(initial.entries) - 1) * self.profile.row_height_mm)
        with self.assertRaisesRegex(ValueError, "too large"):
            fit_single_page_fallback(
                self.surface,
                (section,),
                area=area,
                profiles=(self.profile,),
                group_size=4,
                overflow_message="too large",
            )
        result = fit_single_page_fallback(
            self.surface,
            (section,),
            area=area,
            profiles=(self.profile,),
            group_size=4,
            overflow_message="too large",
            entries_builder=lambda sections: tuple(
                entry
                for entry in fallback_entries(sections)
                if not isinstance(entry, FallbackTitleEntry)
            ),
        )
        self.assertEqual(result.sections, initial.sections)
        self.assertEqual(len(result.entries), len(initial.entries) - 1)

    def test_rejects_invalid_geometry(self) -> None:
        for changes in (
            {"columns": 0},
            {"row_height_mm": float("nan")},
            {"column_gap_mm": -1.0},
            {"horizontal_padding_mm": float("inf")},
            {"payload_inset_mm": self.area.width_mm},
            {"reserved_height_mm": -1.0},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                fit_single_page_fallback(
                    self.surface,
                    (_section(),),
                    area=self.area,
                    profiles=(replace(self.profile, **changes),),
                    group_size=4,
                    overflow_message="too large",
                )


if __name__ == "__main__":
    unittest.main()
