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

from ethernity.cli import run_compact, run_extend
from ethernity.cli.features.backup.orchestrator import run_backup_command
from ethernity.cli.features.recover.orchestrator import run_recover_command
from ethernity.cli.shared.types import BackupArgs, CompactArgs, ExtendArgs, RecoverArgs
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from tests.test_support import ensure_playwright_browsers, suppress_output, temp_env

TEST_PASSPHRASE = "extension-integration-passphrase"


class TestIntegrationExtensions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_playwright_browsers()

    def test_extend_recover_latest_and_select_prior_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")
            (source_dir / "nested").mkdir()
            (source_dir / "nested" / "beta.txt").write_text("root-beta", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("first-alpha", encoding="utf-8")
                (source_dir / "gamma.txt").write_text("gamma-one", encoding="utf-8")
                first_extension = self._run_extend(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("second-alpha", encoding="utf-8")
                (source_dir / "gamma.txt").write_text("gamma-two", encoding="utf-8")
                (source_dir / "nested" / "delta.txt").write_text("delta", encoding="utf-8")
                second_extension = self._run_extend(source_dir=source_dir, root_dir=root_dir)

                latest_dir = tmp_path / "recovered-latest"
                self._run_recover(root_dir=root_dir, output_dir=latest_dir)
                self.assertEqual(
                    self._snapshot_tree(latest_dir),
                    {
                        "alpha.txt": b"second-alpha",
                        "gamma.txt": b"gamma-two",
                        "nested/beta.txt": b"root-beta",
                        "nested/delta.txt": b"delta",
                    },
                )

                first_dir = tmp_path / "recovered-first"
                self._run_recover(root_dir=root_dir, output_dir=first_dir, extension_index=1)
                expected_first = {
                    "alpha.txt": b"first-alpha",
                    "gamma.txt": b"gamma-one",
                    "nested/beta.txt": b"root-beta",
                }
                self.assertEqual(self._snapshot_tree(first_dir), expected_first)

                first_hash_dir = tmp_path / "recovered-first-hash"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=first_hash_dir,
                    extension_doc_hash=first_extension.doc_hash.hex(),
                )
                self.assertEqual(self._snapshot_tree(first_hash_dir), expected_first)

                later_extension_dir = root_dir / "extensions" / "02"
                (
                    later_extension_dir
                    / f"recovery_document-02-{second_extension.doc_id.hex()}.pdf"
                ).unlink(missing_ok=True)
                broken_target_dir = tmp_path / "recovered-first-broken-later"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=broken_target_dir,
                    extension_index=1,
                )
                self.assertEqual(self._snapshot_tree(broken_target_dir), expected_first)

                latest_validated_dir = tmp_path / "recovered-latest-validated"
                self._run_recover(root_dir=root_dir, output_dir=latest_validated_dir)
                self.assertEqual(self._snapshot_tree(latest_validated_dir), expected_first)

    def test_compact_preserves_latest_chain_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            compacted_dir = tmp_path / "compacted-root"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")
            (source_dir / "beta.txt").write_text("root-beta", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)
                (source_dir / "alpha.txt").write_text("updated-alpha", encoding="utf-8")
                (source_dir / "gamma.txt").write_text("gamma", encoding="utf-8")
                self._run_extend(source_dir=source_dir, root_dir=root_dir)
                (source_dir / "alpha.txt").write_text("updated-alpha-2", encoding="utf-8")
                (source_dir / "delta.txt").write_text("delta", encoding="utf-8")
                self._run_extend(source_dir=source_dir, root_dir=root_dir)

                with suppress_output():
                    compact_result = run_compact(
                        CompactArgs(
                            config=str(DEFAULT_CONFIG_PATH),
                            root_dir=str(root_dir),
                            output_dir=str(compacted_dir),
                            passphrase=TEST_PASSPHRASE,
                            quiet=True,
                        )
                    )

                self.assertTrue(Path(compact_result.qr_path).exists())
                self.assertTrue(Path(compact_result.recovery_path).exists())

                latest_dir = tmp_path / "latest-state"
                compacted_recovered_dir = tmp_path / "compacted-state"
                self._run_recover(root_dir=root_dir, output_dir=latest_dir)
                self._run_recover(root_dir=compacted_dir, output_dir=compacted_recovered_dir)

                self.assertEqual(
                    self._snapshot_tree(compacted_recovered_dir),
                    self._snapshot_tree(latest_dir),
                )

    def _run_backup(self, *, source_dir: Path, root_dir: Path) -> None:
        with suppress_output():
            exit_code = run_backup_command(
                BackupArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    input_dir=[str(source_dir)],
                    base_dir=str(source_dir),
                    output_dir=str(root_dir),
                    passphrase=TEST_PASSPHRASE,
                    sealed=False,
                    quiet=True,
                )
            )
        self.assertEqual(exit_code, 0)

    def _run_extend(self, *, source_dir: Path, root_dir: Path):
        with suppress_output():
            return run_extend(
                ExtendArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    root_dir=str(root_dir),
                    input_dir=[str(source_dir)],
                    base_dir=str(source_dir),
                    passphrase=TEST_PASSPHRASE,
                    quiet=True,
                )
            )

    def _run_recover(
        self,
        *,
        root_dir: Path,
        output_dir: Path,
        extension_index: int | None = None,
        extension_doc_hash: str | None = None,
    ) -> None:
        with suppress_output():
            exit_code = run_recover_command(
                RecoverArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    scan=[str(root_dir)],
                    passphrase=TEST_PASSPHRASE,
                    extension_index=extension_index,
                    extension_doc_hash=extension_doc_hash,
                    output=str(output_dir),
                    allow_unsigned=False,
                    assume_yes=True,
                    quiet=True,
                )
            )
        self.assertEqual(exit_code, 0)

    @staticmethod
    def _snapshot_tree(root: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
