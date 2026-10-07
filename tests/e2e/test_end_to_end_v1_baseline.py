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

import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.crypto import decrypt_bytes
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import FrameType, decode_frame
from ethernity.encoding.qr_payloads import (
    QR_PAYLOAD_CODEC_BASE64,
    decode_qr_payload,
    encode_qr_payload,
)
from ethernity.formats.document_codec import decode_backup_document
from ethernity.qr.scan import scan_qr_payloads
from tests.test_support import (
    build_cli_env,
    cli_subprocess_timeout_seconds,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = DEFAULT_CONFIG_PATH
_FIXTURE_SOURCE = _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "source"
_FROZEN_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden"
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
    def test_file_mode_no_sharding_backup_and_restore(self) -> None:
        self._assert_file_mode_round_trip(qr_payload_codec="raw")

    def test_base64_file_mode_backup_and_restore(self) -> None:
        self._assert_file_mode_round_trip(qr_payload_codec="base64")

    def _assert_file_mode_round_trip(self, *, qr_payload_codec: str) -> None:
        with self._workspace() as workspace:
            output_dir = workspace / "backup-file"
            input_file = workspace / "source" / "standalone_secret.txt"
            config_path = self._profile_config_path(workspace, qr_payload_codec)
            self._run_cli(
                [
                    "backup",
                    "--input",
                    str(input_file),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--recovery-count",
                    "0",
                    "--design",
                    "forge",
                ],
                workspace,
                config_path=config_path,
            )
            [output_dir] = output_dir.glob("backup-*")
            self._assert_backup_files(output_dir, expected_shards=0, expected_signing_shards=0)
            self._assert_manifest_matches_frozen(
                output_dir,
                profile=qr_payload_codec,
                scenario_id="file_no_shard",
            )

            restored_path = workspace / "restored-file.bin"
            self._run_cli(
                [
                    "restore",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--output",
                    str(restored_path),
                ],
                workspace,
                config_path=config_path,
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
                    "--recovery-count",
                    "0",
                    "--design",
                    "forge",
                ],
                workspace,
            )
            [output_dir] = output_dir.glob("backup-*")
            self._assert_backup_files(output_dir, expected_shards=0, expected_signing_shards=0)
            self._assert_manifest_matches_frozen(
                output_dir,
                profile="raw",
                scenario_id="directory_no_shard",
            )

            restored_dir = workspace / "restored-directory"
            self._run_cli(
                [
                    "restore",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--output",
                    str(restored_dir),
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
                    "--recovery-count",
                    "0",
                    "--design",
                    "forge",
                ],
                workspace,
            )
            [output_dir] = output_dir.glob("backup-*")
            self._assert_backup_files(output_dir, expected_shards=0, expected_signing_shards=0)
            self._assert_manifest_matches_frozen(
                output_dir,
                profile="raw",
                scenario_id="mixed_no_shard",
            )

            restored_dir = workspace / "restored-mixed"
            self._run_cli(
                [
                    "restore",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--passphrase",
                    _TEST_PASSPHRASE,
                    "--output",
                    str(restored_dir),
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
                    "--recovery-threshold",
                    "2",
                    "--recovery-count",
                    "3",
                    "--signing-key-mode",
                    "embedded",
                    "--design",
                    "forge",
                ],
                workspace,
            )
            [output_dir] = output_dir.glob("backup-*")
            shard_paths, signing_paths = self._assert_backup_files(
                output_dir,
                expected_shards=3,
                expected_signing_shards=0,
            )
            self.assertEqual(len(signing_paths), 0)
            self._assert_manifest_matches_frozen(
                output_dir,
                profile="raw",
                scenario_id="sharded_embedded",
            )

            shard_payloads_file = workspace / "shard_payloads_embedded.txt"
            self._write_scanned_payloads(shard_paths[:2], shard_payloads_file)

            restored_dir = workspace / "restored-sharded-embedded"
            self._run_cli(
                [
                    "restore",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--recovery-payloads-file",
                    str(shard_payloads_file),
                    "--output",
                    str(restored_dir),
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
                    "--recovery-threshold",
                    "2",
                    "--recovery-count",
                    "3",
                    "--signing-key-mode",
                    "sharded",
                    "--signing-key-threshold",
                    "1",
                    "--signing-key-count",
                    "2",
                    "--design",
                    "forge",
                ],
                workspace,
            )
            [output_dir] = output_dir.glob("backup-*")
            shard_paths, signing_paths = self._assert_backup_files(
                output_dir,
                expected_shards=3,
                expected_signing_shards=2,
            )
            self._assert_manifest_matches_frozen(
                output_dir,
                profile="raw",
                scenario_id="sharded_signing_sharded",
            )

            signing_payloads = scan_qr_payloads([str(path) for path in signing_paths])
            self.assertGreaterEqual(len(signing_payloads), 1)
            decoded_signing_frames = 0
            for payload in signing_payloads:
                try:
                    frame = self._decode_scanned_frame(payload)
                except ValueError:
                    continue
                self.assertEqual(frame.frame_type, FrameType.KEY_DOCUMENT)
                decoded_signing_frames += 1
            self.assertGreaterEqual(decoded_signing_frames, 1)

            shard_payloads_file = workspace / "shard_payloads_signing_sharded.txt"
            self._write_scanned_payloads(shard_paths[:2], shard_payloads_file)

            restored_dir = workspace / "restored-sharded-signing-key"
            self._run_cli(
                [
                    "restore",
                    "--scan",
                    str(output_dir / "qr_document.pdf"),
                    "--recovery-payloads-file",
                    str(shard_payloads_file),
                    "--output",
                    str(restored_dir),
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
            def __enter__(self):
                return workspace

            def __exit__(self, exc_type, exc, tb):
                return context.__exit__(exc_type, exc, tb)

        return _WorkspaceContext()

    def _run_cli(
        self,
        cli_args: list[str],
        workspace: Path,
        *,
        config_path: Path = _CONFIG_PATH,
    ) -> subprocess.CompletedProcess[str]:
        env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(workspace / "xdg")})
        command_args = [*cli_args]
        if "--yes" not in command_args:
            command_args.append("--yes")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ethernity",
                "run",
                "--config",
                str(config_path),
                *command_args,
            ],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=cli_subprocess_timeout_seconds(),
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=result.stderr.strip() or result.stdout.strip(),
        )
        return result

    def _assert_manifest_matches_frozen(
        self,
        output_dir: Path,
        *,
        profile: str,
        scenario_id: str,
    ) -> None:
        payloads = scan_qr_payloads([str(output_dir / "qr_document.pdf")])
        frames = []
        for payload in payloads:
            try:
                frame = (
                    decode_frame(decode_qr_payload(payload))
                    if profile == "base64"
                    else decode_frame(payload)
                )
            except ValueError:
                continue
            if frame.frame_type == FrameType.MAIN_DOCUMENT:
                frames.append(frame)
        ciphertext = reassemble_payload(frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
        plaintext = decrypt_bytes(ciphertext, passphrase=_TEST_PASSPHRASE)
        self.assertEqual(plaintext[:3], b"AY\x03")
        manifest, _payload = decode_backup_document(plaintext)
        files = sorted(
            (
                {
                    "path": entry.path,
                    "size": entry.size,
                    "sha256": entry.sha256.hex(),
                }
                for entry in manifest.files
            ),
            key=lambda item: item["path"],
        )
        details = {
            "sealed": manifest.sealed,
            "input_origin": manifest.input_origin,
            "input_roots": list(manifest.input_roots),
            "files": files,
        }
        snapshot_path = _FROZEN_ROOT / profile / scenario_id / "snapshot.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        legacy_projection = dict(snapshot["manifest_projection"])
        self.assertEqual(legacy_projection.pop("version"), 1)
        self.assertEqual(details, legacy_projection)

    @staticmethod
    def _profile_config_path(workspace: Path, qr_payload_codec: str) -> Path:
        config_text = _CONFIG_PATH.read_text(encoding="utf-8").replace(
            '\nqr_payload_codec = "raw" # required: raw | base64',
            f'\nqr_payload_codec = "{qr_payload_codec}" # required: raw | base64',
            1,
        )
        configured_codec = tomllib.loads(config_text)["defaults"]["backup"]["qr_payload_codec"]
        if configured_codec != qr_payload_codec:
            raise AssertionError(f"failed to configure QR payload codec: {qr_payload_codec}")
        path = workspace / f"config-{qr_payload_codec}.toml"
        path.write_text(config_text, encoding="utf-8")
        return path

    def _assert_backup_files(
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
            self.assertTrue(path.exists(), msg=f"missing file: {path}")
            self.assertGreater(path.stat().st_size, 0, msg=f"file is empty: {path}")

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
                normalized.append(encode_qr_payload(payload, codec=QR_PAYLOAD_CODEC_BASE64))
            else:
                normalized.append(payload)
        destination.write_text("\n".join(normalized), encoding="utf-8")

    @staticmethod
    def _decode_scanned_frame(payload: bytes | str):
        if isinstance(payload, bytes):
            try:
                return decode_frame(payload)
            except ValueError:
                pass
        return decode_frame(decode_qr_payload(payload))

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
