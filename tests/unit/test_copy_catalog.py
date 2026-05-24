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
        copy = build_copy_bundle(doc_type="main", context={})
        self.assertEqual(copy["title"], "Main Document")
        self.assertEqual(copy["subtitle"], "Passphrase-protected payload")
        self.assertEqual(copy["header_guidance"], "Use with matching recovery document")
        self.assertEqual(copy["segment_prefix"], "Segment")

    def test_extension_main_bundle_is_lineage_aware(self) -> None:
        copy = build_copy_bundle(
            doc_type="main",
            context={"lineage": {"kind": "extension", "extension_index": 2}},
        )
        self.assertEqual(copy["title"], "Extension Main Document")
        self.assertEqual(copy["subtitle"], "Extension 02 - Appended generation payload")
        self.assertEqual(copy["lineage_badge"], "Extension 02")
        self.assertIn("root backup", copy["header_guidance"])

    def test_extension_recovery_bundle_describes_encoded_fallback(self) -> None:
        copy = build_copy_bundle(
            doc_type="recovery",
            context={"lineage": {"kind": "extension", "extension_index": 2}},
        )
        self.assertEqual(copy["lineage_badge"], "Extension 02")
        self.assertIn("encoded fallback lines", copy["transcription_helper"])
        self.assertNotIn("decrypted", copy["transcription_helper"].lower())

    def test_compaction_recovery_bundle_is_lineage_aware(self) -> None:
        copy = build_copy_bundle(
            doc_type="recovery",
            context={"lineage": {"kind": "compaction_checkpoint", "extension_index": None}},
        )
        self.assertEqual(copy["title"], "Recovery Document")
        self.assertEqual(copy["lineage_badge"], "Compaction Checkpoint")
        self.assertIn("compaction checkpoint", copy["warning_body"].lower())

    def test_compaction_main_bundle_is_lineage_aware(self) -> None:
        copy = build_copy_bundle(
            doc_type="main",
            context={"lineage": {"kind": "compaction_checkpoint", "extension_index": None}},
        )
        self.assertEqual(copy["title"], "Compaction Checkpoint Main Document")
        self.assertEqual(copy["lineage_badge"], "Compaction Checkpoint")
        self.assertIn("checkpoint", copy["subtitle"].lower())

    def test_shard_bundle_formats_dynamic_warning(self) -> None:
        copy = build_copy_bundle(
            doc_type="shard",
            context={"shard_index": 2, "shard_total": 5, "shard_threshold": 3},
        )
        self.assertEqual(copy["title"], "Shard Document")
        self.assertEqual(copy["subtitle"], "Shard 2 of 5")
        self.assertIn("shard 2 of 5", copy["warning_body"])
        self.assertIn("Recovery requires 3/5 shards.", copy["warning_body"])

    def test_extension_shard_bundle_mentions_generation(self) -> None:
        copy = build_copy_bundle(
            doc_type="shard",
            context={
                "shard_index": 2,
                "shard_total": 5,
                "shard_threshold": 3,
                "lineage": {"kind": "extension", "extension_index": 2},
            },
        )
        self.assertEqual(copy["title"], "Extension Shard Document")
        self.assertEqual(copy["subtitle"], "Extension 02 - Shard 2 of 5")
        self.assertIn("extension 02 shard 2 of 5", copy["warning_body"].lower())

    def test_signing_key_shard_bundle_formats_dynamic_subtitle(self) -> None:
        copy = build_copy_bundle(
            doc_type="signing_key_shard",
            context={"shard_index": 4, "shard_total": 7},
        )
        self.assertEqual(copy["title"], "Signing Authority Shard")
        self.assertEqual(copy["subtitle"], "Signing authority shard 4 of 7")
        self.assertEqual(copy["key_material_label"], "Key Material Payload")

    def test_compaction_signing_key_shard_bundle_mentions_checkpoint(self) -> None:
        copy = build_copy_bundle(
            doc_type="signing_key_shard",
            context={
                "shard_index": 4,
                "shard_total": 7,
                "lineage": {"kind": "compaction_checkpoint", "extension_index": None},
            },
        )
        self.assertEqual(copy["title"], "Compaction Checkpoint Signing Authority Shard")
        self.assertEqual(
            copy["subtitle"],
            "Compaction Checkpoint - Signing authority shard 4 of 7",
        )
        self.assertEqual(copy["lineage_badge"], "Compaction Checkpoint")

    def test_compaction_shard_bundle_mentions_checkpoint(self) -> None:
        copy = build_copy_bundle(
            doc_type="shard",
            context={
                "shard_index": 1,
                "shard_total": 3,
                "shard_threshold": 2,
                "lineage": {"kind": "compaction_checkpoint", "extension_index": None},
            },
        )
        self.assertEqual(copy["title"], "Compaction Checkpoint Shard Document")
        self.assertEqual(copy["lineage_badge"], "Compaction Checkpoint")
        self.assertIn("checkpoint shard", copy["warning_body"].lower())

    def test_kit_index_bundle_contains_expected_copy(self) -> None:
        copy = build_copy_bundle(doc_type="kit_index", context={})
        self.assertEqual(copy["title"], "Recovery Kit Index")
        self.assertEqual(copy["subtitle"], "Inventory + Custody Log")
        self.assertEqual(copy["chain_of_custody_label"], "Chain of Custody")

    def test_extension_kit_index_bundle_mentions_extension(self) -> None:
        copy = build_copy_bundle(
            doc_type="kit_index",
            context={"lineage": {"kind": "extension", "extension_index": 3}},
        )
        self.assertEqual(copy["title"], "Extension Recovery Kit Index")
        self.assertEqual(copy["subtitle"], "Extension 03 - Inventory + Custody Log")
        self.assertEqual(copy["lineage_badge"], "Extension 03")

    def test_compaction_kit_index_bundle_mentions_checkpoint(self) -> None:
        copy = build_copy_bundle(
            doc_type="kit_index",
            context={"lineage": {"kind": "compaction_checkpoint", "extension_index": None}},
        )
        self.assertEqual(copy["title"], "Compaction Checkpoint Recovery Kit Index")
        self.assertEqual(copy["lineage_badge"], "Compaction Checkpoint")
        self.assertIn("compaction checkpoint", copy["warning_body"].lower())

    def test_unknown_doc_type_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported render doc_type"):
            build_copy_bundle(doc_type="unknown", context={})


if __name__ == "__main__":
    unittest.main()
