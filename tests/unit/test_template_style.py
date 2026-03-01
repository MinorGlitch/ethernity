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
        self.assertFalse(ledger.capabilities.inject_forge_copy)
        self.assertFalse(ledger.capabilities.repeat_primary_qr_on_shard_continuation)
        self.assertFalse(ledger.capabilities.advanced_fallback_layout)
        self.assertFalse(ledger.capabilities.extra_main_first_page_qr_slot)
        self.assertFalse(ledger.capabilities.uniform_main_qr_capacity)
        self.assertIsNone(ledger.capabilities.main_qr_grid_size_mm)
        self.assertIsNone(ledger.capabilities.main_qr_grid_max_cols)
        self.assertIsNone(ledger.capabilities.fallback_layout)

        maritime = load_template_style(_TEMPLATES_ROOT / "maritime" / "main_document.html.j2")
        self.assertEqual(maritime.name, "maritime")
        self.assertAlmostEqual(maritime.header.meta_row_gap_mm, 1.2)
        self.assertAlmostEqual(maritime.header.stack_gap_mm, 1.6)
        self.assertAlmostEqual(maritime.header.divider_thickness_mm, 0.4)
        self.assertAlmostEqual(maritime.content_offset.divider_gap_extra_mm, 7.0)
        self.assertEqual(maritime.content_offset.doc_types, frozenset({"recovery"}))

        forge = load_template_style(_TEMPLATES_ROOT / "forge" / "main_document.html.j2")
        self.assertEqual(forge.name, "forge")
        self.assertAlmostEqual(forge.header.meta_row_gap_mm, 1.2)
        self.assertAlmostEqual(forge.header.stack_gap_mm, 1.2)
        self.assertAlmostEqual(forge.header.divider_thickness_mm, 0.5)
        self.assertAlmostEqual(forge.content_offset.divider_gap_extra_mm, 0.0)
        self.assertEqual(forge.content_offset.doc_types, frozenset())
        self.assertTrue(forge.capabilities.inject_forge_copy)
        self.assertTrue(forge.capabilities.repeat_primary_qr_on_shard_continuation)
        self.assertTrue(forge.capabilities.advanced_fallback_layout)
        self.assertFalse(forge.capabilities.uniform_main_qr_capacity)
        self.assertIsNotNone(forge.capabilities.fallback_layout)
        if forge.capabilities.fallback_layout is not None:
            self.assertAlmostEqual(
                forge.capabilities.fallback_layout.recovery.line_height_floor_mm,
                5.8,
            )
            self.assertAlmostEqual(
                forge.capabilities.fallback_layout.shard.first_page_payload_zone_height_mm,
                43.2,
            )
            self.assertAlmostEqual(
                forge.capabilities.fallback_layout.signing_key_shard.first_page_payload_zone_height_mm,
                37.8,
            )

        sentinel = load_template_style(_TEMPLATES_ROOT / "sentinel" / "main_document.html.j2")
        self.assertEqual(sentinel.name, "sentinel")
        self.assertAlmostEqual(sentinel.header.meta_row_gap_mm, 1.2)
        self.assertAlmostEqual(sentinel.header.stack_gap_mm, 1.2)
        self.assertAlmostEqual(sentinel.header.divider_thickness_mm, 0.5)
        self.assertAlmostEqual(sentinel.content_offset.divider_gap_extra_mm, 0.0)
        self.assertEqual(sentinel.content_offset.doc_types, frozenset())
        self.assertFalse(sentinel.capabilities.inject_forge_copy)
        self.assertTrue(sentinel.capabilities.repeat_primary_qr_on_shard_continuation)
        self.assertTrue(sentinel.capabilities.advanced_fallback_layout)
        self.assertTrue(sentinel.capabilities.extra_main_first_page_qr_slot)
        self.assertFalse(sentinel.capabilities.uniform_main_qr_capacity)
        self.assertIsNotNone(sentinel.capabilities.fallback_layout)
        if sentinel.capabilities.fallback_layout is not None:
            self.assertAlmostEqual(
                sentinel.capabilities.fallback_layout.recovery.first_page_text_width_bonus_mm,
                58.0,
            )
            self.assertAlmostEqual(
                sentinel.capabilities.fallback_layout.recovery.continuation_text_width_bonus_mm,
                150.0,
            )
            self.assertAlmostEqual(
                sentinel.capabilities.fallback_layout.shard.first_page_payload_zone_height_mm,
                48.0,
            )

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
            self.assertFalse(style.capabilities.inject_forge_copy)
            self.assertFalse(style.capabilities.repeat_primary_qr_on_shard_continuation)
            self.assertFalse(style.capabilities.advanced_fallback_layout)
            self.assertFalse(style.capabilities.extra_main_first_page_qr_slot)
            self.assertFalse(style.capabilities.uniform_main_qr_capacity)
            self.assertIsNone(style.capabilities.main_qr_grid_size_mm)
            self.assertIsNone(style.capabilities.main_qr_grid_max_cols)
            self.assertIsNone(style.capabilities.fallback_layout)

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
    "fallback_layout": {
      "recovery": {
        "line_height_floor_mm": 5.8,
        "first_page_footer_reserve_mm": 76.0,
        "continuation_footer_reserve_mm": 11.6,
        "meta_baseline_lines": 3,
        "meta_extra_line_mm": 8.0,
        "meta_section_overhead_mm": 12.0,
        "first_page_text_width_bonus_mm": 58.0,
        "continuation_text_width_bonus_mm": 150.0
      },
      "shard": {
        "line_height_floor_mm": 4.8,
        "first_page_payload_zone_height_mm": 48.0,
        "continuation_payload_zone_height_mm": 52.8
      },
      "signing_key_shard": {
        "line_height_floor_mm": 4.2,
        "first_page_payload_zone_height_mm": 71.4,
        "continuation_payload_zone_height_mm": 46.2
      }
    }
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            style = load_template_style(template_dir / "main_document.html.j2")
            self.assertFalse(style.capabilities.inject_forge_copy)
            self.assertTrue(style.capabilities.repeat_primary_qr_on_shard_continuation)
            self.assertTrue(style.capabilities.advanced_fallback_layout)
            self.assertTrue(style.capabilities.extra_main_first_page_qr_slot)
            self.assertFalse(style.capabilities.uniform_main_qr_capacity)
            self.assertIsNone(style.capabilities.main_qr_grid_size_mm)
            self.assertIsNone(style.capabilities.main_qr_grid_max_cols)
            self.assertIsNotNone(style.capabilities.fallback_layout)

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

    def test_style_rejects_legacy_bonus_capability_keys_with_migration_hint(self) -> None:
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
    "shard_first_page_bonus_lines": 1
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "legacy capability keys removed: shard_first_page_bonus_lines",
            ):
                load_template_style(template_dir / "main_document.html.j2")

    def test_style_rejects_invalid_main_qr_grid_capability_values(self) -> None:
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
    "main_qr_grid_size_mm": 0,
    "main_qr_grid_max_cols": -1
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "missing or invalid 'main_qr_grid_size_mm' positive number",
            ):
                load_template_style(template_dir / "main_document.html.j2")

    def test_style_rejects_boolean_where_number_required(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            (template_dir / "style.json").write_text(
                """{
  "name": "custom",
  "header": {
    "meta_row_gap_mm": true,
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
            with self.assertRaisesRegex(
                ValueError,
                "missing or invalid 'meta_row_gap_mm' number",
            ):
                load_template_style(template_dir / "main_document.html.j2")

    def test_style_rejects_negative_recovery_continuation_footer_reserve(self) -> None:
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
    "advanced_fallback_layout": true,
    "fallback_layout": {
      "recovery": {
        "line_height_floor_mm": 5.8,
        "first_page_footer_reserve_mm": 76.0,
        "continuation_footer_reserve_mm": -1.0,
        "meta_baseline_lines": 3,
        "meta_extra_line_mm": 8.0,
        "meta_section_overhead_mm": 12.0,
        "first_page_text_width_bonus_mm": 58.0,
        "continuation_text_width_bonus_mm": 150.0
      },
      "shard": {
        "line_height_floor_mm": 4.8,
        "first_page_payload_zone_height_mm": 48.0,
        "continuation_payload_zone_height_mm": 52.8
      },
      "signing_key_shard": {
        "line_height_floor_mm": 4.2,
        "first_page_payload_zone_height_mm": 71.4,
        "continuation_payload_zone_height_mm": 46.2
      }
    }
  }
}
""",
                encoding="utf-8",
            )
            (template_dir / "main_document.html.j2").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "missing or invalid 'continuation_footer_reserve_mm' non-negative number",
            ):
                load_template_style(template_dir / "main_document.html.j2")


if __name__ == "__main__":
    unittest.main()
