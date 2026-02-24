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

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ethernity.encoding.framing import FrameType, decode_frame
from ethernity.encoding.qr_payloads import decode_qr_payload
from ethernity.qr.scan import scan_qr_payloads
from tests.test_support import build_cli_env, ensure_playwright_browsers

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "src" / "ethernity" / "config" / "config.toml"
_FIXTURE_SOURCE = _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "source"
_TEST_PASSPHRASE = "stable-v1-baseline-passphrase"

_DIRECTORY_EXPECTED = [
    "alpha.txt",
    "nested/beta.json",
    "nested/raw.bin",
]
_MIXED_EXPECTED = [
    "mixed_input.txt",
    "directory_payload/alpha.txt",
    "directory_payload/nested/beta.json",
    "directory_payload/nested/raw.bin",
]


class TestStableV1Baseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_playwright_browsers()

    def test_file_mode_no_sharding_backup_and_restore(self) -> None:
        with self._workspace() as workspace:
            output_dir = workspace / "backup-file"
            input_file = workspace / "source" / "standalone_secret.txt"
            self._run_cli(
                [
                    "backup",
                    "--input",
                    str(input_file),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--design",
                    "forge",
                    "--quiet",
                ],
                workspace,
            )
            self._assert_backup_artifacts(output_dir, expected_shards=0, expected_signing_shards=0)

            restored_path = workspace / "restored-file.bin"
            self._run_cli(
                [
                    "recover",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--output",
                    str(restored_path),
                    "--quiet",
                ],
                workspace,
            )

            self.assertEqual(restored_path.read_bytes(), input_file.read_bytes())

    def test_directory_mode_no_sharding_backup_and_restore(self) -> None:
        with self._workspace() as workspace:
            output_dir = workspace / "backup-directory"
            input_dir = workspace / "source" / "directory_payload"
            self._run_cli(
                [
                    "backup",
                    "--input-dir",
                    str(input_dir),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--design",
                    "forge",
                    "--quiet",
                ],
                workspace,
            )
            self._assert_backup_artifacts(output_dir, expected_shards=0, expected_signing_shards=0)

            restored_dir = workspace / "restored-directory"
            self._run_cli(
                [
                    "recover",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--output",
                    str(restored_dir),
                    "--quiet",
                ],
                workspace,
            )

            self._assert_restored_matches(
                source_root=input_dir,
                restored_root=restored_dir,
                relative_paths=_DIRECTORY_EXPECTED,
            )

    def test_mixed_mode_no_sharding_backup_and_restore(self) -> None:
        with self._workspace() as workspace:
            output_dir = workspace / "backup-mixed"
            source_root = workspace / "source"
            self._run_cli(
                [
                    "backup",
                    "--input",
                    str(source_root / "mixed_input.txt"),
                    "--input-dir",
                    str(source_root / "directory_payload"),
                    "--base-dir",
                    str(source_root),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--design",
                    "forge",
                    "--quiet",
                ],
                workspace,
            )
            self._assert_backup_artifacts(output_dir, expected_shards=0, expected_signing_shards=0)

            restored_dir = workspace / "restored-mixed"
            self._run_cli(
                [
                    "recover",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--output",
                    str(restored_dir),
                    "--quiet",
                ],
                workspace,
            )

            self._assert_restored_matches(
                source_root=source_root,
                restored_root=restored_dir,
                relative_paths=_MIXED_EXPECTED,
            )

    def test_sharded_embedded_signing_key_backup_and_restore(self) -> None:
        with self._workspace() as workspace:
            output_dir = workspace / "backup-sharded-embedded"
            input_dir = workspace / "source" / "directory_payload"
            self._run_cli(
                [
                    "backup",
                    "--input-dir",
                    str(input_dir),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--shard-threshold",
                    "2",
                    "--shard-count",
                    "3",
                    "--signing-key-mode",
                    "embedded",
                    "--design",
                    "forge",
                    "--quiet",
                ],
                workspace,
            )
            shard_paths, signing_paths = self._assert_backup_artifacts(
                output_dir,
                expected_shards=3,
                expected_signing_shards=0,
            )
            self.assertEqual(len(signing_paths), 0)

            shard_payloads_file = workspace / "shard_payloads_embedded.txt"
            self._write_scanned_payloads(shard_paths[:2], shard_payloads_file)

            restored_dir = workspace / "restored-sharded-embedded"
            self._run_cli(
                [
                    "recover",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--shard-payloads-file",
                    str(shard_payloads_file),
                    "--output",
                    str(restored_dir),
                    "--quiet",
                ],
                workspace,
            )

            self._assert_restored_matches(
                source_root=input_dir,
                restored_root=restored_dir,
                relative_paths=_DIRECTORY_EXPECTED,
            )

    def test_sharded_signing_key_backup_and_restore(self) -> None:
        with self._workspace() as workspace:
            output_dir = workspace / "backup-sharded-signing-key"
            source_root = workspace / "source"
            self._run_cli(
                [
                    "backup",
                    "--input",
                    str(source_root / "mixed_input.txt"),
                    "--input-dir",
                    str(source_root / "directory_payload"),
                    "--base-dir",
                    str(source_root),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--shard-threshold",
                    "2",
                    "--shard-count",
                    "3",
                    "--signing-key-mode",
                    "sharded",
                    "--signing-key-shard-threshold",
                    "1",
                    "--signing-key-shard-count",
                    "2",
                    "--design",
                    "forge",
                    "--quiet",
                ],
                workspace,
            )
            shard_paths, signing_paths = self._assert_backup_artifacts(
                output_dir,
                expected_shards=3,
                expected_signing_shards=2,
            )

            signing_payloads = scan_qr_payloads([str(path) for path in signing_paths])
            self.assertGreaterEqual(len(signing_payloads), 1)
            for payload in signing_payloads:
                frame = decode_frame(decode_qr_payload(payload))
                self.assertEqual(frame.frame_type, FrameType.KEY_DOCUMENT)

            shard_payloads_file = workspace / "shard_payloads_signing_sharded.txt"
            self._write_scanned_payloads(shard_paths[:2], shard_payloads_file)

            restored_dir = workspace / "restored-sharded-signing-key"
            self._run_cli(
                [
                    "recover",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--shard-payloads-file",
                    str(shard_payloads_file),
                    "--output",
                    str(restored_dir),
                    "--quiet",
                ],
                workspace,
            )

            self._assert_restored_matches(
                source_root=source_root,
                restored_root=restored_dir,
                relative_paths=_MIXED_EXPECTED,
            )

    def _workspace(self):
        context = tempfile.TemporaryDirectory()
        tmpdir = context.__enter__()
        workspace = Path(tmpdir)
        shutil.copytree(_FIXTURE_SOURCE, workspace / "source")

        class _WorkspaceContext:
            def __enter__(self_inner):
                return workspace

            def __exit__(self_inner, exc_type, exc, tb):
                return context.__exit__(exc_type, exc, tb)

        return _WorkspaceContext()

    def _run_cli(self, cli_args: list[str], workspace: Path) -> subprocess.CompletedProcess[str]:
        env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(workspace / "xdg")})
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ethernity.cli",
                "--config",
                str(_CONFIG_PATH),
                *cli_args,
            ],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=result.stderr.strip() or result.stdout.strip(),
        )
        return result

    def _assert_backup_artifacts(
        self,
        output_dir: Path,
        *,
        expected_shards: int,
        expected_signing_shards: int,
    ) -> tuple[list[Path], list[Path]]:
        required = [
            output_dir / "qr_document.pdf",
            output_dir / "recovery_document.pdf",
            output_dir / "recovery_kit_index.pdf",
        ]
        for path in required:
            self.assertTrue(path.exists(), msg=f"missing artifact: {path}")
            self.assertGreater(path.stat().st_size, 0, msg=f"artifact is empty: {path}")

        shard_paths = sorted(output_dir.glob("shard-*.pdf"))
        signing_paths = sorted(output_dir.glob("signing-key-shard-*.pdf"))
        self.assertEqual(len(shard_paths), expected_shards)
        self.assertEqual(len(signing_paths), expected_signing_shards)
        return shard_paths, signing_paths

    def _write_scanned_payloads(self, pdf_paths: list[Path], destination: Path) -> None:
        self.assertGreaterEqual(len(pdf_paths), 1)
        payloads = scan_qr_payloads([str(path) for path in pdf_paths])
        self.assertGreaterEqual(len(payloads), 1)
        normalized: list[str] = []
        for payload in payloads:
            if isinstance(payload, bytes):
                normalized.append(payload.decode("ascii"))
            else:
                normalized.append(payload)
        destination.write_text("\n".join(normalized), encoding="utf-8")

    def _assert_restored_matches(
        self,
        *,
        source_root: Path,
        restored_root: Path,
        relative_paths: list[str],
    ) -> None:
        self.assertTrue(restored_root.exists(), msg=f"missing restored output: {restored_root}")
        for relative in relative_paths:
            source_path = source_root / relative
            restored_path = restored_root / relative
            self.assertTrue(source_path.exists(), msg=f"missing source fixture: {source_path}")
            self.assertTrue(restored_path.exists(), msg=f"missing restored file: {restored_path}")
            self.assertEqual(
                restored_path.read_bytes(),
                source_path.read_bytes(),
                msg=f"byte mismatch for {relative}",
            )


if __name__ == "__main__":
    unittest.main()
