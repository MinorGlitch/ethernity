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

from ethernity.artifacts.publish import (
    create_sibling_staging_dir,
    promote_staged_artifact_dir,
    publish_staged_artifacts,
)


class TestArtifactPublish(unittest.TestCase):
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
            self.assertFalse(staging_dir.exists())

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
                observed.append((lock_dir.is_dir(), final_dir.exists(), staging_dir.exists()))

            promoted = promote_staged_artifact_dir(
                staging_dir,
                final_dir,
                validate_promotion=_validate_promotion,
                lock_dir=lock_dir,
            )

            self.assertEqual(promoted, final_dir)
            self.assertEqual(observed, [(True, False, True)])
            self.assertFalse(lock_dir.exists())
            self.assertFalse(staging_dir.exists())
            self.assertTrue((final_dir / "qr_document.pdf").is_file())

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
                )

            self.assertFalse(staging_dir.exists())
            self.assertFalse(final_dir.exists())
