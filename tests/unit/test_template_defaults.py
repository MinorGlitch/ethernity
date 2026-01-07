import unittest
from pathlib import Path

from ethernity.render.templating import render_template


class TestTemplateDefaults(unittest.TestCase):
    def test_main_template_defaults(self) -> None:
        context = {
            "doc_id": "deadbeef",
            "page_num": 1,
            "page_total": 1,
        }
        template_path = (
            Path(__file__).resolve().parents[2] / "ethernity" / "templates" / "main_document.toml.j2"
        )
        cfg = render_template(template_path, context)
        header = cfg["header"]
        self.assertEqual(header["title_style"], "B")
        self.assertEqual(header["subtitle_style"], "I")
        self.assertEqual(header["meta_style"], "I")
        self.assertEqual(header["title_color"], [15, 30, 45])
        self.assertTrue(header["divider_enabled"])

    def test_recovery_template_defaults(self) -> None:
        context = {
            "doc_id": "deadbeef",
            "page_num": 1,
            "page_total": 1,
            "key_lines": ["Key"],
        }
        template_path = (
            Path(__file__).resolve().parents[2]
            / "ethernity"
            / "templates"
            / "recovery_document.toml.j2"
        )
        cfg = render_template(template_path, context)
        header = cfg["header"]
        self.assertEqual(header["title_style"], "B")
        self.assertEqual(header["meta_color"], [120, 130, 140])
        self.assertTrue(header["divider_enabled"])
        self.assertEqual(cfg["page"]["keys_gap_mm"], 3)


if __name__ == "__main__":
    unittest.main()
