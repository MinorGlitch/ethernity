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
        self.assertFalse(ledger.capabilities.repeat_primary_qr_on_shard_continuation)
        self.assertFalse(ledger.capabilities.advanced_fallback_layout)
        self.assertFalse(ledger.capabilities.wide_recovery_fallback_lines)
        self.assertFalse(ledger.capabilities.extra_main_first_page_qr_slot)
        self.assertEqual(ledger.capabilities.shard_first_page_bonus_lines, 0)
        self.assertEqual(ledger.capabilities.signing_key_shard_first_page_bonus_lines, 0)

        maritime = load_template_style(_TEMPLATES_ROOT / "maritime" / "main_document.html.j2")
        self.assertEqual(maritime.name, "maritime")
        self.assertAlmostEqual(maritime.header.meta_row_gap_mm, 1.2)
        self.assertAlmostEqual(maritime.header.stack_gap_mm, 1.6)
        self.assertAlmostEqual(maritime.header.divider_thickness_mm, 0.4)
        self.assertAlmostEqual(maritime.content_offset.divider_gap_extra_mm, 7.0)
        self.assertEqual(maritime.content_offset.doc_types, frozenset({"recovery"}))

        dossier = load_template_style(_TEMPLATES_ROOT / "dossier" / "main_document.html.j2")
        self.assertEqual(dossier.name, "dossier")
        self.assertAlmostEqual(dossier.header.meta_row_gap_mm, 1.4)
        self.assertAlmostEqual(dossier.header.stack_gap_mm, 2.0)
        self.assertAlmostEqual(dossier.header.divider_thickness_mm, 0.6)
        self.assertAlmostEqual(dossier.content_offset.divider_gap_extra_mm, 7.0)
        self.assertEqual(
            dossier.content_offset.doc_types,
            frozenset({"recovery", "kit", "shard", "signing_key_shard"}),
        )

        midnight = load_template_style(_TEMPLATES_ROOT / "midnight" / "main_document.html.j2")
        self.assertEqual(midnight.name, "midnight")
        self.assertAlmostEqual(midnight.header.meta_row_gap_mm, 1.0)
        self.assertAlmostEqual(midnight.header.stack_gap_mm, 1.6)
        self.assertAlmostEqual(midnight.header.divider_thickness_mm, 0.45)
        self.assertAlmostEqual(midnight.content_offset.divider_gap_extra_mm, 7.0)
        self.assertEqual(
            midnight.content_offset.doc_types,
            frozenset({"recovery", "kit", "shard", "signing_key_shard"}),
        )

        forge = load_template_style(_TEMPLATES_ROOT / "forge" / "main_document.html.j2")
        self.assertEqual(forge.name, "forge")
        self.assertAlmostEqual(forge.header.meta_row_gap_mm, 1.2)
        self.assertAlmostEqual(forge.header.stack_gap_mm, 1.2)
        self.assertAlmostEqual(forge.header.divider_thickness_mm, 0.5)
        self.assertAlmostEqual(forge.content_offset.divider_gap_extra_mm, 0.0)
        self.assertEqual(forge.content_offset.doc_types, frozenset())
        self.assertTrue(forge.capabilities.repeat_primary_qr_on_shard_continuation)
        self.assertTrue(forge.capabilities.advanced_fallback_layout)
        self.assertFalse(forge.capabilities.wide_recovery_fallback_lines)
        self.assertEqual(forge.capabilities.shard_first_page_bonus_lines, 0)
        self.assertEqual(forge.capabilities.signing_key_shard_first_page_bonus_lines, 0)

        sentinel = load_template_style(_TEMPLATES_ROOT / "sentinel" / "main_document.html.j2")
        self.assertEqual(sentinel.name, "sentinel")
        self.assertAlmostEqual(sentinel.header.meta_row_gap_mm, 1.2)
        self.assertAlmostEqual(sentinel.header.stack_gap_mm, 1.2)
        self.assertAlmostEqual(sentinel.header.divider_thickness_mm, 0.5)
        self.assertAlmostEqual(sentinel.content_offset.divider_gap_extra_mm, 0.0)
        self.assertEqual(sentinel.content_offset.doc_types, frozenset())
        self.assertTrue(sentinel.capabilities.repeat_primary_qr_on_shard_continuation)
        self.assertTrue(sentinel.capabilities.advanced_fallback_layout)
        self.assertTrue(sentinel.capabilities.wide_recovery_fallback_lines)
        self.assertTrue(sentinel.capabilities.extra_main_first_page_qr_slot)
        self.assertEqual(sentinel.capabilities.shard_first_page_bonus_lines, 1)
        self.assertEqual(sentinel.capabilities.signing_key_shard_first_page_bonus_lines, 8)

        monograph = load_template_style(_TEMPLATES_ROOT / "monograph" / "main_document.html.j2")
        self.assertEqual(monograph.name, "monograph")
        self.assertAlmostEqual(monograph.header.meta_row_gap_mm, 1.2)
        self.assertAlmostEqual(monograph.header.stack_gap_mm, 1.2)
        self.assertAlmostEqual(monograph.header.divider_thickness_mm, 0.5)
        self.assertAlmostEqual(monograph.content_offset.divider_gap_extra_mm, 0.0)
        self.assertEqual(monograph.content_offset.doc_types, frozenset())
        self.assertTrue(monograph.capabilities.repeat_primary_qr_on_shard_continuation)
        self.assertTrue(monograph.capabilities.advanced_fallback_layout)
        self.assertFalse(monograph.capabilities.wide_recovery_fallback_lines)
        self.assertFalse(monograph.capabilities.extra_main_first_page_qr_slot)
        self.assertEqual(monograph.capabilities.shard_first_page_bonus_lines, 0)
        self.assertEqual(monograph.capabilities.signing_key_shard_first_page_bonus_lines, 0)

    def test_style_defaults_capabilities_when_missing(self) -> None:
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
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            style = load_template_style(template_dir / "main_document.html.j2")
            self.assertFalse(style.capabilities.repeat_primary_qr_on_shard_continuation)
            self.assertFalse(style.capabilities.advanced_fallback_layout)
            self.assertFalse(style.capabilities.wide_recovery_fallback_lines)
            self.assertFalse(style.capabilities.extra_main_first_page_qr_slot)
            self.assertEqual(style.capabilities.shard_first_page_bonus_lines, 0)
            self.assertEqual(style.capabilities.signing_key_shard_first_page_bonus_lines, 0)

    def test_sentinel_style_defaults_extra_first_page_slot_when_omitted(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            (template_dir / "style.json").write_text(
                """{
  "name": "sentinel",
  "header": {
    "meta_row_gap_mm": 1.2,
    "stack_gap_mm": 1.0,
    "divider_thickness_mm": 0.5
  },
  "content_offset": {
    "divider_gap_extra_mm": 0.0,
    "doc_types": []
  },
  "capabilities": {
    "repeat_primary_qr_on_shard_continuation": true,
    "advanced_fallback_layout": true,
    "wide_recovery_fallback_lines": true
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            style = load_template_style(template_dir / "main_document.html.j2")
            self.assertTrue(style.capabilities.repeat_primary_qr_on_shard_continuation)
            self.assertTrue(style.capabilities.advanced_fallback_layout)
            self.assertTrue(style.capabilities.wide_recovery_fallback_lines)
            self.assertTrue(style.capabilities.extra_main_first_page_qr_slot)
            self.assertEqual(style.capabilities.shard_first_page_bonus_lines, 0)
            self.assertEqual(style.capabilities.signing_key_shard_first_page_bonus_lines, 0)

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

    def test_style_rejects_unknown_capability_keys(self) -> None:
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
  "capabilities": {
    "repeat_primary_qr_on_shard_continuation": true,
    "unknown_feature": true
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown key\\(s\\) in capabilities"):
                load_template_style(template_dir / "main_document.html.j2")

    def test_style_rejects_non_bool_capability_values(self) -> None:
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
  "capabilities": {
    "repeat_primary_qr_on_shard_continuation": 1
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "missing or invalid 'repeat_primary_qr_on_shard_continuation' boolean",
            ):
                load_template_style(template_dir / "main_document.html.j2")

    def test_style_rejects_invalid_shard_bonus_capability_values(self) -> None:
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
  "capabilities": {
    "shard_first_page_bonus_lines": -1
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "missing or invalid 'shard_first_page_bonus_lines' non-negative integer",
            ):
                load_template_style(template_dir / "main_document.html.j2")


if __name__ == "__main__":
    unittest.main()
