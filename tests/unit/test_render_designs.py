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

from ethernity.render.designs import load_design_manifest


def _write_manifest(directory: Path, payload: dict[str, object]) -> None:
    (directory / "style.json").write_text("{}", encoding="utf-8")
    (directory / "design.json").write_text(json.dumps(payload), encoding="utf-8")


class TestRenderDesigns(unittest.TestCase):
    def test_load_design_manifest_normalizes_name_and_doc_types(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            _write_manifest(
                directory,
                {
                    "schema_version": 1,
                    "name": "Custom",
                    "style": "style.json",
                    "documents": ["MAIN", "recovery"],
                },
            )

            manifest = load_design_manifest(directory)

            self.assertEqual(manifest.name, "custom")
            self.assertEqual(manifest.style_path, (directory / "style.json").resolve())
            self.assertEqual(manifest.documents, frozenset({"main", "recovery"}))
            self.assertTrue(manifest.supports_doc_type("MAIN"))

    def test_load_design_manifest_rejects_unknown_keys(self) -> None:
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            _write_manifest(
                directory,
                {
                    "schema_version": 1,
                    "name": "custom",
                    "style": "style.json",
                    "documents": ["main"],
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
                    "schema_version": 1,
                    "name": "custom",
                    "style": "style.json",
                    "documents": ["poster"],
                },
            )

            with self.assertRaisesRegex(ValueError, "unknown document type 'poster'"):
                load_design_manifest(directory)


if __name__ == "__main__":
    unittest.main()
