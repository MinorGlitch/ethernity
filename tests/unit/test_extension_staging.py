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

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ethernity.extensions as extension_facade
from ethernity.extensions import (
    ExtensionPublishPolicy,
    create_extension_staging_dir,
    create_staged_extension_artifact_plan,
    preflight_extension_publish_target,
)
from ethernity.extensions.staging import validate_staged_extension_dir


class TestExtensionStaging(unittest.TestCase):
    def _assert_private_mode_when_supported(self, path: Path) -> None:
        if os.name == "nt":
            return
        self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_layout_validator_is_not_a_package_facade_export(self) -> None:
        self.assertFalse(hasattr(extension_facade, "validate_staged_extension_dir"))
        self.assertFalse(hasattr(extension_facade, "ValidatedStagedExtension"))

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

    def test_create_staged_extension_artifact_plan_uses_index_100_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planned = create_staged_extension_artifact_plan(
                tmpdir,
                index=100,
                doc_id_hex="deadbeefcafebabe",
                nonce="abc123",
                publish_policy=ExtensionPublishPolicy(
                    require_recovery_kit_index=True,
                    passphrase_shard_count=1,
                    signing_key_shard_count=1,
                ),
            )

            self.assertEqual(planned.final_dir.name, "100")
            self.assertEqual(
                planned.qr_document_path.name,
                "qr_document-100-deadbeefcafebabe.pdf",
            )
            self.assertEqual(
                planned.recovery_document_path.name,
                "recovery_document-100-deadbeefcafebabe.pdf",
            )
            self.assertEqual(
                planned.recovery_kit_index_path.name if planned.recovery_kit_index_path else None,
                "recovery_kit_index-100-deadbeefcafebabe.pdf",
            )
            self.assertEqual(
                [path.name for path in planned.shard_paths],
                ["shard-100-deadbeefcafebabe-1-of-1.pdf"],
            )
            self.assertEqual(
                [path.name for path in planned.signing_key_shard_paths],
                ["signing-key-shard-100-deadbeefcafebabe-1-of-1.pdf"],
            )

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
            self._assert_private_mode_when_supported(output_root)
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

    def test_create_staging_dir_rejects_missing_canonical_publish_root_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "scan-output-root"

            with self.assertRaisesRegex(
                ValueError,
                "canonical extension publish root must already exist",
            ):
                create_extension_staging_dir(
                    missing_root,
                    index=1,
                    nonce="abc123",
                    allow_missing_root=True,
                    require_empty_extensions=True,
                )

            self.assertFalse(missing_root.exists())

    def test_create_staged_extension_artifact_plan_rejects_missing_canonical_publish_root_creation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "scan-output-root"

            with self.assertRaisesRegex(
                ValueError,
                "canonical extension publish root must already exist",
            ):
                create_staged_extension_artifact_plan(
                    missing_root,
                    index=1,
                    doc_id_hex="deadbeefcafebabe",
                    nonce="abc123",
                    publish_policy=ExtensionPublishPolicy(),
                    allow_missing_root=True,
                )

            self.assertFalse(missing_root.exists())

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

    def test_preflight_extension_publish_target_rejects_missing_canonical_root_creation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "scan-output-root"

            with self.assertRaisesRegex(
                ValueError,
                "canonical extension publish root must already exist",
            ):
                preflight_extension_publish_target(
                    missing_root,
                    index=1,
                    allow_missing_root=True,
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

    def test_preflight_ignores_obsolete_per_destination_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "extensions" / ".01.lock"
            lock_path.parent.mkdir(parents=True)
            lock_path.touch()

            preflight_extension_publish_target(tmpdir, index=1)

    def test_preflight_extension_publish_target_accepts_persistent_chain_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "extensions" / ".chain.lock"
            lock_path.parent.mkdir(parents=True)
            lock_path.touch()

            preflight_extension_publish_target(
                tmpdir,
                index=1,
                require_empty_extensions=True,
            )

    def test_preflight_loose_target_accepts_persistent_chain_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / ".chain.lock"
            lock_path.touch()

            preflight_extension_publish_target(
                tmpdir,
                index=1,
                publish_layout="loose",
                require_empty_root=True,
            )

    def test_preflight_loose_target_rejects_chain_lock_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / ".chain.lock"
            lock_path.mkdir()

            with self.assertRaisesRegex(ValueError, "entire dedicated output directory"):
                preflight_extension_publish_target(
                    tmpdir,
                    index=1,
                    publish_layout="loose",
                    require_empty_root=True,
                )

    def test_preflight_loose_target_explains_interrupted_staging_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / ".staging-1-abc123").mkdir()

            with self.assertRaisesRegex(ValueError, "entire dedicated output directory"):
                preflight_extension_publish_target(
                    tmpdir,
                    index=1,
                    publish_layout="loose",
                    require_empty_root=True,
                )

    def test_preflight_loose_target_preserves_published_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "extension-01-deadbeefcafebabe").mkdir()

            with self.assertRaisesRegex(ValueError, "preserve that directory"):
                preflight_extension_publish_target(
                    tmpdir,
                    index=1,
                    publish_layout="loose",
                    require_empty_root=True,
                )

    def test_preflight_rejects_obsolete_chain_lock_directory_with_doctor_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "extensions" / ".chain.lock"
            lock_path.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, r"run doctor .* --repair --yes"):
                preflight_extension_publish_target(tmpdir, index=1)

    def test_validate_staged_extension_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=1, nonce="abc123")
            self._assert_private_mode_when_supported(staging_dir)
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
            self.assertEqual(validated.doc_id_hex, "deadbeefcafebabe")
            self.assertEqual(validated.final_dir_name, "01")
            self.assertTrue(staging_dir.exists())

    def test_validate_rejects_missing_chain_bound_recovery_kit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_dir = create_extension_staging_dir(tmpdir, index=1, nonce="abc123")
            (staging_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"qr")
            (staging_dir / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"recovery")

            with self.assertRaisesRegex(ValueError, "required MAIN artifacts: recovery_kit"):
                validate_staged_extension_dir(
                    staging_dir,
                    expected_index=1,
                    publish_policy=ExtensionPublishPolicy(),
                )

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
        if path.name.startswith("recovery_document-"):
            kit_name = path.name.replace("recovery_document-", "recovery_kit-", 1)
            (path.parent / kit_name).write_bytes(data)
