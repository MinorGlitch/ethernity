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
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ethernity.crypto import encrypt_bytes_with_passphrase
from ethernity.encoding.chunking import chunk_payload
from ethernity.encoding.framing import DOC_ID_LEN, FrameType, decode_frame, encode_frame
from ethernity.encoding.qr_payloads import decode_qr_payload, encode_qr_payload
from ethernity.formats.envelope_codec import build_single_file_manifest, encode_envelope
from ethernity.qr.scan import scan_qr_payloads
from tests.test_support import build_cli_env, ensure_playwright_browsers

TEST_SIGNING_SEED = b"\x11" * 32


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
            config_path = repo_root / "src" / "ethernity" / "config" / "config.toml"

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = subprocess.run(
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

    def test_backup_cli_signing_key_shards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            input_path = tmp_path / "input.txt"
            input_path.write_text("backup cli payload", encoding="utf-8")
            output_dir = tmp_path / "backup"
            repo_root = Path(__file__).resolve().parents[2]
            config_path = repo_root / "src" / "ethernity" / "config" / "config.toml"

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            result = subprocess.run(
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
            result = subprocess.run(
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
            config_path = repo_root / "src" / "ethernity" / "config" / "config.toml"

            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            backup = subprocess.run(
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

            mint = subprocess.run(
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


if __name__ == "__main__":
    unittest.main()
