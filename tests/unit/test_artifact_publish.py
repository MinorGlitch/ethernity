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

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ethernity.artifacts.publish import (
    TRANSACTION_METADATA_NAME,
    PublicationTransaction,
    create_sibling_staging_dir,
    exclusive_advisory_lock,
    promote_staged_artifact_dir,
    publish_staged_artifacts,
    read_transaction_metadata,
    sync_directory_metadata,
    write_transaction_metadata,
)


class TestArtifactPublish(unittest.TestCase):
    def test_directory_sync_fails_explicitly_when_unavailable(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.artifacts.publish._directory_metadata_sync_supported",
                return_value=True,
            ),
            mock.patch(
                "ethernity.artifacts.publish._open_directory_fd",
                side_effect=OSError("unsupported"),
            ),
        ):
            with self.assertRaisesRegex(OSError, "directory metadata sync unavailable"):
                sync_directory_metadata(tmpdir)

    def test_directory_sync_is_portable_on_windows(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.artifacts.publish._directory_metadata_sync_supported",
                return_value=False,
            ),
            mock.patch("ethernity.artifacts.publish._open_directory_fd") as open_directory,
        ):
            sync_directory_metadata(tmpdir)

        open_directory.assert_not_called()

    def test_transaction_metadata_records_identity_and_excludes_itself_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)
            lock_path = final_dir.parent / ".publication.lock"
            journal_written_under_lock: list[bool] = []

            def _populate() -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            def _write_metadata(*args, **kwargs):
                with self.assertRaisesRegex(ValueError, "already in progress"):
                    with exclusive_advisory_lock(lock_path, operation_name="competing publisher"):
                        pass
                journal_written_under_lock.append(True)
                return write_transaction_metadata(*args, **kwargs)

            transaction = PublicationTransaction(
                root_hash="11" * 32,
                expected_parent_hash="22" * 32,
                new_index=3,
                new_hash="33" * 32,
            )
            with mock.patch(
                "ethernity.artifacts.publish.write_transaction_metadata",
                side_effect=_write_metadata,
            ):
                result = publish_staged_artifacts(
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                    populate=_populate,
                    lock_path=lock_path,
                    transaction=transaction,
                    durability="required",
                )

            recorded, snapshot = read_transaction_metadata(result.final_dir)
            self.assertEqual(journal_written_under_lock, [True])
            self.assertEqual(recorded.root_hash, transaction.root_hash)
            self.assertEqual(recorded.expected_parent_hash, transaction.expected_parent_hash)
            self.assertEqual(recorded.new_index, 3)
            self.assertEqual(recorded.new_hash, transaction.new_hash)
            self.assertIsNotNone(recorded.transaction_uuid)
            self.assertEqual(snapshot, (("qr_document.pdf", 2, snapshot[0][2]),))
            self.assertNotIn(TRANSACTION_METADATA_NAME, {item[0] for item in snapshot})

    def test_publish_staged_artifacts_promotes_validated_staging_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)

            def _populate() -> str:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")
                return "rendered"

            def _validate_staging(path: Path) -> None:
                self.assertEqual(path, staging_dir)
                self.assertTrue((path / "qr_document.pdf").is_file())

            result = publish_staged_artifacts(
                staging_dir=staging_dir,
                final_dir=final_dir,
                populate=_populate,
                validate_staging=_validate_staging,
            )

            self.assertEqual(result.payload, "rendered")
            self.assertEqual(result.final_dir, final_dir)
            self.assertTrue((final_dir / "qr_document.pdf").is_file())
            self.assertFalse((final_dir / TRANSACTION_METADATA_NAME).exists())
            self.assertFalse(staging_dir.exists())
            self.assertFalse((final_dir.parent / ".backup-deadbeef.lock").exists())

    def test_publish_staged_artifacts_rejects_mutation_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)

            def _populate() -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            def _mutate_after_snapshot(_payload: None) -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"changed")

            with self.assertRaisesRegex(ValueError, "artifacts changed before promotion"):
                publish_staged_artifacts(
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                    populate=_populate,
                    validate_artifacts=_mutate_after_snapshot,
                    lock_path=final_dir.parent / ".publication.lock",
                    durability="required",
                )

            self.assertFalse(staging_dir.exists())
            self.assertFalse(final_dir.exists())

    def test_publish_staged_artifacts_preserves_replacement_staging_dir_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)
            moved_staging_dir = Path(tmpdir) / "moved-staging"

            def _populate() -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            def _swap_staging_dir(_payload: None) -> None:
                staging_dir.rename(moved_staging_dir)
                staging_dir.mkdir()
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            with self.assertRaisesRegex(ValueError, "staging_dir changed before promotion"):
                publish_staged_artifacts(
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                    populate=_populate,
                    validate_artifacts=_swap_staging_dir,
                    lock_path=final_dir.parent / ".publication.lock",
                    durability="required",
                )

            self.assertTrue((moved_staging_dir / "qr_document.pdf").is_file())
            self.assertTrue((staging_dir / "qr_document.pdf").is_file())
            self.assertFalse(final_dir.exists())

    def test_publish_staged_artifacts_rechecks_final_dir_under_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)

            def _populate() -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            def _create_final_after_lock(_path: Path) -> None:
                final_dir.mkdir()

            with self.assertRaisesRegex(ValueError, "already exists"):
                publish_staged_artifacts(
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                    populate=_populate,
                    validate_staging=_create_final_after_lock,
                    lock_path=final_dir.parent / ".publication.lock",
                    durability="required",
                )

            self.assertFalse(staging_dir.exists())
            self.assertTrue(final_dir.exists())

    def test_promote_runs_promotion_validator_under_custom_lock_before_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)
            lock_parent = Path(tmpdir) / "extensions"
            lock_parent.mkdir()
            lock_dir = lock_parent / ".chain.lock"
            (staging_dir / "qr_document.pdf").write_bytes(b"qr")
            observed: list[tuple[bool, bool, bool]] = []

            def _validate_promotion() -> None:
                observed.append((lock_dir.is_file(), final_dir.exists(), staging_dir.exists()))

            promoted = promote_staged_artifact_dir(
                staging_dir,
                final_dir,
                validate_promotion=_validate_promotion,
                lock_path=lock_dir,
                durability="required",
            )

            self.assertEqual(promoted, final_dir)
            self.assertEqual(observed, [(True, False, True)])
            self.assertTrue(lock_dir.is_file())
            self.assertFalse(staging_dir.exists())
            self.assertTrue((final_dir / "qr_document.pdf").is_file())

    def test_promote_rejects_a_held_advisory_lock_without_deleting_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)
            lock_path = Path(tmpdir) / ".chain.lock"
            (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            with exclusive_advisory_lock(lock_path, operation_name="test"):
                with self.assertRaisesRegex(ValueError, "already in progress"):
                    promote_staged_artifact_dir(
                        staging_dir,
                        final_dir,
                        lock_path=lock_path,
                        durability="required",
                    )

            self.assertTrue(lock_path.is_file())
            self.assertTrue(staging_dir.is_dir())

    def test_promote_rejects_obsolete_directory_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)
            lock_path = Path(tmpdir) / ".chain.lock"
            lock_path.mkdir()
            (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            with self.assertRaisesRegex(ValueError, "persistent regular file"):
                promote_staged_artifact_dir(
                    staging_dir,
                    final_dir,
                    lock_path=lock_path,
                    durability="required",
                )

            self.assertTrue(staging_dir.is_dir())
            self.assertFalse(final_dir.exists())

    def test_promote_rejects_parent_replacement_before_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "publish"
            moved_root = Path(tmpdir) / "moved-publish"
            root.mkdir()
            final_dir = root / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)
            (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            def _replace_parent() -> None:
                try:
                    root.rename(moved_root)
                    root.mkdir()
                except OSError as exc:
                    self.skipTest(f"parent replacement unavailable: {exc}")

            with self.assertRaisesRegex(ValueError, "parent changed before promotion"):
                promote_staged_artifact_dir(
                    staging_dir,
                    final_dir,
                    validate_promotion=_replace_parent,
                    lock_path=root / ".publication.lock",
                    durability="required",
                )

            self.assertFalse(final_dir.exists())
            self.assertTrue((moved_root / staging_dir.name / "qr_document.pdf").is_file())

    def test_publish_staged_artifacts_cleans_up_on_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)

            def _populate() -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                publish_staged_artifacts(
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                    populate=_populate,
                    lock_path=final_dir.parent / ".publication.lock",
                    durability="required",
                )

            self.assertFalse(staging_dir.exists())
            self.assertFalse(final_dir.exists())
