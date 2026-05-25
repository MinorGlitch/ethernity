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

from ethernity.artifacts.publish import create_sibling_staging_dir, publish_staged_artifacts


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
