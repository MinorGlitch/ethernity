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

from ethernity.publication import (
    create_sibling_staging_dir,
    promote_staged_directory,
    publish_staged_directory,
    sync_directory_metadata,
)


class TestDirectoryPublication(unittest.TestCase):
    def test_directory_sync_fails_explicitly_when_unavailable(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.publication._directory_metadata_sync_supported",
                return_value=True,
            ),
            mock.patch(
                "ethernity.publication.open_directory_fd",
                side_effect=OSError("unsupported"),
            ),
        ):
            with self.assertRaisesRegex(OSError, "directory metadata sync unavailable"):
                sync_directory_metadata(tmpdir)

    def test_directory_sync_is_portable_on_windows(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.publication._directory_metadata_sync_supported",
                return_value=False,
            ),
            mock.patch("ethernity.publication.open_directory_fd") as open_directory,
        ):
            sync_directory_metadata(tmpdir)

        open_directory.assert_not_called()

    def test_publish_staged_directory_promotes_validated_staging_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)

            def _populate() -> str:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")
                return "rendered"

            def _validate_staging(path: Path) -> None:
                self.assertEqual(path, staging_dir)
                self.assertTrue((path / "qr_document.pdf").is_file())

            result = publish_staged_directory(
                staging_dir=staging_dir,
                final_dir=final_dir,
                populate=_populate,
                validate_staging=_validate_staging,
            )

            self.assertEqual(result.payload, "rendered")
            self.assertEqual(result.final_dir, final_dir)
            self.assertTrue((final_dir / "qr_document.pdf").is_file())
            self.assertFalse(staging_dir.exists())
            self.assertFalse((final_dir.parent / ".backup-deadbeef.lock").exists())

    def test_publish_staged_directory_rejects_mutation_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)

            def _populate() -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            def _mutate_after_snapshot(_payload: None) -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"changed")

            with self.assertRaisesRegex(ValueError, "staged files changed before promotion"):
                publish_staged_directory(
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                    populate=_populate,
                    validate_result=_mutate_after_snapshot,
                    durability="required",
                )

            self.assertFalse(staging_dir.exists())
            self.assertFalse(final_dir.exists())

    def test_publish_staged_directory_preserves_replacement_staging_dir_on_failure(self) -> None:
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
                publish_staged_directory(
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                    populate=_populate,
                    validate_result=_swap_staging_dir,
                    durability="required",
                )

            self.assertTrue((moved_staging_dir / "qr_document.pdf").is_file())
            self.assertTrue((staging_dir / "qr_document.pdf").is_file())
            self.assertFalse(final_dir.exists())

    def test_publish_staged_directory_rechecks_final_dir_under_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)

            def _populate() -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")

            def _create_final_after_lock(_path: Path) -> None:
                final_dir.mkdir()

            with self.assertRaisesRegex(ValueError, "already exists"):
                publish_staged_directory(
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                    populate=_populate,
                    validate_staging=_create_final_after_lock,
                    durability="required",
                )

            self.assertFalse(staging_dir.exists())
            self.assertTrue(final_dir.exists())

    def test_promote_rejects_reserved_output_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)
            (staging_dir / "qr_document.pdf").write_bytes(b"qr")
            lock_dir = final_dir.parent / f".{final_dir.name}.lock"
            lock_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "already being promoted"):
                promote_staged_directory(staging_dir, final_dir, durability="required")
            self.assertTrue(lock_dir.is_dir())
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
                promote_staged_directory(
                    staging_dir,
                    final_dir,
                    validate_staging=lambda _path: _replace_parent(),
                    durability="required",
                )

            self.assertFalse(final_dir.exists())
            self.assertTrue((moved_root / staging_dir.name / "qr_document.pdf").is_file())

    def test_publish_staged_directory_cleans_up_on_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_dir = Path(tmpdir) / "backup-deadbeef"
            staging_dir = create_sibling_staging_dir(final_dir)

            def _populate() -> None:
                (staging_dir / "qr_document.pdf").write_bytes(b"qr")
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                publish_staged_directory(
                    staging_dir=staging_dir,
                    final_dir=final_dir,
                    populate=_populate,
                    durability="required",
                )

            self.assertFalse(staging_dir.exists())
            self.assertFalse(final_dir.exists())
