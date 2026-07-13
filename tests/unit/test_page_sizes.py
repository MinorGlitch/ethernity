from __future__ import annotations

import unittest

from ethernity.page_sizes import (
    DEFAULT_PAPER_SIZE_NAME,
    PaperSize,
    is_registered_paper_size,
    paper_size_display_name,
    paper_size_names,
    resolve_paper_size,
)


class TestPageSizes(unittest.TestCase):
    def test_registry_is_stable_and_case_insensitive_at_resolution_boundary(self) -> None:
        self.assertEqual(paper_size_names(), ("A4", "LETTER"))
        self.assertEqual(DEFAULT_PAPER_SIZE_NAME, "A4")
        self.assertEqual(resolve_paper_size(" letter ").name, "LETTER")
        self.assertEqual(paper_size_display_name("letter"), "Letter")
        self.assertTrue(is_registered_paper_size("a4"))

    def test_unknown_size_reports_the_registry(self) -> None:
        with self.assertRaisesRegex(ValueError, "registered paper sizes: A4, LETTER"):
            resolve_paper_size("LEGAL")

    def test_paper_size_requires_normalized_name_and_physical_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "normalized uppercase"):
            PaperSize("legal", "Legal", 215.9, 355.6)
        with self.assertRaisesRegex(ValueError, "whitespace-free"):
            PaperSize("US LEGAL", "US Legal", 215.9, 355.6)
        with self.assertRaisesRegex(ValueError, "display_name must be non-empty"):
            PaperSize("LEGAL", " ", 215.9, 355.6)
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            PaperSize("LEGAL", "Legal", 215.9, 0.0)
        with self.assertRaisesRegex(ValueError, "portrait geometry"):
            PaperSize("LEGAL", "Legal", 355.6, 215.9)


if __name__ == "__main__":
    unittest.main()
