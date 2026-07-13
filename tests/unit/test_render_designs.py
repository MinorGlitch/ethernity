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

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ethernity.page_sizes import PaperSize
from ethernity.render.designs import (
    load_design_manifest,
    supported_paper_size_names,
)


def _write_manifest(directory: Path, payload: dict[str, object]) -> None:
    (directory / "style.json").write_text("{}", encoding="utf-8")
    (directory / "design.json").write_text(json.dumps(payload), encoding="utf-8")


def _page_support(*doc_types: str) -> dict[str, object]:
    return {
        doc_type: {"minimum_width_mm": 190.0, "minimum_height_mm": 260.0} for doc_type in doc_types
    }


class TestRenderDesigns(unittest.TestCase):
    def test_load_design_manifest_normalizes_name_and_doc_types(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            _write_manifest(
                directory,
                {
                    "schema_version": 2,
                    "name": "Custom",
                    "style": "style.json",
                    "documents": ["MAIN", "recovery"],
                    "page_support": _page_support("MAIN", "recovery"),
                },
            )

            manifest = load_design_manifest(directory)

            self.assertEqual(manifest.name, "custom")
            self.assertEqual(manifest.style_path, (directory / "style.json").resolve())
            self.assertEqual(manifest.documents, frozenset({"main", "recovery"}))
            self.assertTrue(manifest.supports_doc_type("MAIN"))
            support = manifest.page_support_for("MAIN")
            self.assertEqual(support.minimum_width_mm, 190.0)
            self.assertEqual(support.minimum_height_mm, 260.0)
            self.assertTrue(
                manifest.supports_page_size(
                    "main",
                    PaperSize("CUSTOM", "Custom", 190.0, 260.0),
                )
            )
            self.assertFalse(
                manifest.supports_page_size(
                    "main",
                    PaperSize("A5", "A5", 148.0, 210.0),
                )
            )
            with self.assertRaisesRegex(ValueError, "outside the proven responsive envelope"):
                manifest.require_page_size(
                    "main",
                    PaperSize("A5", "A5", 148.0, 210.0),
                )

    def test_load_design_manifest_rejects_unknown_keys(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            _write_manifest(
                directory,
                {
                    "schema_version": 2,
                    "name": "custom",
                    "style": "style.json",
                    "documents": ["main"],
                    "page_support": _page_support("main"),
                    "extra": True,
                },
            )

            with self.assertRaisesRegex(ValueError, "unknown design manifest key"):
                load_design_manifest(directory)

    def test_load_design_manifest_rejects_unknown_doc_type(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            _write_manifest(
                directory,
                {
                    "schema_version": 2,
                    "name": "custom",
                    "style": "style.json",
                    "documents": ["poster"],
                    "page_support": _page_support("poster"),
                },
            )

            with self.assertRaisesRegex(ValueError, "unknown document type 'poster'"):
                load_design_manifest(directory)

    def test_load_design_manifest_requires_page_support_for_every_document(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            _write_manifest(
                directory,
                {
                    "schema_version": 2,
                    "name": "custom",
                    "style": "style.json",
                    "documents": ["main", "recovery"],
                    "page_support": _page_support("main"),
                },
            )

            with self.assertRaisesRegex(ValueError, "page_support must match.*missing=recovery"):
                load_design_manifest(directory)

    def test_load_design_manifest_rejects_non_physical_page_support(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            _write_manifest(
                directory,
                {
                    "schema_version": 2,
                    "name": "custom",
                    "style": "style.json",
                    "documents": ["main"],
                    "page_support": {"main": {"minimum_width_mm": 0, "minimum_height_mm": 260.0}},
                },
            )

            with self.assertRaisesRegex(ValueError, "page_support"):
                load_design_manifest(directory)

    def test_every_builtin_design_advertises_current_registered_sizes(self) -> None:
        for design_name in ("archive", "forge", "ledger", "maritime", "sentinel"):
            with self.subTest(design_name=design_name):
                self.assertEqual(
                    supported_paper_size_names(design_name),
                    ("A4", "LETTER"),
                )


if __name__ == "__main__":
    unittest.main()
