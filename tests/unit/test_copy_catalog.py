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

from ethernity.render.copy_catalog import build_copy_bundle, build_instruction_copy


class TestCopyCatalog(unittest.TestCase):
    def test_instruction_copy_preserves_document_specific_instructions(self) -> None:
        expected_lines = {
            "main": (
                "Record all segment labels for this document set.",
                "Scan segments in any order; capture each label once.",
                "Use Recovery Document text fallback only if scanning fails.",
            ),
            "recovery": (
                "This document contains recovery keys and full text fallback.",
                "Keep it separate from the main document.",
                "Fallback includes AUTH + MAIN sections; keep the labels when transcribing.",
            ),
            "kit": (
                "Scan every QR code left to right, top to bottom.",
                (
                    "QR #1 is the shell. Paste it first, then paste every remaining QR in "
                    "order (no separators)."
                ),
                "Save the result as recovery_kit.bundle.html.",
                "Open that file in a browser (offline) to run the kit.",
            ),
        }

        for doc_type, lines in expected_lines.items():
            with self.subTest(doc_type=doc_type):
                instructions = build_instruction_copy(doc_type=doc_type, context={})
                self.assertEqual(instructions.label, "Instructions")
                self.assertEqual(instructions.lines, lines)

        self.assertEqual(
            build_instruction_copy(doc_type="kit_index", context={}).lines,
            expected_lines["kit"],
        )

    def test_shard_instruction_copy_formats_context_for_both_shard_types(self) -> None:
        context = {"shard_index": "2", "shard_total": 5.0, "shard_threshold": 3}
        for doc_type, secret in (("shard", "secret"), ("signing_key_shard", "signing key")):
            with self.subTest(doc_type=doc_type):
                instructions = build_instruction_copy(doc_type=doc_type, context=context)
                self.assertEqual(
                    instructions.lines,
                    (
                        f"Shard 2 of 5. This shard alone cannot recover the {secret}.",
                        "Recovery requires 3/5 shards. Keep each shard secure.",
                        "Keep it apart from recovery documents and other shards.",
                    ),
                )

    def test_main_bundle_contains_document_specific_copy(self) -> None:
        copy = build_copy_bundle(doc_type="main", context={})
        self.assertEqual(copy["title"], "Main Document")
        self.assertEqual(copy["subtitle"], "Passphrase-protected payload")
        self.assertEqual(copy["header_guidance"], "Use with matching recovery document")
        self.assertEqual(copy["segment_prefix"], "Segment")

    def test_extension_main_bundle_is_origin_aware(self) -> None:
        copy = build_copy_bundle(
            doc_type="main",
            context={"origin": {"kind": "extension", "extension_index": 2}},
        )
        self.assertEqual(copy["title"], "Extension Main Document")
        self.assertEqual(copy["subtitle"], "Extension 02 - Added and replaced files")
        self.assertEqual(copy["origin_badge"], "Extension 02")
        self.assertIn("root backup", copy["header_guidance"])

    def test_extension_recovery_bundle_describes_encoded_fallback(self) -> None:
        copy = build_copy_bundle(
            doc_type="recovery",
            context={"origin": {"kind": "extension", "extension_index": 2}},
        )
        self.assertEqual(copy["origin_badge"], "Extension 02")
        self.assertIn("encoded fallback lines", copy["transcription_guidance"])
        self.assertNotIn("decrypted", copy["transcription_guidance"].lower())

    def test_rebuild_recovery_bundle_is_origin_aware(self) -> None:
        copy = build_copy_bundle(
            doc_type="recovery",
            context={"origin": {"kind": "rebuilt_backup", "extension_index": None}},
        )
        self.assertEqual(copy["title"], "Recovery Document")
        self.assertEqual(copy["origin_badge"], "Rebuilt Backup")
        self.assertIn("rebuilt backup", copy["warning_body"].lower())

    def test_rebuild_main_bundle_is_origin_aware(self) -> None:
        copy = build_copy_bundle(
            doc_type="main",
            context={"origin": {"kind": "rebuilt_backup", "extension_index": None}},
        )
        self.assertEqual(copy["title"], "Rebuilt Backup Main Document")
        self.assertEqual(copy["origin_badge"], "Rebuilt Backup")
        self.assertIn("backup", copy["subtitle"].lower())

    def test_shard_bundle_formats_dynamic_warning(self) -> None:
        copy = build_copy_bundle(
            doc_type="shard",
            context={"shard_index": 2, "shard_total": 5, "shard_threshold": 3},
        )
        self.assertEqual(copy["title"], "Shard Document")
        self.assertEqual(copy["subtitle"], "Shard 2 of 5")
        self.assertIn("shard 2 of 5", copy["warning_body"])
        self.assertIn("Recovery requires 3/5 shards.", copy["warning_body"])

    def test_signing_key_shard_bundle_formats_dynamic_subtitle(self) -> None:
        copy = build_copy_bundle(
            doc_type="signing_key_shard",
            context={"shard_index": 4, "shard_total": 7},
        )
        self.assertEqual(copy["title"], "Signing Key Shard")
        self.assertEqual(copy["subtitle"], "Signing key shard 4 of 7")
        self.assertEqual(copy["key_share_label"], "Key Share")

    def test_rebuild_signing_key_shard_bundle_mentions_backup(self) -> None:
        copy = build_copy_bundle(
            doc_type="signing_key_shard",
            context={
                "shard_index": 4,
                "shard_total": 7,
                "origin": {"kind": "rebuilt_backup", "extension_index": None},
            },
        )
        self.assertEqual(copy["title"], "Rebuilt Backup Signing Key Shard")
        self.assertEqual(
            copy["subtitle"],
            "Rebuilt Backup - Signing key shard 4 of 7",
        )
        self.assertEqual(copy["origin_badge"], "Rebuilt Backup")

    def test_rebuild_shard_bundle_mentions_backup(self) -> None:
        copy = build_copy_bundle(
            doc_type="shard",
            context={
                "shard_index": 1,
                "shard_total": 3,
                "shard_threshold": 2,
                "origin": {"kind": "rebuilt_backup", "extension_index": None},
            },
        )
        self.assertEqual(copy["title"], "Rebuilt Backup Shard Document")
        self.assertEqual(copy["origin_badge"], "Rebuilt Backup")
        self.assertIn("backup shard", copy["warning_body"].lower())

    def test_kit_index_bundle_contains_expected_copy(self) -> None:
        copy = build_copy_bundle(doc_type="kit_index", context={})
        self.assertEqual(copy["title"], "Recovery Kit Index")
        self.assertEqual(copy["subtitle"], "Inventory + Handling Log")
        self.assertEqual(copy["handling_log_label"], "Handling Log")

    def test_rebuild_kit_index_bundle_mentions_backup(self) -> None:
        copy = build_copy_bundle(
            doc_type="kit_index",
            context={"origin": {"kind": "rebuilt_backup", "extension_index": None}},
        )
        self.assertEqual(copy["title"], "Rebuilt Backup Recovery Kit Index")
        self.assertEqual(copy["origin_badge"], "Rebuilt Backup")
        self.assertIn("rebuilt backup", copy["warning_body"].lower())

    def test_unknown_doc_type_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported render doc_type"):
            build_copy_bundle(doc_type="unknown", context={})
        with self.assertRaisesRegex(ValueError, "unsupported render doc_type"):
            build_instruction_copy(doc_type="unknown", context={})


if __name__ == "__main__":
    unittest.main()
