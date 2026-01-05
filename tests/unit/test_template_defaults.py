import unittest
from pathlib import Path

from ethernity.render.templating import render_template


class TestTemplateDefaults(unittest.TestCase):
    def test_main_template_defaults(self) -> None:
        context = {
            "paper_size": "A4",
            "margin_mm": 12,
            "header_height_mm": 10,
            "instructions_gap_mm": 2,
            "header_font": "Helvetica",
            "title_size": 14,
            "subtitle_size": 10,
            "meta_size": 8,
            "title": "Main Document",
            "subtitle": "Test Backup",
            "doc_id": "deadbeef",
            "page_num": 1,
            "page_total": 1,
            "instructions_font": "Helvetica",
            "instructions_size": 8,
            "instructions_line_height_mm": 4,
            "instructions": ["Line 1"],
            "qr_size_mm": 60,
            "gap_mm": 2,
            "max_cols": 3,
            "max_rows": 4,
            "text_gap_mm": 2,
        }
        template_path = (
            Path(__file__).resolve().parents[2] / "ethernity" / "templates" / "main_document.toml.j2"
        )
        cfg = render_template(template_path, context)
        header = cfg["header"]
        self.assertEqual(header["title_style"], "")
        self.assertEqual(header["subtitle_style"], "")
        self.assertEqual(header["meta_style"], "")
        self.assertEqual(header["title_color"], [0, 0, 0])
        self.assertFalse(header["divider_enabled"])

    def test_recovery_template_defaults(self) -> None:
        context = {
            "paper_size": "A4",
            "margin_mm": 12,
            "header_height_mm": 10,
            "instructions_gap_mm": 2,
            "header_font": "Helvetica",
            "title_size": 14,
            "subtitle_size": 10,
            "meta_size": 8,
            "recovery_title": "Recovery",
            "recovery_subtitle": "Keys + Text Fallback",
            "doc_id": "deadbeef",
            "page_num": 1,
            "page_total": 1,
            "instructions_font": "Helvetica",
            "instructions_size": 8,
            "instructions_line_height_mm": 4,
            "recovery_instructions": ["Line 1"],
            "keys_font": "Courier",
            "keys_size": 8,
            "keys_line_height_mm": 3.5,
            "key_lines": ["Key"],
            "fallback_font": "Courier",
            "fallback_size": 8,
            "fallback_line_height_mm": 3.5,
            "fallback_group_size": 4,
            "fallback_line_length": 80,
            "fallback_line_count": 6,
        }
        template_path = (
            Path(__file__).resolve().parents[2]
            / "ethernity"
            / "templates"
            / "recovery_document.toml.j2"
        )
        cfg = render_template(template_path, context)
        header = cfg["header"]
        self.assertEqual(header["title_style"], "")
        self.assertEqual(header["meta_color"], [0, 0, 0])
        self.assertFalse(header["divider_enabled"])
        self.assertEqual(cfg["page"]["keys_gap_mm"], 2)


if __name__ == "__main__":
    unittest.main()
