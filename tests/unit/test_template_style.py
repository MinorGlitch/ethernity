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
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.render.template_style import load_template_style

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES_ROOT = _PROJECT_ROOT / "src" / "ethernity" / "templates"


class TestTemplateStyle(unittest.TestCase):
    def test_builtin_styles_match_expected_values(self) -> None:
        ledger = load_template_style(_TEMPLATES_ROOT / "ledger" / "main_document.html.j2")
        self.assertEqual(ledger.name, "ledger")
        self.assertAlmostEqual(ledger.header.meta_row_gap_mm, 1.2)
        self.assertAlmostEqual(ledger.header.stack_gap_mm, 0.0)
        self.assertAlmostEqual(ledger.header.divider_thickness_mm, 0.6)
        self.assertAlmostEqual(ledger.content_offset.divider_gap_extra_mm, 0.0)
        self.assertEqual(ledger.content_offset.doc_types, frozenset())

        maritime = load_template_style(_TEMPLATES_ROOT / "maritime" / "main_document.html.j2")
        self.assertEqual(maritime.name, "maritime")
        self.assertAlmostEqual(maritime.header.meta_row_gap_mm, 1.2)
        self.assertAlmostEqual(maritime.header.stack_gap_mm, 1.6)
        self.assertAlmostEqual(maritime.header.divider_thickness_mm, 0.4)
        self.assertAlmostEqual(maritime.content_offset.divider_gap_extra_mm, 7.0)
        self.assertEqual(maritime.content_offset.doc_types, frozenset())

        dossier = load_template_style(_TEMPLATES_ROOT / "dossier" / "main_document.html.j2")
        self.assertEqual(dossier.name, "dossier")
        self.assertAlmostEqual(dossier.header.meta_row_gap_mm, 1.4)
        self.assertAlmostEqual(dossier.header.stack_gap_mm, 2.0)
        self.assertAlmostEqual(dossier.header.divider_thickness_mm, 0.6)
        self.assertAlmostEqual(dossier.content_offset.divider_gap_extra_mm, 7.0)
        self.assertEqual(
            dossier.content_offset.doc_types,
            frozenset({"kit", "shard", "signing_key_shard"}),
        )

        midnight = load_template_style(_TEMPLATES_ROOT / "midnight" / "main_document.html.j2")
        self.assertEqual(midnight.name, "midnight")
        self.assertAlmostEqual(midnight.header.meta_row_gap_mm, 1.0)
        self.assertAlmostEqual(midnight.header.stack_gap_mm, 1.6)
        self.assertAlmostEqual(midnight.header.divider_thickness_mm, 0.45)
        self.assertAlmostEqual(midnight.content_offset.divider_gap_extra_mm, 7.0)
        self.assertEqual(
            midnight.content_offset.doc_types,
            frozenset({"kit", "shard", "signing_key_shard"}),
        )

    def test_style_rejects_unknown_top_level_keys(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            (template_dir / "style.json").write_text(
                """{
  "name": "custom",
  "header": {
    "meta_row_gap_mm": 1.2,
    "stack_gap_mm": 1.0,
    "divider_thickness_mm": 0.5
  },
  "content_offset": {
    "divider_gap_extra_mm": 0.0,
    "doc_types": []
  },
  "recovery": {
    "header_layout": "split"
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown key\\(s\\) in template style"):
                load_template_style(template_dir / "main_document.html.j2")


if __name__ == "__main__":
    unittest.main()
