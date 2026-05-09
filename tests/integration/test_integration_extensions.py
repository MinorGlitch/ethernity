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
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.ndjson import ApiCommandError
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

                expected_latest_state = {
                    "alpha.txt": b"second-alpha",
                    "gamma.txt": b"gamma-two",
                    "nested/beta.txt": b"root-beta",
                    "nested/delta.txt": b"delta",
                }
                latest_dir = tmp_path / "recovered-latest"
                self._run_recover(root_dir=root_dir, output_dir=latest_dir)
                self.assertEqual(self._snapshot_tree(latest_dir), expected_latest_state)

                expected_first = {
                    "alpha.txt": b"first-alpha",
                    "gamma.txt": b"gamma-one",
                    "nested/beta.txt": b"root-beta",
                }

                later_extension_dir = root_dir / "extensions" / "02"
                (
                    later_extension_dir
                    / f"recovery_document-02-{second_extension.doc_id.hex()}.pdf"
                ).unlink(missing_ok=True)

                degraded_latest_dir = tmp_path / "recovered-latest-degraded"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=degraded_latest_dir,
                )
                self.assertEqual(self._snapshot_tree(degraded_latest_dir), expected_latest_state)

                (source_dir / "alpha.txt").write_text("blocked-third-alpha", encoding="utf-8")
                blocked_extension_dir = root_dir / "extensions" / "03"
                with self.assertRaises(ApiCommandError) as ctx:
                    self._run_extend(source_dir=source_dir, root_dir=root_dir)
                self.assertEqual(ctx.exception.code, "EXTENSION_LAYOUT_INVALID")
                self.assertFalse(blocked_extension_dir.exists())

                first_dir = tmp_path / "recovered-first"
                self._run_recover(root_dir=root_dir, output_dir=first_dir, extension_index=1)
                self.assertEqual(self._snapshot_tree(first_dir), expected_first)

                first_hash_dir = tmp_path / "recovered-first-hash"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=first_hash_dir,
                    extension_doc_hash=first_extension.doc_hash.hex(),
                )
                self.assertEqual(self._snapshot_tree(first_hash_dir), expected_first)

    def test_recover_with_extension_local_shards_unlocks_root_plus_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            recovered_dir = tmp_path / "recovered-from-extension-shards"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                (source_dir / "beta.txt").write_text("extension-beta", encoding="utf-8")
                extension = self._run_extend(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                )

                self.assertEqual(len(extension.shard_paths), 3)
                with suppress_output():
                    exit_code = run_recover_command(
                        RecoverArgs(
                            config=str(DEFAULT_CONFIG_PATH),
                            scan=[str(root_dir)],
                            shard_scan=[str(path) for path in extension.shard_paths[:2]],
                            output=str(recovered_dir),
                            allow_unsigned=False,
                            assume_yes=True,
                            quiet=True,
                        )
                    )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                self._snapshot_tree(recovered_dir),
                {
                    "alpha.txt": b"extension-alpha",
                    "beta.txt": b"extension-beta",
                },
            )

    def test_compact_preserves_latest_state_and_refuses_degraded_latest_head(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            healthy_compacted_dir = tmp_path / "healthy-compacted-root"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")
            (source_dir / "nested").mkdir()
            (source_dir / "nested" / "beta.txt").write_text("root-beta", encoding="utf-8")

            expected_latest_state = {
                "alpha.txt": b"second-alpha",
                "gamma.txt": b"gamma-two",
                "nested/beta.txt": b"root-beta",
                "nested/delta.txt": b"delta",
            }

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("first-alpha", encoding="utf-8")
                (source_dir / "gamma.txt").write_text("gamma-one", encoding="utf-8")
                self._run_extend(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("second-alpha", encoding="utf-8")
                (source_dir / "gamma.txt").write_text("gamma-two", encoding="utf-8")
                (source_dir / "nested" / "delta.txt").write_text("delta", encoding="utf-8")
                latest_extension = self._run_extend(source_dir=source_dir, root_dir=root_dir)

                healthy_latest_dir = tmp_path / "healthy-latest"
                self._run_recover(root_dir=root_dir, output_dir=healthy_latest_dir)
                self.assertEqual(self._snapshot_tree(healthy_latest_dir), expected_latest_state)

                healthy_compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=healthy_compacted_dir,
                )

                self.assertTrue(Path(healthy_compact_result.qr_path).exists())
                self.assertTrue(Path(healthy_compact_result.recovery_path).exists())

                healthy_compacted_recovered_dir = tmp_path / "healthy-compacted-state"
                self._run_recover(
                    root_dir=healthy_compacted_dir,
                    output_dir=healthy_compacted_recovered_dir,
                )
                self.assertEqual(
                    self._snapshot_tree(healthy_compacted_recovered_dir),
                    expected_latest_state,
                )

                degraded_carrier = (
                    root_dir
                    / "extensions"
                    / "02"
                    / f"recovery_document-02-{latest_extension.doc_id.hex()}.pdf"
                )
                self.assertTrue(degraded_carrier.exists())
                degraded_carrier.unlink()

                degraded_latest_dir = tmp_path / "degraded-latest"
                self._run_recover(
                    root_dir=root_dir,
                    output_dir=degraded_latest_dir,
                )
                self.assertEqual(self._snapshot_tree(degraded_latest_dir), expected_latest_state)

                degraded_compacted_dir = tmp_path / "degraded-compacted-root"
                degraded_compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=degraded_compacted_dir,
                )
                self.assertTrue(Path(degraded_compact_result.qr_path).exists())
                self.assertTrue(Path(degraded_compact_result.recovery_path).exists())

    def test_corrupt_present_extension_carrier_fails_closed_across_flows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir)

                (source_dir / "alpha.txt").write_text("extension-alpha", encoding="utf-8")
                extension = self._run_extend(source_dir=source_dir, root_dir=root_dir)

                corrupt_carrier = (
                    root_dir / "extensions" / "01" / f"qr_document-01-{extension.doc_id.hex()}.pdf"
                )
                self.assertTrue(corrupt_carrier.exists())
                corrupt_carrier.write_bytes(b"%PDF-1.7\ncorrupt extension carrier\n")

                with self.assertRaisesRegex(ValueError, "failed to read PDF"):
                    self._run_recover(
                        root_dir=root_dir,
                        output_dir=tmp_path / "corrupt-recovered",
                    )

                with self.assertRaisesRegex(ValueError, "failed to read PDF"):
                    self._run_compact(
                        root_dir=root_dir,
                        output_dir=tmp_path / "corrupt-compacted",
                    )

                (source_dir / "alpha.txt").write_text("blocked-alpha", encoding="utf-8")
                blocked_extension_dir = root_dir / "extensions" / "02"
                with self.assertRaises(ApiCommandError) as ctx:
                    self._run_extend(source_dir=source_dir, root_dir=root_dir)
                self.assertEqual(ctx.exception.code, "EXTENSION_LAYOUT_INVALID")
                self.assertFalse(blocked_extension_dir.exists())

    def test_compact_sealed_root_without_auth_inputs_round_trips_through_recover(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "sealed-source"
            root_dir = tmp_path / "sealed-backup-root"
            compacted_dir = tmp_path / "sealed-compacted-root"
            recovered_dir = tmp_path / "sealed-compacted-recovered"
            source_dir.mkdir()
            (source_dir / "alpha.txt").write_text("sealed-alpha", encoding="utf-8")
            (source_dir / "nested").mkdir()
            (source_dir / "nested" / "beta.txt").write_text("sealed-beta", encoding="utf-8")

            expected_tree = {
                "alpha.txt": b"sealed-alpha",
                "nested/beta.txt": b"sealed-beta",
            }

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(source_dir=source_dir, root_dir=root_dir, sealed=True)

                compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=compacted_dir,
                )

                self.assertTrue(Path(compact_result.qr_path).exists())
                self.assertTrue(Path(compact_result.recovery_path).exists())

                self._run_recover(root_dir=compacted_dir, output_dir=recovered_dir)
                self.assertEqual(self._snapshot_tree(recovered_dir), expected_tree)

    def test_compact_preserves_external_root_passphrase_shard_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "source"
            root_dir = tmp_path / "backup-root"
            external_shard_dir = tmp_path / "separate-shards"
            compacted_dir = tmp_path / "compacted-root"
            recovered_dir = tmp_path / "compacted-recovered"
            source_dir.mkdir()
            external_shard_dir.mkdir()
            (source_dir / "alpha.txt").write_text("root-alpha", encoding="utf-8")

            with temp_env({"XDG_CONFIG_HOME": str(tmp_path / "xdg")}):
                self._run_backup(
                    source_dir=source_dir,
                    root_dir=root_dir,
                    shard_threshold=2,
                    shard_count=3,
                )
                root_shards = sorted(root_dir.glob("shard-*.pdf"))
                self.assertEqual(len(root_shards), 3)
                external_shards: list[Path] = []
                for shard_path in root_shards:
                    moved_path = external_shard_dir / shard_path.name
                    shard_path.rename(moved_path)
                    external_shards.append(moved_path)
                self.assertEqual(sorted(root_dir.glob("shard-*.pdf")), [])

                compact_result = self._run_compact(
                    root_dir=root_dir,
                    output_dir=compacted_dir,
                    passphrase=None,
                    shard_scan=[str(path) for path in external_shards[:2]],
                )

                self.assertEqual(len(compact_result.shard_paths), 3)
                for shard_path in compact_result.shard_paths:
                    self.assertTrue(Path(shard_path).exists())
                self._run_recover(
                    root_dir=compacted_dir,
                    output_dir=recovered_dir,
                    passphrase=None,
                    shard_scan=list(compact_result.shard_paths[:2]),
                )
                self.assertEqual(
                    self._snapshot_tree(recovered_dir),
                    {"alpha.txt": b"root-alpha"},
                )

    def _run_backup(
        self,
        *,
        source_dir: Path,
        root_dir: Path,
        sealed: bool = False,
        shard_threshold: int | None = None,
        shard_count: int | None = None,
    ) -> None:
        with suppress_output():
            exit_code = run_backup_command(
                BackupArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    input_dir=[str(source_dir)],
                    base_dir=str(source_dir),
                    output_dir=str(root_dir),
                    passphrase=TEST_PASSPHRASE,
                    sealed=sealed,
                    shard_threshold=shard_threshold,
                    shard_count=shard_count,
                    quiet=True,
                )
            )
        self.assertEqual(exit_code, 0)

    def _run_compact(
        self,
        *,
        root_dir: Path,
        output_dir: Path,
        passphrase: str | None = TEST_PASSPHRASE,
        shard_scan: list[str] | None = None,
    ):
        with suppress_output():
            return run_compact(
                CompactArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    root_dir=str(root_dir),
                    output_dir=str(output_dir),
                    passphrase=passphrase,
                    shard_scan=shard_scan,
                    quiet=True,
                )
            )

    def _run_extend(
        self,
        *,
        source_dir: Path,
        root_dir: Path,
        shard_threshold: int | None = None,
        shard_count: int | None = None,
    ):
        with suppress_output():
            return run_extend(
                ExtendArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    root_dir=str(root_dir),
                    input_dir=[str(source_dir)],
                    base_dir=str(source_dir),
                    passphrase=TEST_PASSPHRASE,
                    shard_threshold=shard_threshold,
                    shard_count=shard_count,
                    quiet=True,
                )
            )

    def _assert_extend_head_untrusted(
        self,
        *,
        source_dir: Path,
        root_dir: Path,
        expected_latest_head_index: int,
        expected_validated_head_index: int,
        blocked_extension_dir: Path,
        expected_failure_fragment: str = "missing required payload MAIN carriers",
    ) -> ApiCommandError:
        with self.assertRaises(ApiCommandError) as ctx:
            self._run_extend(source_dir=source_dir, root_dir=root_dir)

        exc = ctx.exception
        self.assertEqual(exc.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(exc.details["stage"], "replay")
        self.assertEqual(exc.details["failure_stage"], "discovery")
        self.assertEqual(exc.details["failure_head_index"], expected_latest_head_index)
        self.assertEqual(exc.details["failure_head_dir_name"], f"{expected_latest_head_index:02d}")
        self.assertEqual(exc.details["latest_head_index"], expected_latest_head_index)
        self.assertEqual(exc.details["latest_head_dir_name"], f"{expected_latest_head_index:02d}")
        self.assertIsNone(exc.details["requested_head_index"])
        self.assertIsNone(exc.details["requested_head_doc_hash"])
        self.assertEqual(exc.details["validated_head_index"], expected_validated_head_index)
        self.assertIsInstance(exc.details["validated_head_doc_hash"], str)
        self.assertEqual(len(exc.details["validated_head_doc_hash"]), 64)
        self.assertFalse(exc.details["explicit_selection"])
        self.assertIn("latest supplied recovery head could not be trusted", str(exc))
        self.assertIn(expected_failure_fragment, str(exc))
        self.assertFalse(blocked_extension_dir.exists())
        self.assertEqual(list((root_dir / "extensions").glob(".staging-*")), [])
        return exc

    def _run_recover(
        self,
        *,
        root_dir: Path,
        output_dir: Path,
        extension_index: int | None = None,
        extension_doc_hash: str | None = None,
        passphrase: str | None = TEST_PASSPHRASE,
        shard_scan: list[str] | None = None,
    ) -> None:
        with suppress_output():
            exit_code = run_recover_command(
                RecoverArgs(
                    config=str(DEFAULT_CONFIG_PATH),
                    scan=[str(root_dir)],
                    passphrase=passphrase,
                    shard_scan=shard_scan,
                    extension_index=extension_index,
                    extension_doc_hash=extension_doc_hash,
                    output=str(output_dir),
                    allow_unsigned=False,
                    assume_yes=True,
                    quiet=True,
                )
            )
        self.assertEqual(exit_code, 0)

    def _assert_recover_head_untrusted(
        self,
        *,
        root_dir: Path,
        output_dir: Path,
        expected_latest_head_index: int,
        expected_failure_fragment: str = "missing required payload MAIN carriers",
    ) -> ApiCommandError:
        with self.assertRaises(ApiCommandError) as ctx:
            self._run_recover(root_dir=root_dir, output_dir=output_dir)

        exc = ctx.exception
        self._assert_head_untrusted_error(
            exc,
            output_dir=output_dir,
            expected_latest_head_index=expected_latest_head_index,
            expected_message_fragment="latest supplied recovery head could not be trusted",
            expected_failure_fragment=expected_failure_fragment,
            checkpoint_created=None,
        )
        return exc

    def _assert_compact_head_untrusted(
        self,
        *,
        root_dir: Path,
        output_dir: Path,
        expected_latest_head_index: int,
        expected_failure_fragment: str = "missing required payload MAIN carriers",
    ) -> ApiCommandError:
        with self.assertRaises(ApiCommandError) as ctx:
            self._run_compact(root_dir=root_dir, output_dir=output_dir)

        exc = ctx.exception
        self._assert_head_untrusted_error(
            exc,
            output_dir=output_dir,
            expected_latest_head_index=expected_latest_head_index,
            expected_message_fragment=(
                "latest supplied compact head could not be trusted; no checkpoint was created"
            ),
            expected_failure_fragment=expected_failure_fragment,
            checkpoint_created=False,
        )
        return exc

    def _assert_head_untrusted_error(
        self,
        exc: ApiCommandError,
        *,
        output_dir: Path,
        expected_latest_head_index: int,
        expected_message_fragment: str,
        expected_failure_fragment: str,
        checkpoint_created: bool | None,
    ) -> None:
        self.assertEqual(exc.code, api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(exc.details["stage"], "replay")
        self.assertEqual(exc.details["failure_stage"], "discovery")
        self.assertEqual(exc.details["failure_head_index"], expected_latest_head_index)
        self.assertEqual(exc.details["failure_head_dir_name"], f"{expected_latest_head_index:02d}")
        self.assertEqual(exc.details["latest_head_index"], expected_latest_head_index)
        self.assertEqual(exc.details["latest_head_dir_name"], f"{expected_latest_head_index:02d}")
        self.assertIsNone(exc.details["requested_head_index"])
        self.assertIsNone(exc.details["requested_head_doc_hash"])
        self.assertEqual(exc.details["validated_head_index"], 0)
        self.assertFalse(exc.details["explicit_selection"])
        self.assertIn(expected_message_fragment, str(exc))
        self.assertIn(expected_failure_fragment, str(exc))
        if checkpoint_created is None:
            self.assertNotIn("checkpoint_created", exc.details)
        else:
            self.assertEqual(exc.details["checkpoint_created"], checkpoint_created)
        self.assertFalse(output_dir.exists())

    @staticmethod
    def _snapshot_tree(root: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
