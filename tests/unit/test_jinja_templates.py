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

import base64
import unittest
from pathlib import Path

from ethernity.render.templating import render_template

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ETHERNITY_ROOT = _PROJECT_ROOT / "src" / "ethernity"


def _page_base(*, page_num: int, page_label: str) -> dict[str, object]:
    return {
        "page_num": page_num,
        "page_label": page_label,
        "divider_y_mm": 30.0,
        "instructions_y_mm": 40.0,
        "show_instructions": True,
        "instructions_full_page": False,
        "qr_items": [],
        "qr_grid": None,
        "qr_outline": None,
        "sequence": None,
        "fallback_blocks": [],
    }


def _page_with_qr(*, page_num: int = 1, page_label: str = "Page 1 / 1") -> dict[str, object]:
    page = _page_base(page_num=page_num, page_label=page_label)
    page["qr_items"] = [{"index": 1, "data_uri": "data:image/png;base64,AA=="}]
    page["qr_grid"] = {
        "x_mm": 14.0,
        "y_mm": 60.0,
        "size_mm": 50.0,
        "gap_x_mm": 2.0,
        "gap_y_mm": 2.0,
        "cols": 3,
        "rows": 1,
        "count": 1,
    }
    page["qr_outline"] = {"x_mm": 14.0, "y_mm": 60.0, "width_mm": 50.0, "height_mm": 50.0}
    return page


def _base_document_context() -> dict[str, object]:
    return {
        "page_size_css": "A4",
        "page_width_mm": 210.0,
        "page_height_mm": 297.0,
        "margin_mm": 14.0,
        "usable_width_mm": 182.0,
        "doc_id": "deadbeef" * 4,
        "created_timestamp_utc": "2026-01-01 00:00 UTC",
        "doc": {"title": "Document", "subtitle": "Subtitle"},
        "instructions": {"label": "Instructions", "lines": ["Line 1", "Line 2"], "scan_hint": None},
        "keys": {"lines": []},
        "fallback": {"width_mm": 182.0},
        "shard_index": 1,
        "shard_total": 3,
        "recovery": {
            "passphrase": None,
            "passphrase_lines": [],
            "quorum_value": None,
            "signing_pub_lines": [],
        },
    }


class TestJinjaTemplates(unittest.TestCase):
    def test_document_templates_render(self) -> None:
        template_root = _ETHERNITY_ROOT / "templates"
        templates = sorted(template_root.rglob("*.html.j2"))
        self.assertTrue(templates, "no document templates found")

        for template_path in templates:
            context = _base_document_context()
            if "recovery_document" in template_path.name:
                context["pages"] = [_page_base(page_num=1, page_label="Page 1 / 1")]
                context["doc"] = {"title": "Recovery Document", "subtitle": "Keys + Text Fallback"}
                context["instructions"] = {
                    "label": "Instructions",
                    "lines": ["A", "B"],
                    "scan_hint": None,
                }
            elif "kit_document" in template_path.name:
                context["pages"] = [
                    _page_with_qr(page_num=1, page_label="Page 1 / 2"),
                    {
                        **_page_base(page_num=2, page_label=""),
                        "instructions_full_page": True,
                        "qr_items": [],
                    },
                ]
                context["doc"] = {"title": "Recovery Kit", "subtitle": "Offline HTML bundle"}
                context["instructions"] = {
                    "label": "Instructions",
                    "lines": ["A", "B"],
                    "scan_hint": "Start at the top-left and follow each row.",
                }
            elif (
                "shard_document" in template_path.name
                or "signing_key_shard_document" in template_path.name
            ):
                context["pages"] = [
                    {
                        **_page_with_qr(page_num=1, page_label="Page 1 / 1"),
                        "fallback_blocks": [
                            {
                                "title": "MAIN",
                                "lines": ["aaaa bbbb cccc dddd", "eeee ffff gggg hhhh"],
                                "line_offset": 0,
                                "y_mm": 90.0,
                                "height_mm": 80.0,
                            }
                        ],
                    }
                ]
                context["doc"] = {"title": "Shard Document", "subtitle": "Shard 1 of 3"}
                context["instructions"] = {
                    "label": "Instructions",
                    "lines": ["A", "B"],
                    "scan_hint": None,
                }
            else:
                context["pages"] = [_page_with_qr(page_num=1, page_label="Page 1 / 1")]
                context["doc"] = {"title": "Main Document", "subtitle": "Mode: passphrase"}
                context["instructions"] = {
                    "label": "Instructions",
                    "lines": ["A", "B"],
                    "scan_hint": None,
                }

            rendered = render_template(template_path, context)
            self.assertIn("<!doctype html>", rendered.lower(), str(template_path))

    def test_envelope_templates_render_with_default_logo(self) -> None:
        storage_root = _ETHERNITY_ROOT / "storage"
        logo_path = storage_root / "logo.png"
        self.assertTrue(logo_path.is_file(), "expected default logo.png to exist")

        prefix = base64.b64encode(logo_path.read_bytes()[:60]).decode("ascii")

        templates = sorted(storage_root.glob("envelope_*.html.j2"))
        self.assertTrue(templates, "no envelope templates found")

        for template_path in templates:
            rendered = render_template(
                template_path,
                {"page_width_mm": 114, "page_height_mm": 162},
            )
            self.assertIn("base64,", rendered, str(template_path))
            self.assertIn(prefix, rendered, str(template_path))


if __name__ == "__main__":
    unittest.main()
