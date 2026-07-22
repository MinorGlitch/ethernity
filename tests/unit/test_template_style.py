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
_TEMPLATES_ROOT = _PROJECT_ROOT / "src" / "ethernity" / "resources" / "templates"


def _write_style(template_dir: Path, content: str) -> None:
    (template_dir / "style.json").write_text(content, encoding="utf-8")


class TestTemplateStyle(unittest.TestCase):
    def test_builtin_styles_expose_only_live_capabilities(self) -> None:
        archive = load_template_style(_TEMPLATES_ROOT / "archive")
        self.assertEqual(archive.name, "archive")
        self.assertAlmostEqual(archive.capabilities.main_qr_grid_size_mm or 0.0, 58.6)
        self.assertFalse(archive.capabilities.recovery_first_page_single_section)
        self.assertFalse(archive.capabilities.recovery_kit_index_document)

        for design in ("ledger", "maritime"):
            style = load_template_style(_TEMPLATES_ROOT / design)
            self.assertEqual(style.name, design)
            self.assertEqual(style.capabilities, type(style.capabilities)())

        forge = load_template_style(_TEMPLATES_ROOT / "forge")
        self.assertTrue(forge.capabilities.recovery_first_page_single_section)
        self.assertTrue(forge.capabilities.recovery_kit_index_document)
        self.assertIsNone(forge.capabilities.main_qr_grid_size_mm)

        sentinel = load_template_style(_TEMPLATES_ROOT / "sentinel")
        self.assertFalse(sentinel.capabilities.recovery_first_page_single_section)
        self.assertTrue(sentinel.capabilities.recovery_kit_index_document)
        self.assertIsNone(sentinel.capabilities.main_qr_grid_size_mm)

    def test_style_defaults_capabilities_when_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            _write_style(template_dir, '{"name": "custom"}\n')

            style = load_template_style(template_dir)

            self.assertFalse(style.capabilities.recovery_first_page_single_section)
            self.assertFalse(style.capabilities.recovery_kit_index_document)
            self.assertIsNone(style.capabilities.main_qr_grid_size_mm)

    def test_style_accepts_all_live_capabilities(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            _write_style(
                template_dir,
                """{
  "name": "custom",
  "capabilities": {
    "recovery_first_page_single_section": true,
    "recovery_kit_index_document": true,
    "main_qr_grid_size_mm": 42
  }
}
""",
            )

            style = load_template_style(template_dir)

            self.assertTrue(style.capabilities.recovery_first_page_single_section)
            self.assertTrue(style.capabilities.recovery_kit_index_document)
            self.assertEqual(style.capabilities.main_qr_grid_size_mm, 42.0)

    def test_style_rejects_removed_top_level_sections(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            _write_style(
                template_dir,
                """{
  "name": "custom",
  "header": {
    "meta_row_gap_mm": 1.2
  }
}
""",
            )

            with self.assertRaisesRegex(ValueError, "unknown key\\(s\\) in template style"):
                load_template_style(template_dir)

    def test_style_rejects_removed_capability_keys(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            _write_style(
                template_dir,
                """{
  "name": "custom",
  "capabilities": {
    "advanced_fallback_layout": true
  }
}
""",
            )

            with self.assertRaisesRegex(ValueError, "unknown key\\(s\\) in capabilities"):
                load_template_style(template_dir)

    def test_style_rejects_unknown_capability_keys(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            _write_style(
                template_dir,
                '{"name": "custom", "capabilities": {"unknown_feature": true}}\n',
            )

            with self.assertRaisesRegex(ValueError, "unknown key\\(s\\) in capabilities"):
                load_template_style(template_dir)

    def test_style_rejects_non_bool_capability_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            _write_style(
                template_dir,
                """{
  "name": "custom",
  "capabilities": {
    "recovery_kit_index_document": 1
  }
}
""",
            )

            with self.assertRaisesRegex(
                ValueError,
                "missing or invalid 'recovery_kit_index_document' boolean",
            ):
                load_template_style(template_dir)

    def test_style_rejects_invalid_main_qr_grid_size(self) -> None:
        for value in ("0", "true"):
            with self.subTest(value=value), TemporaryDirectory() as temp_dir:
                template_dir = Path(temp_dir)
                _write_style(
                    template_dir,
                    f'{{"name": "custom", "capabilities": {{"main_qr_grid_size_mm": {value}}}}}\n',
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "missing or invalid 'main_qr_grid_size_mm' positive number",
                ):
                    load_template_style(template_dir)

    def test_style_rejects_invalid_capabilities_object(self) -> None:
        with TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            _write_style(template_dir, '{"name": "custom", "capabilities": []}\n')

            with self.assertRaisesRegex(ValueError, "invalid 'capabilities' object"):
                load_template_style(template_dir)


if __name__ == "__main__":
    unittest.main()
