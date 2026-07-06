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

import unittest

from ethernity.render.layout_policy import (
    adjust_layout_fallback_capacity,
    adjust_page_fallback_capacity,
)
from ethernity.render.template_style import (
    FallbackLayoutProfile,
    RecoveryFallbackLayout,
    ShardFallbackLayout,
    TemplateCapabilities,
)
from ethernity.render.types import Layout


def _advanced_capabilities() -> TemplateCapabilities:
    return TemplateCapabilities(
        advanced_fallback_layout=True,
        fallback_layout=FallbackLayoutProfile(
            recovery=RecoveryFallbackLayout(
                line_height_floor_mm=1.0,
                first_page_footer_reserve_mm=100.0,
                continuation_footer_reserve_mm=100.0,
                meta_baseline_lines=0,
                meta_extra_line_mm=0.0,
                meta_section_overhead_mm=0.0,
                first_page_text_width_bonus_mm=0.0,
                continuation_text_width_bonus_mm=0.0,
            ),
            shard=ShardFallbackLayout(
                line_height_floor_mm=1.0,
                first_page_payload_zone_height_mm=0.0,
                continuation_payload_zone_height_mm=0.0,
            ),
            signing_key_shard=ShardFallbackLayout(
                line_height_floor_mm=1.0,
                first_page_payload_zone_height_mm=0.0,
                continuation_payload_zone_height_mm=0.0,
            ),
        ),
    )


def _layout() -> Layout:
    return Layout(
        page_w=100.0,
        page_h=100.0,
        margin=0.0,
        header_height=0.0,
        instructions_y=0.0,
        content_start_y=0.0,
        usable_w=100.0,
        usable_h=100.0,
        usable_h_grid=100.0,
        qr_size=10.0,
        gap=0.0,
        cols=1,
        rows=1,
        per_page=1,
        gap_y_override=None,
        fallback_width=100.0,
        line_length=10,
        line_height=1.0,
        fallback_lines_per_page=10,
        fallback_font="Courier",
        fallback_size=8.0,
        text_gap=0.0,
        min_lines=1,
        key_lines=(),
        total_pages=1,
    )


class TestLayoutPolicy(unittest.TestCase):
    def test_advanced_layout_capacity_can_be_zero_for_empty_payload_zone(self) -> None:
        _line_height, lines = adjust_layout_fallback_capacity(
            capabilities=_advanced_capabilities(),
            doc_type="shard",
            content_start_y=0.0,
            page_h=100.0,
            margin=0.0,
            line_height=1.0,
            fallback_lines_per_page_val=10,
            include_recovery_metadata_footer=False,
            recovery_meta_lines_extra=0,
            include_instructions=True,
        )

        self.assertEqual(lines, 0)

    def test_page_capacity_can_be_zero_for_empty_payload_zone(self) -> None:
        lines = adjust_page_fallback_capacity(
            capabilities=_advanced_capabilities(),
            doc_type="shard",
            page_layout=_layout(),
            lines_capacity=10,
            page_idx=0,
            recovery_meta_lines_extra=0,
        )

        self.assertEqual(lines, 0)


if __name__ == "__main__":
    unittest.main()
