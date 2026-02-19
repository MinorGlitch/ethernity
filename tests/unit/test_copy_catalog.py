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

from ethernity.render.copy_catalog import build_copy_bundle


class TestCopyCatalog(unittest.TestCase):
    def test_main_bundle_contains_canonical_copy(self) -> None:
        copy = build_copy_bundle(template_name="main_document.html.j2", context={})
        self.assertEqual(copy["title"], "Main Document")
        self.assertEqual(copy["subtitle"], "Passphrase-protected payload")
        self.assertEqual(copy["header_guidance"], "Use with matching recovery document")
        self.assertEqual(copy["segment_prefix"], "Segment")

    def test_shard_bundle_formats_dynamic_warning(self) -> None:
        copy = build_copy_bundle(
            template_name="shard_document.html.j2",
            context={"shard_index": 2, "shard_total": 5, "shard_threshold": 3},
        )
        self.assertEqual(copy["title"], "Shard Document")
        self.assertEqual(copy["subtitle"], "Shard 2 of 5")
        self.assertIn("shard 2 of 5", copy["warning_body"])
        self.assertIn("Recovery requires 3/5 shards.", copy["warning_body"])

    def test_signing_key_shard_bundle_formats_dynamic_subtitle(self) -> None:
        copy = build_copy_bundle(
            template_name="signing_key_shard_document.html.j2",
            context={"shard_index": 4, "shard_total": 7},
        )
        self.assertEqual(copy["title"], "Signing Key Shard")
        self.assertEqual(copy["subtitle"], "Signing key shard 4 of 7")
        self.assertEqual(copy["key_material_label"], "Key Material Payload")

    def test_kit_index_bundle_contains_expected_copy(self) -> None:
        copy = build_copy_bundle(template_name="kit_index_document.html.j2", context={})
        self.assertEqual(copy["title"], "Recovery Kit Index")
        self.assertEqual(copy["subtitle"], "Inventory + Custody Log")
        self.assertEqual(copy["chain_of_custody_label"], "Chain of Custody")

    def test_unknown_template_returns_empty_bundle(self) -> None:
        copy = build_copy_bundle(template_name="unknown_template.html.j2", context={})
        self.assertEqual(copy, {})


if __name__ == "__main__":
    unittest.main()
