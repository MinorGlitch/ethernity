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

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.extensions import (
    ExtensionPublishPolicy,
    ValidatedStagedExtension,
    create_extension_staging_dir,
    create_staged_extension_artifact_plan,
    preflight_extension_publish_target,
    promote_staged_extension_dir,
    validate_staged_extension_dir,
)


class TestExtensionStaging(unittest.TestCase):
    def test_create_staged_extension_artifact_plan_returns_canonical_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planned = create_staged_extension_artifact_plan(
                tmpdir,
                index=6,
                doc_id_hex="deadbeefcafebabe",
                nonce="abc123",
                publish_policy=ExtensionPublishPolicy(
                    require_recovery_kit_index=True,
                    passphrase_shard_count=2,
                    signing_key_shard_count=1,
                ),
            )

            self.assertTrue(planned.staging_dir.is_dir())
            self.assertEqual(planned.publish_layout, "canonical")
            self.assertEqual(planned.staging_dir.name, ".staging-6-abc123")
            self.assertEqual(planned.final_dir.name, "06")
            self.assertEqual(
                planned.qr_document_path.name,
                "qr_document-06-deadbeefcafebabe.pdf",
            )
            self.assertEqual(
                planned.recovery_document_path.name,
                "recovery_document-06-deadbeefcafebabe.pdf",
            )
            self.assertEqual(
                planned.recovery_kit_index_path.name if planned.recovery_kit_index_path else None,
                "recovery_kit_index-06-deadbeefcafebabe.pdf",
            )
            self.assertEqual(
                [path.name for path in planned.shard_paths],
                [
                    "shard-06-deadbeefcafebabe-1-of-2.pdf",
                    "shard-06-deadbeefcafebabe-2-of-2.pdf",
                ],
            )
            self.assertEqual(
                [path.name for path in planned.signing_key_shard_paths],
                ["signing-key-shard-06-deadbeefcafebabe-1-of-1.pdf"],
            )

    def test_create_staged_extension_artifact_plan_omits_optional_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planned = create_staged_extension_artifact_plan(
                tmpdir,
                index=2,
                doc_id_hex="cafebabedeadbeef",
                nonce="n",
                publish_policy=ExtensionPublishPolicy(),
            )

            self.assertIsNone(planned.recovery_kit_index_path)
            self.assertEqual(planned.shard_paths, ())
            self.assertEqual(planned.signing_key_shard_paths, ())

    def test_create_staged_extension_artifact_plan_returns_loose_scan_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "scan-output"
            planned = create_staged_extension_artifact_plan(
                output_root,
                index=2,
                doc_id_hex="cafebabedeadbeef",
                nonce="abc123",
                publish_policy=ExtensionPublishPolicy(),
                publish_layout="loose",
                allow_missing_root=True,
                require_empty_root=True,
            )

            self.assertTrue(output_root.is_dir())
            self.assertEqual(output_root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(planned.publish_layout, "loose")
            self.assertEqual(planned.staging_dir.parent, output_root)
            self.assertEqual(planned.staging_dir.name, ".staging-2-abc123")
            self.assertEqual(planned.final_dir, output_root / "extension-02-cafebabedeadbeef")
            self.assertFalse((output_root / "extensions").exists())

    def test_create_staging_dir_rejects_missing_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "missing-root"

            with self.assertRaisesRegex(ValueError, "extension publish root not found"):
                create_extension_staging_dir(missing_root, index=1, nonce="abc123")

    def test_create_staging_dir_can_create_missing_canonical_publish_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "scan-output-root"

            staging_dir = create_extension_staging_dir(
                missing_root,
                index=1,
                nonce="abc123",
                allow_missing_root=True,
                require_empty_extensions=True,
            )

            self.assertTrue(missing_root.is_dir())
            self.assertEqual(missing_root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(staging_dir.parent, missing_root / "extensions")

    def test_preflight_extension_publish_target_accepts_missing_scan_publish_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "scan-output-root"

            preflight_extension_publish_target(
                missing_root,
                index=1,
                publish_layout="loose",
                allow_missing_root=True,
                require_empty_root=True,
            )

            self.assertFalse(missing_root.exists())

    def test_preflight_extension_publish_target_rejects_nonempty_scan_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "notes.txt").write_text("not empty", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "empty directory or missing path",
            ):
                preflight_extension_publish_target(
                    tmpdir,
                    index=2,
                    publish_layout="loose",
                    allow_missing_root=True,
                    require_empty_root=True,
                )

    def test_preflight_extension_publish_target_rejects_non_directory_extensions_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            (root_dir / "extensions").write_text("not a directory", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "extensions path must be a directory"):
                preflight_extension_publish_target(root_dir, index=1)

    def test_preflight_extension_publish_target_rejects_existing_final_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "extensions" / "01"
            final_dir.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "canonical extension directory already exists"):
                preflight_extension_publish_target(tmpdir, index=1)

    def test_preflight_extension_publish_target_rejects_existing_promotion_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_dir = Path(tmpdir) / "extensions" / ".01.lock"
            lock_dir.mkdir(parents=True)

            with self.assertRaisesRegex(
                ValueError,
                "canonical extension directory is already being promoted",
            ):
                preflight_extension_publish_target(tmpdir, index=1)

    def test_preflight_extension_publish_target_rejects_existing_chain_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_dir = Path(tmpdir) / "extensions" / ".chain.lock"
            lock_dir.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "extension chain is already being promoted"):
                preflight_extension_publish_target(tmpdir, index=1)

    def test_validate_and_promote_staged_extension_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=1, nonce="abc123")
            self.assertEqual(staging_dir.stat().st_mode & 0o777, 0o700)
            self._write(staging_dir / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_kit_index-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "shard-01-deadbeefcafebabe-1-of-2.pdf")
            self._write(staging_dir / "shard-01-deadbeefcafebabe-2-of-2.pdf")

            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=1,
                publish_policy=ExtensionPublishPolicy(
                    require_recovery_kit_index=True,
                    passphrase_shard_count=2,
                ),
            )
            final_dir = promote_staged_extension_dir(validated)

            self.assertEqual(validated.doc_id_hex, "deadbeefcafebabe")
            self.assertEqual(final_dir.name, "01")
            self.assertTrue((final_dir / "qr_document-01-deadbeefcafebabe.pdf").exists())
            self.assertFalse(staging_dir.exists())

    def test_promote_rejects_existing_canonical_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=1, nonce="abc123")
            self._write(staging_dir / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf")
            (Path(tmpdir) / "extensions" / "01").mkdir()

            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=1,
                publish_policy=ExtensionPublishPolicy(),
            )

            with self.assertRaisesRegex(ValueError, "canonical extension directory already exists"):
                promote_staged_extension_dir(validated)

            self.assertTrue(staging_dir.exists())

    def test_promote_recomputes_final_dir_from_revalidated_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=1, nonce="abc123")
            self._write(staging_dir / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf")
            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=1,
                publish_policy=ExtensionPublishPolicy(),
            )
            forged = ValidatedStagedExtension(
                staging_dir=validated.staging_dir,
                final_dir_name="02",
                publish_layout=validated.publish_layout,
                doc_id_hex=validated.doc_id_hex,
                expected_index=validated.expected_index,
                publish_policy=validated.publish_policy,
                staging_dir_identity=validated.staging_dir_identity,
                staging_snapshot=validated.staging_snapshot,
                publish_root_identity=validated.publish_root_identity,
                artifact_parent_identity=validated.artifact_parent_identity,
            )

            final_dir = promote_staged_extension_dir(forged)

            self.assertEqual(final_dir.name, "01")
            self.assertTrue((Path(tmpdir) / "extensions" / "01").is_dir())
            self.assertFalse((Path(tmpdir) / "extensions" / "02").exists())

    def test_promote_recomputes_loose_final_dir_from_validated_doc_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_staged_extension_artifact_plan(
                tmpdir,
                index=2,
                doc_id_hex="deadbeefcafebabe",
                nonce="abc123",
                publish_policy=ExtensionPublishPolicy(),
                publish_layout="loose",
                require_empty_root=True,
            ).staging_dir
            self._write(staging_dir / "qr_document-02-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-02-deadbeefcafebabe.pdf")
            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=2,
                publish_policy=ExtensionPublishPolicy(),
                publish_layout="loose",
            )
            forged = ValidatedStagedExtension(
                staging_dir=validated.staging_dir,
                final_dir_name="extension-02-cafebabedeadbeef",
                publish_layout=validated.publish_layout,
                doc_id_hex=validated.doc_id_hex,
                expected_index=validated.expected_index,
                publish_policy=validated.publish_policy,
                staging_dir_identity=validated.staging_dir_identity,
                staging_snapshot=validated.staging_snapshot,
                publish_root_identity=validated.publish_root_identity,
                artifact_parent_identity=validated.artifact_parent_identity,
            )

            final_dir = promote_staged_extension_dir(forged)

            self.assertEqual(final_dir.name, "extension-02-deadbeefcafebabe")
            self.assertTrue((Path(tmpdir) / "extension-02-deadbeefcafebabe").is_dir())
            self.assertFalse((Path(tmpdir) / "extension-02-cafebabedeadbeef").exists())

    def test_promote_rejects_regular_file_swap_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=1, nonce="abc123")
            qr_path = staging_dir / "qr_document-01-deadbeefcafebabe.pdf"
            self._write(qr_path, b"qr")
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf", b"recovery")

            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=1,
                publish_policy=ExtensionPublishPolicy(),
            )
            qr_path.write_bytes(b"different regular file")

            with self.assertRaisesRegex(ValueError, "artifacts changed before promotion"):
                promote_staged_extension_dir(validated)

            self.assertTrue(staging_dir.exists())

    def test_promote_rejects_staging_dir_swapped_for_symlink_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=1, nonce="abc123")
            self._write(staging_dir / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf")

            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=1,
                publish_policy=ExtensionPublishPolicy(),
            )
            external_dir = Path(tmpdir) / "external"
            external_dir.mkdir()
            shutil.rmtree(staging_dir)
            try:
                staging_dir.symlink_to(external_dir, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "validated staging_dir must not be a symlink"):
                promote_staged_extension_dir(validated)

    def test_promote_rejects_staging_dir_recreated_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=1, nonce="abc123")
            self._write(staging_dir / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf")

            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=1,
                publish_policy=ExtensionPublishPolicy(),
            )
            moved_staging_dir = Path(tmpdir) / "extensions" / ".staging-old"
            staging_dir.rename(moved_staging_dir)
            staging_dir.mkdir(mode=0o700)
            self._write(staging_dir / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf")

            with self.assertRaisesRegex(ValueError, "staging directory changed before promotion"):
                promote_staged_extension_dir(validated)

            self.assertTrue(moved_staging_dir.exists())

    def test_promote_rejects_extensions_dir_swap_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            staging_dir = create_extension_staging_dir(root_dir, index=1, nonce="abc123")
            self._write(staging_dir / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf")

            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=1,
                publish_policy=ExtensionPublishPolicy(),
            )
            extensions_dir = root_dir / "extensions"
            moved_extensions_dir = root_dir / "extensions-old"
            extensions_dir.rename(moved_extensions_dir)
            extensions_dir.mkdir()

            with self.assertRaisesRegex(
                ValueError,
                "extensions directory changed before promotion",
            ):
                promote_staged_extension_dir(validated)

            self.assertTrue((moved_extensions_dir / staging_dir.name).is_dir())

    def test_promote_rejects_root_dir_swap_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_root_dir = Path(tmpdir) / "root"
            original_root_dir.mkdir()
            staging_dir = create_extension_staging_dir(
                original_root_dir,
                index=1,
                nonce="abc123",
            )
            self._write(staging_dir / "qr_document-01-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf")

            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=1,
                publish_policy=ExtensionPublishPolicy(),
            )
            moved_root_dir = Path(tmpdir) / "root-old"
            original_root_dir.rename(moved_root_dir)
            original_root_dir.mkdir()
            (original_root_dir / "extensions").mkdir()

            with self.assertRaisesRegex(
                ValueError,
                "extension publish root changed before promotion",
            ):
                promote_staged_extension_dir(validated)

            self.assertTrue((moved_root_dir / "extensions" / staging_dir.name).is_dir())

    def test_promote_rejects_artifact_swapped_for_symlink_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=1, nonce="abc123")
            qr_path = staging_dir / "qr_document-01-deadbeefcafebabe.pdf"
            self._write(qr_path)
            self._write(staging_dir / "recovery_document-01-deadbeefcafebabe.pdf")

            validated = validate_staged_extension_dir(
                staging_dir,
                expected_index=1,
                publish_policy=ExtensionPublishPolicy(),
            )
            external_pdf = Path(tmpdir) / "external.pdf"
            external_pdf.write_bytes(b"placeholder")
            qr_path.unlink()
            try:
                qr_path.symlink_to(external_pdf)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "contains symlinked artifact"):
                promote_staged_extension_dir(validated)
            self.assertTrue(staging_dir.exists())

    def test_validate_rejects_missing_required_main_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=2, nonce="abc123")
            self._write(staging_dir / "qr_document-02-deadbeefcafebabe.pdf")

            with self.assertRaisesRegex(ValueError, "missing required MAIN artifacts"):
                validate_staged_extension_dir(
                    staging_dir,
                    expected_index=2,
                    publish_policy=ExtensionPublishPolicy(),
                )

    def test_validate_rejects_missing_required_shard_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=3, nonce="abc123")
            self._write(staging_dir / "qr_document-03-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-03-deadbeefcafebabe.pdf")
            self._write(staging_dir / "shard-03-deadbeefcafebabe-1-of-2.pdf")

            with self.assertRaisesRegex(ValueError, "include shares 1 through 2"):
                validate_staged_extension_dir(
                    staging_dir,
                    expected_index=3,
                    publish_policy=ExtensionPublishPolicy(passphrase_shard_count=2),
                )

    def test_validate_rejects_unexpected_shards_when_policy_disables_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=4, nonce="abc123")
            self._write(staging_dir / "qr_document-04-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-04-deadbeefcafebabe.pdf")
            self._write(staging_dir / "shard-04-deadbeefcafebabe-1-of-1.pdf")

            with self.assertRaisesRegex(ValueError, "unexpectedly includes shard artifacts"):
                validate_staged_extension_dir(
                    staging_dir,
                    expected_index=4,
                    publish_policy=ExtensionPublishPolicy(),
                )

    def test_validate_rejects_shard_doc_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=5, nonce="abc123")
            self._write(staging_dir / "qr_document-05-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-05-deadbeefcafebabe.pdf")
            self._write(staging_dir / "shard-05-cafebabedeadbeef-1-of-1.pdf")

            with self.assertRaisesRegex(ValueError, "shard artifact doc_id does not match MAIN"):
                validate_staged_extension_dir(
                    staging_dir,
                    expected_index=5,
                    publish_policy=ExtensionPublishPolicy(passphrase_shard_count=1),
                )

    def test_validate_rejects_unexpected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=6, nonce="abc123")
            self._write(staging_dir / "qr_document-06-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-06-deadbeefcafebabe.pdf")
            self._write(staging_dir / "unexpected.txt")

            with self.assertRaisesRegex(ValueError, "unexpected artifact"):
                validate_staged_extension_dir(
                    staging_dir,
                    expected_index=6,
                    publish_policy=ExtensionPublishPolicy(),
                )

    def test_validate_rejects_unexpected_recovery_kit_index_when_policy_disables_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=7, nonce="abc123")
            self._write(staging_dir / "qr_document-07-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-07-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_kit_index-07-deadbeefcafebabe.pdf")

            with self.assertRaisesRegex(
                ValueError,
                "unexpectedly includes recovery_kit_index",
            ):
                validate_staged_extension_dir(
                    staging_dir,
                    expected_index=7,
                    publish_policy=ExtensionPublishPolicy(),
                )

    def test_validate_rejects_missing_required_recovery_kit_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=8, nonce="abc123")
            self._write(staging_dir / "qr_document-08-deadbeefcafebabe.pdf")
            self._write(staging_dir / "recovery_document-08-deadbeefcafebabe.pdf")

            with self.assertRaisesRegex(
                ValueError,
                "missing required MAIN artifacts: recovery_kit_index",
            ):
                validate_staged_extension_dir(
                    staging_dir,
                    expected_index=8,
                    publish_policy=ExtensionPublishPolicy(require_recovery_kit_index=True),
                )

    def test_validate_rejects_symlinked_staging_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=9, nonce="abc123")
            external_pdf = Path(tmpdir) / "external.pdf"
            external_pdf.write_bytes(b"placeholder")
            try:
                (staging_dir / "qr_document-09-deadbeefcafebabe.pdf").symlink_to(external_pdf)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            self._write(staging_dir / "recovery_document-09-deadbeefcafebabe.pdf")

            with self.assertRaisesRegex(ValueError, "contains symlinked artifact"):
                validate_staged_extension_dir(
                    staging_dir,
                    expected_index=9,
                    publish_policy=ExtensionPublishPolicy(),
                )

    def test_create_staging_dir_rejects_symlinked_extensions_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            target_dir = Path(tmpdir) / "external-extensions"
            root_dir.mkdir()
            target_dir.mkdir()
            try:
                (root_dir / "extensions").symlink_to(target_dir, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "extensions path must not be a symlink"):
                create_extension_staging_dir(root_dir, index=10, nonce="abc123")

    def test_create_staging_dir_rejects_extensions_root_symlink_swap_after_mkdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "root"
            extensions_dir = root_dir / "extensions"
            target_dir = Path(tmpdir) / "external-extensions"
            root_dir.mkdir()
            original_mkdir = Path.mkdir

            def _mkdir(
                path: Path,
                mode: int = 0o777,
                parents: bool = False,
                exist_ok: bool = False,
            ) -> None:
                original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)
                if path == extensions_dir:
                    shutil.rmtree(path)
                    original_mkdir(target_dir)
                    try:
                        path.symlink_to(target_dir, target_is_directory=True)
                    except OSError as exc:
                        self.skipTest(f"symlinks unavailable: {exc}")

            with (
                mock.patch.object(Path, "mkdir", autospec=True, side_effect=_mkdir),
                self.assertRaisesRegex(ValueError, "extensions path must not be a symlink"),
            ):
                create_extension_staging_dir(root_dir, index=10, nonce="abc123")

    @staticmethod
    def _write(path: Path, data: bytes = b"placeholder") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
