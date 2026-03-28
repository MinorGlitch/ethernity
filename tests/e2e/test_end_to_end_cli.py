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

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.encoding.chunking import chunk_payload
from ethernity.encoding.framing import DOC_ID_LEN, FrameType, decode_frame, encode_frame
from ethernity.encoding.qr_payloads import decode_qr_payload, encode_qr_payload
from ethernity.formats.envelope_codec import build_single_file_manifest, encode_envelope
from ethernity.qr.scan import scan_qr_payloads
from tests.test_support import (
    build_cli_env,
    cli_subprocess_timeout_seconds,
    ensure_playwright_browsers,
)

TEST_SIGNING_SEED = b"\x11" * 32


def _run_cli_subprocess(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    kwargs.setdefault("timeout", cli_subprocess_timeout_seconds())
    return subprocess.run(*args, **kwargs)


class TestEndToEndCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_playwright_browsers()

    def test_backup_cli_creates_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.txt"
            input_path.write_text("backup cli payload", encoding="utf-8")
            output_dir = tmp_path / "backup"
            repo_root = Path(__file__).resolve().parents[2]
            config_path = DEFAULT_CONFIG_PATH

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "backup",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase-generate",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output_dir / "qr_document.pdf").exists())
            self.assertTrue((output_dir / "recovery_document.pdf").exists())

    def test_api_help_does_not_create_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = Path(__file__).resolve().parents[2]
            xdg_config_home = tmp_path / "xdg"

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(xdg_config_home)})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "api",
                    "--help",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("backup", result.stdout)
            self.assertIn("config", result.stdout)
            self.assertIn("recover", result.stdout)
            self.assertEqual(result.stderr, "")
            self.assertFalse(xdg_config_home.exists())

    def test_api_config_get_does_not_initialize_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = Path(__file__).resolve().parents[2]
            xdg_config_home = tmp_path / "xdg"

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(xdg_config_home)})
            result = _run_cli_subprocess(
                [sys.executable, "-m", "ethernity.cli", "api", "config", "get"],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            events = self._parse_ndjson_events(result.stdout)
            self.assertEqual(events[-1]["command"], "config")
            self.assertEqual(events[-1]["status"], "valid")
            self.assertFalse(xdg_config_home.exists())

    def test_api_parse_errors_emit_ndjson(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = Path(__file__).resolve().parents[2]
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--paper",
                    "bogus",
                    "api",
                    "backup",
                    "--input",
                    str(tmp_path / "missing.txt"),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr, "")
            events = self._parse_ndjson_events(result.stdout)
            self.assertEqual(events[-1]["type"], "error")
            self.assertEqual(events[-1]["code"], "INVALID_INPUT")

    def test_api_config_get_and_set_drive_backup_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = Path(__file__).resolve().parents[2]
            xdg_config_home = tmp_path / "xdg"
            input_path = tmp_path / "input.txt"
            input_path.write_text("config-backed api payload", encoding="utf-8")
            configured_output_dir = tmp_path / "configured-output"
            patch_path = tmp_path / "config_patch.json"
            patch_path.write_text(
                json.dumps(
                    {
                        "values": {
                            "defaults": {
                                "backup": {
                                    "output_dir": str(configured_output_dir),
                                    "shard_threshold": 2,
                                    "shard_count": 3,
                                    "signing_key_mode": "sharded",
                                    "signing_key_shard_threshold": 2,
                                    "signing_key_shard_count": 3,
                                }
                            }
                        },
                        "onboarding": {
                            "mark_complete": True,
                            "configured_fields": ["backup_output_dir", "sharding"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(xdg_config_home)})
            get_result = _run_cli_subprocess(
                [sys.executable, "-m", "ethernity.cli", "api", "config", "get"],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(get_result.returncode, 0, get_result.stderr)
            get_events = self._parse_ndjson_events(get_result.stdout)
            get_result_event = cast(dict[str, Any], get_events[-1])
            self.assertEqual(get_result_event["command"], "config")
            self.assertEqual(get_result_event["operation"], "get")
            self.assertTrue(str(get_result_event["path"]).endswith("config.toml"))
            self.assertEqual(get_result_event["source"], "default")
            self.assertEqual(str(get_result_event["path"]), str(DEFAULT_CONFIG_PATH))
            self.assertTrue(Path(str(get_result_event["path"])).exists())

            set_result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "api",
                    "config",
                    "set",
                    "--input-json",
                    str(patch_path),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(set_result.returncode, 0, set_result.stderr)
            set_events = self._parse_ndjson_events(set_result.stdout)
            set_result_event = cast(dict[str, Any], set_events[-1])
            set_values = cast(dict[str, Any], set_result_event["values"])
            set_defaults = cast(dict[str, Any], set_values["defaults"])
            set_backup_defaults = cast(dict[str, Any], set_defaults["backup"])
            set_onboarding = cast(dict[str, Any], set_result_event["onboarding"])
            self.assertEqual(set_result_event["command"], "config")
            self.assertEqual(set_result_event["operation"], "set")
            self.assertEqual(
                set_backup_defaults["output_dir"],
                str(configured_output_dir),
            )
            self.assertFalse(cast(bool, set_onboarding["needed"]))

            backup_result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "api",
                    "backup",
                    "--input",
                    str(input_path),
                    "--passphrase",
                    "api config passphrase",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(backup_result.returncode, 0, backup_result.stderr)
            backup_events = self._parse_ndjson_events(backup_result.stdout)
            backup_result_event = cast(dict[str, Any], backup_events[-1])
            backup_plan = cast(dict[str, Any], backup_result_event["plan"])
            backup_artifacts = cast(dict[str, Any], backup_result_event["artifacts"])
            self.assertEqual(backup_result_event["command"], "backup")
            self.assertEqual(backup_result_event["output_dir"], str(configured_output_dir))
            self.assertEqual(backup_plan["shard_threshold"], 2)
            self.assertEqual(backup_plan["shard_count"], 3)
            self.assertEqual(backup_plan["signing_key_mode"], "sharded")
            self.assertEqual(len(cast(list[object], backup_artifacts["shard_documents"])), 3)
            self.assertEqual(
                len(cast(list[object], backup_artifacts["signing_key_shard_documents"])),
                3,
            )

    def test_api_backup_cli_emits_ndjson_only_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.txt"
            input_path.write_text("backup cli payload", encoding="utf-8")
            output_dir = tmp_path / "backup"
            repo_root = Path(__file__).resolve().parents[2]
            config_path = DEFAULT_CONFIG_PATH

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "api",
                    "backup",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    "api backup passphrase",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            events = self._parse_ndjson_events(result.stdout)
            self.assertEqual(events[0]["type"], "started")
            self.assertEqual(events[-1]["type"], "result")
            self.assertEqual(events[-1]["command"], "backup")
            self.assertTrue((output_dir / "qr_document.pdf").exists())
            self.assertTrue((output_dir / "recovery_document.pdf").exists())

    def test_api_backup_existing_output_directory_is_treated_as_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.txt"
            input_path.write_text("backup cli payload", encoding="utf-8")
            parent_dir = tmp_path / "gui-backups"
            parent_dir.mkdir()
            repo_root = Path(__file__).resolve().parents[2]
            config_path = DEFAULT_CONFIG_PATH

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "api",
                    "backup",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(parent_dir),
                    "--passphrase",
                    "api backup passphrase",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            events = self._parse_ndjson_events(result.stdout)
            self.assertEqual(events[-1]["command"], "backup")
            actual_output_dir = Path(str(events[-1]["output_dir"]))
            self.assertEqual(actual_output_dir.parent, parent_dir)
            self.assertTrue(actual_output_dir.name.startswith("backup-"))
            self.assertTrue((actual_output_dir / "qr_document.pdf").exists())
            self.assertTrue((actual_output_dir / "recovery_document.pdf").exists())

    def test_api_backup_missing_input_emits_structured_ndjson_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = Path(__file__).resolve().parents[2]
            config_path = DEFAULT_CONFIG_PATH

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "api",
                    "backup",
                    "--input",
                    str(tmp_path / "missing.txt"),
                    "--passphrase",
                    "api backup passphrase",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stderr, "")
            events = self._parse_ndjson_events(result.stdout)
            self.assertEqual(events[0]["type"], "started")
            self.assertEqual(events[-1]["type"], "error")
            self.assertEqual(events[-1]["code"], "NOT_FOUND")
            self.assertEqual(events[-1]["details"]["path"], str(tmp_path / "missing.txt"))
            self.assertEqual([event["type"] for event in events if event["type"] == "artifact"], [])

    def test_api_mint_cli_emits_ndjson_only_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.txt"
            input_path.write_text("mint cli payload", encoding="utf-8")
            output_dir = tmp_path / "backup"
            minted_dir = tmp_path / "minted"
            main_payloads = tmp_path / "main_payloads.txt"
            repo_root = Path(__file__).resolve().parents[2]
            config_path = DEFAULT_CONFIG_PATH

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            backup = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "backup",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    "mint-api-passphrase",
                    "--quiet",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(backup.returncode, 0, backup.stderr)
            self._write_scanned_payloads([output_dir / "qr_document.pdf"], main_payloads)

            mint = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "api",
                    "mint",
                    "--payloads-file",
                    str(main_payloads),
                    "--passphrase",
                    "mint-api-passphrase",
                    "--shard-threshold",
                    "2",
                    "--shard-count",
                    "3",
                    "--output-dir",
                    str(minted_dir),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(mint.returncode, 0, mint.stderr)
            self.assertEqual(mint.stderr, "")
            events = self._parse_ndjson_events(mint.stdout)
            self.assertEqual(events[0]["type"], "started")
            self.assertEqual(events[-1]["type"], "result")
            self.assertEqual(events[-1]["command"], "mint")
            self.assertEqual(events[-1]["output_dir"], str(minted_dir))
            self.assertEqual(len(list(minted_dir.glob("shard-*.pdf"))), 3)

    def test_api_mint_existing_output_directory_is_treated_as_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.txt"
            input_path.write_text("mint cli payload", encoding="utf-8")
            output_dir = tmp_path / "backup"
            minted_parent = tmp_path / "mint-parent"
            minted_parent.mkdir()
            main_payloads = tmp_path / "main_payloads.txt"
            repo_root = Path(__file__).resolve().parents[2]
            config_path = DEFAULT_CONFIG_PATH

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            backup = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "backup",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    "mint-api-passphrase",
                    "--quiet",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(backup.returncode, 0, backup.stderr)
            self._write_scanned_payloads([output_dir / "qr_document.pdf"], main_payloads)

            mint = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "api",
                    "mint",
                    "--payloads-file",
                    str(main_payloads),
                    "--passphrase",
                    "mint-api-passphrase",
                    "--shard-threshold",
                    "2",
                    "--shard-count",
                    "3",
                    "--output-dir",
                    str(minted_parent),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(mint.returncode, 0, mint.stderr)
            events = self._parse_ndjson_events(mint.stdout)
            actual_output_dir = Path(str(events[-1]["output_dir"]))
            self.assertEqual(actual_output_dir.parent, minted_parent)
            self.assertTrue(actual_output_dir.name.startswith("mint-"))
            self.assertEqual(len(list(actual_output_dir.glob("shard-*.pdf"))), 3)

    def test_api_recover_cli_emits_ndjson_only_stdout(self) -> None:
        payload = b"recover cli payload"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = Path(__file__).resolve().parents[2]
            manifest = build_single_file_manifest(
                "payload.bin",
                payload,
                signing_seed=TEST_SIGNING_SEED,
            )
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            self.assertIsNotNone(passphrase)
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            doc_id = doc_hash[:DOC_ID_LEN]
            frames = chunk_payload(
                ciphertext,
                doc_id=doc_id,
                frame_type=FrameType.MAIN_DOCUMENT,
                chunk_size=10,
            )
            frames_path = tmp_path / "frames.txt"
            payload_lines = []
            for frame in frames:
                encoded = encode_qr_payload(encode_frame(frame))
                payload_lines.append(
                    encoded.decode("ascii") if isinstance(encoded, bytes) else encoded
                )
            frames_path.write_text("\n".join(payload_lines), encoding="utf-8")
            output_path = tmp_path / "recovered.bin"

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "api",
                    "recover",
                    "--payloads-file",
                    str(frames_path),
                    "--passphrase",
                    str(passphrase),
                    "--skip-auth-check",
                    "--output",
                    str(output_path),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            events = self._parse_ndjson_events(result.stdout)
            self.assertEqual(events[0]["type"], "started")
            self.assertEqual(events[-1]["type"], "result")
            self.assertEqual(events[-1]["command"], "recover")
            self.assertEqual(events[-1]["output_path_kind"], "file")
            self.assertEqual(output_path.read_bytes(), payload)

    def test_api_recover_cli_writes_single_file_under_existing_output_directory(self) -> None:
        payload = b"recover to existing directory"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = Path(__file__).resolve().parents[2]
            manifest = build_single_file_manifest(
                "payload.bin",
                payload,
                signing_seed=TEST_SIGNING_SEED,
            )
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            self.assertIsNotNone(passphrase)
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            doc_id = doc_hash[:DOC_ID_LEN]
            frames = chunk_payload(
                ciphertext,
                doc_id=doc_id,
                frame_type=FrameType.MAIN_DOCUMENT,
                chunk_size=10,
            )
            frames_path = tmp_path / "frames.txt"
            payload_lines = []
            for frame in frames:
                encoded = encode_qr_payload(encode_frame(frame))
                payload_lines.append(
                    encoded.decode("ascii") if isinstance(encoded, bytes) else encoded
                )
            frames_path.write_text("\n".join(payload_lines), encoding="utf-8")
            output_dir = tmp_path / "gui-backups"
            output_dir.mkdir()

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "api",
                    "recover",
                    "--payloads-file",
                    str(frames_path),
                    "--passphrase",
                    str(passphrase),
                    "--skip-auth-check",
                    "--output",
                    str(output_dir),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            events = self._parse_ndjson_events(result.stdout)
            self.assertEqual(events[-1]["type"], "result")
            self.assertEqual(events[-1]["output_path_kind"], "directory")
            self.assertEqual(events[-1]["output_path"], str(output_dir))
            self.assertEqual((output_dir / "payload.bin").read_bytes(), payload)

    def test_api_recover_cli_supports_scanned_shard_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.txt"
            input_path.write_text("recover via shard scan", encoding="utf-8")
            output_dir = tmp_path / "backup"
            recovered_path = tmp_path / "recovered.bin"
            repo_root = Path(__file__).resolve().parents[2]
            config_path = DEFAULT_CONFIG_PATH

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            backup = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "backup",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    "scan-shards-passphrase",
                    "--shard-threshold",
                    "2",
                    "--shard-count",
                    "3",
                    "--quiet",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(backup.returncode, 0, backup.stderr)

            qr_document = output_dir / "qr_document.pdf"
            shard_paths = sorted(output_dir.glob("shard-*.pdf"))
            self.assertGreaterEqual(len(shard_paths), 2)

            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "api",
                    "recover",
                    "--scan",
                    str(qr_document),
                    "--shard-scan",
                    str(shard_paths[0]),
                    "--shard-scan",
                    str(shard_paths[1]),
                    "--output",
                    str(recovered_path),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            events = self._parse_ndjson_events(result.stdout)
            self.assertEqual(events[-1]["command"], "recover")
            self.assertEqual(events[-1]["output_path_kind"], "file")
            self.assertEqual(recovered_path.read_text(encoding="utf-8"), "recover via shard scan")

    def test_backup_cli_signing_key_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.txt"
            input_path.write_text("backup cli payload", encoding="utf-8")
            output_dir = tmp_path / "backup"
            repo_root = Path(__file__).resolve().parents[2]
            config_path = DEFAULT_CONFIG_PATH

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "backup",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase-generate",
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
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            signing_key_shards = list(output_dir.glob("signing-key-shard-*.pdf"))
            self.assertEqual(len(signing_key_shards), 2)

    def test_recover_cli_from_frames(self) -> None:
        payload = b"recover cli payload"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            repo_root = Path(__file__).resolve().parents[2]
            manifest = build_single_file_manifest(
                "payload.bin",
                payload,
                signing_seed=TEST_SIGNING_SEED,
            )
            envelope = encode_envelope(payload, manifest)
            ciphertext, passphrase = encrypt_bytes_with_passphrase(envelope, passphrase=None)
            self.assertIsNotNone(passphrase)
            doc_hash = hashlib.blake2b(ciphertext, digest_size=32).digest()
            doc_id = doc_hash[:DOC_ID_LEN]
            frames = chunk_payload(
                ciphertext,
                doc_id=doc_id,
                frame_type=FrameType.MAIN_DOCUMENT,
                chunk_size=10,
            )
            frames_path = tmp_path / "frames.txt"
            payload_lines = []
            for frame in frames:
                encoded = encode_qr_payload(encode_frame(frame))
                payload_lines.append(
                    encoded.decode("ascii") if isinstance(encoded, bytes) else encoded
                )
            frames_path.write_text(
                "\n".join(payload_lines),
                encoding="utf-8",
            )
            output_path = tmp_path / "recovered.bin"

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "recover",
                    "--payloads-file",
                    str(frames_path),
                    "--passphrase",
                    str(passphrase),
                    "--skip-auth-check",
                    "--output",
                    str(output_path),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output_path.read_bytes(), payload)

    def test_mint_cli_rejects_sealed_backup_without_signing_key_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.txt"
            input_path.write_text("sealed mint payload", encoding="utf-8")
            output_dir = tmp_path / "backup"
            repo_root = Path(__file__).resolve().parents[2]
            config_path = DEFAULT_CONFIG_PATH

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            backup = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "backup",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--passphrase",
                    "sealed-mint-passphrase",
                    "--sealed",
                    "--shard-threshold",
                    "2",
                    "--shard-count",
                    "3",
                    "--design",
                    "forge",
                    "--quiet",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(backup.returncode, 0, backup.stderr)

            main_payloads = tmp_path / "main_payloads.txt"
            shard_payloads = tmp_path / "shard_payloads.txt"
            self._write_scanned_payloads([output_dir / "qr_document.pdf"], main_payloads)
            self._write_scanned_payloads(sorted(output_dir.glob("shard-*.pdf"))[:2], shard_payloads)

            mint = _run_cli_subprocess(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(config_path),
                    "mint",
                    "--payloads-file",
                    str(main_payloads),
                    "--shard-payloads-file",
                    str(shard_payloads),
                    "--shard-threshold",
                    "2",
                    "--shard-count",
                    "3",
                    "--signing-key-shard-threshold",
                    "1",
                    "--signing-key-shard-count",
                    "2",
                    "--output-dir",
                    str(tmp_path / "minted"),
                    "--quiet",
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(mint.returncode, 2)
            self.assertIn("backup is sealed", mint.stderr)

    @staticmethod
    def _write_scanned_payloads(pdf_paths: list[Path], destination: Path) -> None:
        payloads = scan_qr_payloads([str(path) for path in pdf_paths])
        normalized: list[str] = []
        for payload in payloads:
            try:
                if isinstance(payload, bytes):
                    frame = decode_frame(payload)
                else:
                    frame = decode_frame(decode_qr_payload(payload))
            except ValueError:
                continue
            encoded = encode_qr_payload(encode_frame(frame), codec="base64")
            normalized.append(encoded.decode("ascii") if isinstance(encoded, bytes) else encoded)
        destination.write_text("\n".join(normalized), encoding="utf-8")

    @staticmethod
    def _parse_ndjson_events(stdout: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                raise AssertionError(f"expected object event, got: {parsed!r}")
            events.append(parsed)
        if not events:
            raise AssertionError("expected NDJSON events on stdout")
        return events


if __name__ == "__main__":
    unittest.main()
