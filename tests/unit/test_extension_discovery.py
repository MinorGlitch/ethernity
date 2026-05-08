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

import tempfile
import unittest
from pathlib import Path

from ethernity.extensions import (
    discover_extension_directories,
    discover_validated_extension_directories,
)


class TestExtensionDiscovery(unittest.TestCase):
    def test_returns_empty_when_extensions_dir_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(discover_extension_directories(tmpdir), ())

    def test_discovers_sorted_canonical_directories_and_ignores_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            (extensions_dir / "02").mkdir(parents=True)
            (extensions_dir / ".staging-3-abcd").mkdir(parents=True)
            (extensions_dir / "notes").mkdir(parents=True)

            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "recovery_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "02" / "qr_document-02-cafebabedeadbeef.pdf")
            self._write(extensions_dir / "02" / "recovery_document-02-cafebabedeadbeef.pdf")
            self._write(extensions_dir / "02" / "shard-02-cafebabedeadbeef-1-of-2.pdf")

            discovered = discover_extension_directories(tmpdir)

            self.assertEqual([item.dir_name for item in discovered], ["01", "02"])
            self.assertEqual(discovered[0].doc_id_hex, "deadbeefcafebabe")
            self.assertEqual(discovered[1].doc_id_hex, "cafebabedeadbeef")
            self.assertEqual(
                [carrier.doc_type for carrier in discovered[1].main_carriers],
                ["qr_document", "recovery_document"],
            )
            self.assertIsNone(discovered[1].recovery_kit_index_carrier)
            self.assertEqual(
                [
                    (carrier.doc_type, carrier.share_index, carrier.share_count)
                    for carrier in discovered[1].shard_carriers
                ],
                [("shard", 1, 2)],
            )

    def test_discovers_numeric_order_after_index_99(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            for index in range(1, 101):
                dir_name = f"{index:02d}" if index < 100 else str(index)
                (extensions_dir / dir_name).mkdir(parents=True, exist_ok=True)
                self._write(
                    extensions_dir / dir_name / f"qr_document-{dir_name}-deadbeefcafebabe.pdf"
                )
                self._write(
                    extensions_dir / dir_name / f"recovery_document-{dir_name}-deadbeefcafebabe.pdf"
                )

            discovered = discover_extension_directories(tmpdir)

            self.assertEqual(discovered[9].dir_name, "10")
            self.assertEqual(discovered[98].dir_name, "99")
            self.assertEqual(discovered[99].dir_name, "100")

    def test_discovers_recovery_kit_index_without_treating_it_as_payload_carrier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)

            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "recovery_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "recovery_kit_index-01-deadbeefcafebabe.pdf")

            discovered = discover_extension_directories(tmpdir)

            self.assertEqual(
                [carrier.doc_type for carrier in discovered[0].main_carriers],
                ["qr_document", "recovery_document"],
            )
            self.assertIsNotNone(discovered[0].recovery_kit_index_carrier)
            self.assertEqual(
                discovered[0].recovery_kit_index_carrier.doc_type,
                "recovery_kit_index",
            )

    def test_rejects_non_canonical_decimal_directory_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "001").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "non-canonical extension directory name"):
                discover_extension_directories(tmpdir)

    def test_rejects_extension_directory_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            (extensions_dir / "03").mkdir(parents=True)
            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "recovery_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "03" / "qr_document-03-cafebabedeadbeef.pdf")
            self._write(extensions_dir / "03" / "recovery_document-03-cafebabedeadbeef.pdf")

            with self.assertRaisesRegex(ValueError, "sequential with no gaps"):
                discover_extension_directories(tmpdir)

    def test_rejects_missing_main_carriers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            self._write(extensions_dir / "01" / "shard-01-deadbeefcafebabe-1-of-2.pdf")

            with self.assertRaisesRegex(ValueError, "must contain both payload MAIN carriers"):
                discover_extension_directories(tmpdir)

    def test_rejects_partial_payload_main_carrier_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")

            with self.assertRaisesRegex(ValueError, "missing required payload MAIN carriers"):
                discover_extension_directories(tmpdir)

    def test_rejects_recovery_only_payload_main_carrier_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            self._write(extensions_dir / "01" / "recovery_document-01-deadbeefcafebabe.pdf")

            with self.assertRaisesRegex(ValueError, "missing required payload MAIN carriers"):
                discover_extension_directories(tmpdir)

    def test_rejects_main_filename_index_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            self._write(extensions_dir / "01" / "qr_document-02-deadbeefcafebabe.pdf")

            with self.assertRaisesRegex(ValueError, "does not match directory 01"):
                discover_extension_directories(tmpdir)

    def test_rejects_conflicting_main_carrier_doc_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "recovery_document-01-cafebabedeadbeef.pdf")

            with self.assertRaisesRegex(ValueError, "conflicting MAIN carrier doc_ids"):
                discover_extension_directories(tmpdir)

    def test_rejects_unexpected_artifact_in_canonical_extension_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "recovery_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "README.txt")

            with self.assertRaisesRegex(ValueError, "contains unexpected artifact: README.txt"):
                discover_extension_directories(tmpdir)

    def test_rejects_unexpected_non_file_entry_in_canonical_extension_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            extension_dir = extensions_dir / "01"
            extension_dir.mkdir(parents=True)
            self._write(extension_dir / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extension_dir / "recovery_document-01-deadbeefcafebabe.pdf")
            (extension_dir / "nested").mkdir()

            with self.assertRaisesRegex(
                ValueError,
                "contains unexpected non-file entry: nested",
            ):
                discover_extension_directories(tmpdir)

    def test_rejects_shard_doc_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "recovery_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "shard-01-cafebabedeadbeef-1-of-2.pdf")

            with self.assertRaisesRegex(ValueError, "shard carrier doc_id does not match MAIN"):
                discover_extension_directories(tmpdir)

    def test_rejects_duplicate_shard_share_index_with_different_share_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "recovery_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "shard-01-deadbeefcafebabe-1-of-2.pdf")
            self._write(extensions_dir / "01" / "shard-01-deadbeefcafebabe-1-of-3.pdf")

            with self.assertRaisesRegex(ValueError, "duplicate shard carrier shard 1-of-3"):
                discover_extension_directories(tmpdir)

    def test_rejects_duplicate_main_doc_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe-copy.pdf")

            with self.assertRaisesRegex(ValueError, "invalid extension MAIN carrier filename"):
                discover_extension_directories(tmpdir)

    def test_validated_discovery_preserves_valid_prefix_before_invalid_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            (extensions_dir / "01").mkdir(parents=True)
            (extensions_dir / "02").mkdir(parents=True)
            self._write(extensions_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "01" / "recovery_document-01-deadbeefcafebabe.pdf")
            self._write(extensions_dir / "02" / "qr_document-02-cafebabedeadbeef.pdf")

            discovery = discover_validated_extension_directories(tmpdir)

        self.assertEqual([item.dir_name for item in discovery.directories], ["01"])
        self.assertEqual(discovery.first_invalid_dir_name, "02")
        self.assertIn("missing required payload MAIN carriers", discovery.first_invalid_message)

    def test_rejects_symlinked_extensions_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            target_dir = Path(tmpdir) / "external-extensions"
            root_dir.mkdir()
            (target_dir / "01").mkdir(parents=True)
            self._write(target_dir / "01" / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(target_dir / "01" / "recovery_document-01-deadbeefcafebabe.pdf")
            try:
                (root_dir / "extensions").symlink_to(target_dir, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "extensions path must not be a symlink"):
                discover_extension_directories(root_dir)

    def test_rejects_dangling_symlinked_extensions_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            root_dir.mkdir()
            try:
                (root_dir / "extensions").symlink_to(
                    Path(tmpdir) / "missing-extensions",
                    target_is_directory=True,
                )
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            discovery = discover_validated_extension_directories(root_dir)

        self.assertEqual(discovery.directories, ())
        self.assertEqual(discovery.first_invalid_dir_name, "extensions")
        self.assertEqual(discovery.first_invalid_message, "extensions path must not be a symlink")

    def test_rejects_symlinked_extension_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            extensions_dir = Path(tmpdir) / "extensions"
            extension_dir = extensions_dir / "01"
            extension_dir.mkdir(parents=True)
            external_pdf = Path(tmpdir) / "external.pdf"
            external_pdf.write_bytes(b"placeholder")
            try:
                (extension_dir / "qr_document-01-deadbeefcafebabe.pdf").symlink_to(external_pdf)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            self._write(extension_dir / "recovery_document-01-deadbeefcafebabe.pdf")

            with self.assertRaisesRegex(ValueError, "must not contain symlinked artifacts"):
                discover_extension_directories(tmpdir)

    @staticmethod
    def _write(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"placeholder")
