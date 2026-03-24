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

from __future__ import annotations

import unittest
from pathlib import Path

from ethernity.render.copy_catalog import build_copy_bundle
from ethernity.render.templating import render_template

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ETHERNITY_ROOT = _PROJECT_ROOT / "src" / "ethernity"


class TestTemplateOverflowGuards(unittest.TestCase):
    def test_sentinel_recovery_template_removes_capacity_compensation_logic(self) -> None:
        template_path = (
            _ETHERNITY_ROOT / "resources" / "templates" / "sentinel" / "recovery_document.html.j2"
        )
        source = template_path.read_text(encoding="utf-8")

        self.assertNotIn("capacity_bonus_rows", source)
        self.assertNotIn("visual_trim_rows", source)

    def test_sentinel_recovery_template_uses_mm_row_height_tokens(self) -> None:
        template_path = (
            _ETHERNITY_ROOT / "resources" / "templates" / "sentinel" / "recovery_document.html.j2"
        )
        context: dict[str, object] = {
            "page_size_css": "A4",
            "page_width_mm": 210.0,
            "page_height_mm": 297.0,
            "margin_mm": 14.0,
            "usable_width_mm": 182.0,
            "doc_id": "deadbeef" * 4,
            "created_timestamp_utc": "2026-01-01 00:00 UTC",
            "ethernity_version": "0.2.2",
            "doc": {"title": "Recovery Document", "subtitle": "Keys + Text Fallback"},
            "instructions": {"label": "Instructions", "lines": ["Line 1"], "scan_hint": None},
            "fallback": {"width_mm": 182.0},
            "recovery": {
                "passphrase": None,
                "passphrase_lines": [],
                "quorum_value": "2 of 3",
                "signing_pub_lines": [],
            },
            "pages": [
                {
                    "page_num": 1,
                    "page_label": "Page 1 / 1",
                    "divider_y_mm": 30.0,
                    "instructions_y_mm": 40.0,
                    "show_instructions": True,
                    "instructions_full_page": False,
                    "qr_items": [],
                    "qr_grid": None,
                    "qr_outline": None,
                    "sequence": None,
                    "fallback_blocks": [
                        {
                            "title": "MAIN",
                            "lines": ["line-one", "line-two"],
                            "line_offset": 0,
                            "y_mm": 90.0,
                            "height_mm": 50.0,
                        }
                    ],
                    "fallback_line_capacity": 6,
                    "fallback_row_height_mm": 5.8,
                }
            ],
        }
        context["copy"] = build_copy_bundle(template_name=template_path.name, context=context)
        rendered = render_template(template_path, context)

        self.assertIn('style="height: 5.80mm"', rendered)
        self.assertNotIn("h-[22px]", rendered)
        self.assertNotIn("h-[19px]", rendered)


if __name__ == "__main__":
    unittest.main()
