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

import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ethernity.crypto import decrypt_bytes
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import FrameType, decode_frame
from ethernity.encoding.qr_payloads import (
    QR_PAYLOAD_CODEC_BASE64,
    decode_qr_payload,
    encode_qr_payload,
)
from ethernity.formats.envelope_codec import decode_envelope
from ethernity.qr.scan import scan_qr_payloads
from tests.test_support import build_cli_env, ensure_playwright_browsers

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "src" / "ethernity" / "config" / "config.toml"
_SOURCE_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "source"
_GOLDEN_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden"
_BINARY_PAYLOADS_MAGIC = b"EQPB"
_BINARY_PAYLOADS_VERSION = 1


class FrozenProfileTestCase(unittest.TestCase):
    __test__ = False
    PROFILE_NAME = ""
    QR_PAYLOAD_CODEC = ""

    @classmethod
    def setUpClass(cls) -> None:
        if not cls.PROFILE_NAME or cls.QR_PAYLOAD_CODEC not in {"raw", "base64"}:
            raise AssertionError("PROFILE_NAME and QR_PAYLOAD_CODEC must be configured")
        ensure_playwright_browsers()
        index_path = _GOLDEN_ROOT / cls.PROFILE_NAME / "index.json"
        cls._index = json.loads(index_path.read_text(encoding="utf-8"))
        cls._passphrase = str(cls._index["passphrase"])

    def test_frozen_artifact_hashes_match_snapshots(self) -> None:
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                snapshot = self._snapshot(scenario)
                scenario_root = self._profile_root() / str(scenario["id"])
                for rel_path, expected_hash in snapshot["artifact_hashes"].items():
                    if rel_path.endswith((".txt", ".bin")):
                        artifact_path = scenario_root / rel_path
                    else:
                        artifact_path = scenario_root / "backup" / rel_path
                    self.assertTrue(
                        artifact_path.exists(),
                        msg=f"missing artifact: {artifact_path}",
                    )
                    self.assertEqual(self._sha256_file(artifact_path), expected_hash)

    def test_recover_from_frozen_backups(self) -> None:
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                snapshot = self._snapshot(scenario)
                scenario_root = self._profile_root() / str(scenario["id"])
                main_payloads = scenario_root / "main_payloads.txt"
                shard_payload_count = int(snapshot["shard_payload_count"])

                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_path = Path(tmpdir)
                    env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
                    expected_files = dict(snapshot["expected_file_sha256"])
                    is_single_file = len(expected_files) == 1
                    output_path = tmp_path / ("restored.bin" if is_single_file else "restored")

                    cmd = [
                        sys.executable,
                        "-m",
                        "ethernity.cli",
                        "--config",
                        str(_CONFIG_PATH),
                        "recover",
                        "--payloads-file",
                        str(main_payloads),
                        "--output",
                        str(output_path),
                        "--quiet",
                    ]
                    if shard_payload_count > 0:
                        cmd.extend(
                            [
                                "--shard-payloads-file",
                                str(scenario_root / "shard_payloads_threshold.txt"),
                            ]
                        )
                    else:
                        cmd.extend(["--passphrase", self._passphrase])

                    result = subprocess.run(
                        cmd,
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
                    self._assert_recovered_hashes(output_path, expected_files)

    def test_binary_payload_fixtures_decode_and_match_projection(self) -> None:
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                snapshot = self._snapshot(scenario)
                scenario_root = self._profile_root() / str(scenario["id"])
                binary_payloads = self._read_binary_payload_file(
                    scenario_root / "main_payloads.bin"
                )
                payload_lines = [
                    encode_qr_payload(payload, codec=QR_PAYLOAD_CODEC_BASE64)
                    for payload in binary_payloads
                ]
                projection = self._manifest_projection(payload_lines, self._passphrase)
                self.assertEqual(projection, snapshot["manifest_projection"])

    def test_new_backups_match_frozen_protocol_snapshots(self) -> None:
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                snapshot = self._snapshot(scenario)
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_path = Path(tmpdir)
                    output_dir = tmp_path / "backup"
                    env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})

                    cmd = [
                        sys.executable,
                        "-m",
                        "ethernity.cli",
                        "--config",
                        str(self._profile_config_path(tmp_path)),
                        "backup",
                        *self._backup_args_for_scenario(str(scenario["id"]), _SOURCE_ROOT),
                        "--design",
                        "forge",
                        "--output-dir",
                        str(output_dir),
                        "--quiet",
                    ]
                    result = subprocess.run(
                        cmd,
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

                    main_payloads = self._scan_payloads([output_dir / "qr_document.pdf"])
                    projection = self._manifest_projection(main_payloads, self._passphrase)
                    self.assertEqual(projection, snapshot["manifest_projection"])

                    self.assertEqual(
                        len(list(output_dir.glob("shard-*.pdf"))),
                        int(snapshot["expected_shard_pdfs"]),
                    )
                    self.assertEqual(
                        len(list(output_dir.glob("signing-key-shard-*.pdf"))),
                        int(snapshot["expected_signing_key_shard_pdfs"]),
                    )
                    for required_name in [
                        "qr_document.pdf",
                        "recovery_document.pdf",
                        "recovery_kit_index.pdf",
                    ]:
                        self.assertTrue((output_dir / required_name).exists())

    def _profile_root(self) -> Path:
        return _GOLDEN_ROOT / self.PROFILE_NAME

    def _scenarios(self) -> list[dict[str, object]]:
        return list(self._index["scenarios"])

    def _snapshot(self, scenario: dict[str, object]) -> dict[str, object]:
        snapshot_path = self._profile_root() / str(scenario["path"])
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    def _scan_payloads(self, pdf_paths: list[Path]) -> list[str]:
        payloads = scan_qr_payloads([str(path) for path in pdf_paths])
        normalized: list[str] = []
        for payload in payloads:
            if isinstance(payload, bytes):
                normalized.append(encode_qr_payload(payload, codec=QR_PAYLOAD_CODEC_BASE64))
            else:
                normalized.append(payload)
        return normalized

    def _profile_config_path(self, workspace: Path) -> Path:
        base = _CONFIG_PATH.read_text(encoding="utf-8")
        config_text = base.replace(
            'qr_payload_codec = "raw" # required: raw | base64',
            f'qr_payload_codec = "{self.QR_PAYLOAD_CODEC}" # required: raw | base64',
            1,
        )
        path = workspace / f"config_{self.PROFILE_NAME}.toml"
        path.write_text(config_text, encoding="utf-8")
        return path

    def _manifest_projection(self, payload_lines: list[str], passphrase: str) -> dict[str, object]:
        frames = []
        for line in payload_lines:
            cleaned = line.strip()
            if not cleaned:
                continue
            try:
                frame = decode_frame(decode_qr_payload(cleaned))
            except ValueError:
                continue
            frames.append(frame)
        main_frames = [frame for frame in frames if frame.frame_type == FrameType.MAIN_DOCUMENT]
        ciphertext = reassemble_payload(main_frames, expected_frame_type=FrameType.MAIN_DOCUMENT)
        plaintext = decrypt_bytes(ciphertext, passphrase=passphrase)
        manifest, _payload = decode_envelope(plaintext)
        files = [
            {
                "path": entry.path,
                "size": entry.size,
                "sha256": entry.sha256.hex(),
            }
            for entry in manifest.files
        ]
        files.sort(key=lambda item: str(item["path"]))
        return {
            "version": manifest.format_version,
            "sealed": manifest.sealed,
            "input_origin": manifest.input_origin,
            "input_roots": list(manifest.input_roots),
            "files": files,
        }

    def _read_binary_payload_file(self, path: Path) -> list[bytes]:
        blob = path.read_bytes()
        if len(blob) < 9:
            raise AssertionError(f"invalid binary payload fixture (too short): {path}")
        if blob[:4] != _BINARY_PAYLOADS_MAGIC:
            raise AssertionError(f"invalid binary payload fixture magic: {path}")
        version = blob[4]
        if version != _BINARY_PAYLOADS_VERSION:
            raise AssertionError(f"unsupported binary payload fixture version: {version}")
        count = struct.unpack(">I", blob[5:9])[0]
        offset = 9
        payloads: list[bytes] = []
        for _ in range(count):
            if offset + 4 > len(blob):
                raise AssertionError(f"truncated binary payload fixture length table: {path}")
            payload_len = struct.unpack(">I", blob[offset : offset + 4])[0]
            offset += 4
            end = offset + payload_len
            if end > len(blob):
                raise AssertionError(f"truncated binary payload fixture payload body: {path}")
            payloads.append(blob[offset:end])
            offset = end
        if offset != len(blob):
            raise AssertionError(f"extra trailing bytes in binary payload fixture: {path}")
        return payloads

    def _assert_recovered_hashes(self, output_path: Path, expected: dict[str, str]) -> None:
        expected_paths = set(expected.keys())
        if output_path.is_file():
            self.assertEqual(len(expected_paths), 1)
            only_path = next(iter(expected_paths))
            self.assertEqual(self._sha256_file(output_path), expected[only_path])
            return

        self.assertTrue(output_path.is_dir(), msg=f"missing restored output: {output_path}")
        found = {
            str(path.relative_to(output_path).as_posix()): self._sha256_file(path)
            for path in output_path.rglob("*")
            if path.is_file()
        }
        self.assertEqual(set(found.keys()), expected_paths)
        for rel_path, expected_hash in expected.items():
            self.assertEqual(found[rel_path], expected_hash)

    def _sha256_file(self, path: Path) -> str:
        hasher = hashlib.sha256()
        hasher.update(path.read_bytes())
        return hasher.hexdigest()

    def _backup_args_for_scenario(self, scenario_id: str, source_root: Path) -> list[str]:
        base = {
            "file_no_shard": [
                "--input",
                str(source_root / "standalone_secret.txt"),
                "--passphrase",
                self._passphrase,
            ],
            "directory_no_shard": [
                "--input-dir",
                str(source_root / "directory_payload"),
                "--passphrase",
                self._passphrase,
            ],
            "mixed_no_shard": [
                "--input",
                str(source_root / "mixed_input.txt"),
                "--input-dir",
                str(source_root / "directory_payload"),
                "--base-dir",
                str(source_root),
                "--passphrase",
                self._passphrase,
            ],
            "sharded_embedded": [
                "--input-dir",
                str(source_root / "directory_payload"),
                "--passphrase",
                self._passphrase,
                "--shard-threshold",
                "2",
                "--shard-count",
                "3",
                "--signing-key-mode",
                "embedded",
            ],
            "sharded_signing_sharded": [
                "--input",
                str(source_root / "mixed_input.txt"),
                "--input-dir",
                str(source_root / "directory_payload"),
                "--base-dir",
                str(source_root),
                "--passphrase",
                self._passphrase,
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
        }
        if scenario_id not in base:
            raise AssertionError(f"unknown frozen scenario: {scenario_id}")
        return base[scenario_id]
