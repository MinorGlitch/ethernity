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
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from ethernity.encoding.framing import Frame, decode_frame, encode_frame
from ethernity.encoding.qr_payloads import decode_qr_payload
from tests.test_support import build_cli_env, cli_subprocess_timeout_seconds

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_2" / "extension_golden"
_BINARY_PAYLOADS_MAGIC = b"EQPB"
_BINARY_PAYLOADS_VERSION = 1
_EXTENSION_DOCUMENT_RE = re.compile(
    r"^(qr_document|recovery_document|head_anchor)-(?P<index>\d+)-(?P<doc_id>[0-9a-f]{16})\.pdf$"
)


class TestStableV1_2ExtensionGolden(unittest.TestCase):
    def test_fixture_index_describes_frozen_compatibility_matrix(self) -> None:
        index = json.loads((_FIXTURE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["version"], "1.2.0")
        self.assertEqual(index["passphrase"], "stable-v1_2-extension-passphrase")
        self.assertEqual(
            index["profiles"],
            {
                "base64": {
                    "path": "base64/index.json",
                    "qr_payload_codec": "base64",
                },
                "raw": {
                    "path": "raw/index.json",
                    "qr_payload_codec": "raw",
                },
            },
        )

    def test_frozen_files_and_binary_payloads_are_intact(self) -> None:
        for scenario_root, snapshot in self._snapshots():
            with self.subTest(scenario=snapshot["scenario_id"], profile=snapshot["profile"]):
                for rel_path, expected_hash in cast(
                    dict[str, str], snapshot["file_hashes"]
                ).items():
                    file = scenario_root / rel_path
                    self.assertTrue(file.exists(), msg=f"missing fixture file: {file}")
                    self.assertEqual(self._sha256_file(file), expected_hash)

                for fixtures in (
                    cast(dict[str, Any], snapshot["payload_fixtures"]),
                    cast(dict[str, Any], snapshot["shard_fixtures"]),
                ):
                    for fixture in fixtures.values():
                        self._assert_binary_payload_fixture_matches_text(
                            scenario_root,
                            cast(dict[str, str], fixture),
                        )

    def test_frozen_wire_matrix_recovers_latest_state(self) -> None:
        """One recovery per scenario proves compatibility without repeating selector matrices."""
        for scenario_root, snapshot in self._snapshots():
            with self.subTest(scenario=snapshot["scenario_id"], profile=snapshot["profile"]):
                with tempfile.TemporaryDirectory() as tmpdir:
                    output = Path(tmpdir) / "recovered"
                    cmd = self._run_task_args(
                        "restore",
                        "--payloads-file",
                        scenario_root / snapshot["payload_fixtures"]["chain"]["text"],
                        "--output",
                        output,
                        "--yes",
                        *self._unlock_args(scenario_root, snapshot),
                    )
                    self._run_ok(cmd)
                    latest_state = sorted(cast(dict[str, str], snapshot["extension_doc_hashes"]))[
                        -1
                    ]
                    self._assert_output_hashes(
                        output,
                        cast(dict[str, dict[str, str]], snapshot["states"])[latest_state],
                    )

    def test_frozen_extension_documents_retain_their_original_layout(self) -> None:
        for scenario_root, snapshot in self._snapshots():
            chain_dir = scenario_root / str(snapshot["chain_dir"])
            for extension_dir in sorted((chain_dir / "extensions").glob("[0-9][0-9]*")):
                pdf_names = {path.name for path in extension_dir.glob("*.pdf")}
                matches = [_EXTENSION_DOCUMENT_RE.fullmatch(name) for name in pdf_names]
                self.assertTrue(all(matches), msg=f"unexpected extension files: {pdf_names}")
                self.assertEqual(len(pdf_names), 3)
                self.assertEqual(
                    {match.group(1) for match in matches if match is not None},
                    {"qr_document", "recovery_document", "head_anchor"},
                )
                self.assertEqual(
                    len(
                        {
                            (match.group("index"), match.group("doc_id"))
                            for match in matches
                            if match is not None
                        }
                    ),
                    1,
                )

    def test_one_representative_pdf_chain_scans_and_recovers(self) -> None:
        scenario_root = _FIXTURE_ROOT / "base64" / "gzip_replacement_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recovered"
            self._run_ok(
                self._run_task_args(
                    "restore",
                    "--scan",
                    scenario_root / str(snapshot["chain_dir"]),
                    "--passphrase",
                    str(snapshot["passphrase"]),
                    "--output",
                    output,
                    "--yes",
                )
            )
            self._assert_output_hashes(
                output,
                cast(dict[str, dict[str, str]], snapshot["states"])["extension_01"],
            )

    def _snapshots(self) -> list[tuple[Path, dict[str, Any]]]:
        cases: list[tuple[Path, dict[str, Any]]] = []
        for index_path in sorted(_FIXTURE_ROOT.glob("*/index.json")):
            index = json.loads(index_path.read_text(encoding="utf-8"))
            for scenario in index["scenarios"]:
                snapshot_path = index_path.parent / str(scenario["path"])
                cases.append((snapshot_path.parent, self._snapshot_at(snapshot_path)))
        return cases

    @staticmethod
    def _snapshot_at(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _unlock_args(scenario_root: Path, snapshot: dict[str, Any]) -> list[str]:
        root_shards = cast(dict[str, Any], snapshot["shard_fixtures"]).get("root")
        if root_shards is not None:
            return ["--recovery-payloads-file", str(scenario_root / root_shards["text"])]
        return ["--passphrase", str(snapshot["passphrase"])]

    def _run_ok(self, cmd: list[str]) -> None:
        result = self._run(cmd)
        self.assertEqual(result.returncode, 0, msg=result.stderr.strip() or result.stdout.strip())

    @staticmethod
    def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as xdg_home:
            return subprocess.run(
                cmd,
                cwd=_REPO_ROOT,
                env=build_cli_env(overrides={"XDG_CONFIG_HOME": xdg_home}),
                capture_output=True,
                text=True,
                check=False,
                timeout=cli_subprocess_timeout_seconds(),
            )

    @staticmethod
    def _run_task_args(*args: object) -> list[str]:
        return [sys.executable, "-m", "ethernity", "run", *[str(arg) for arg in args]]

    def _assert_output_hashes(self, output: Path, expected_hashes: dict[str, str]) -> None:
        found = {
            path.relative_to(output).as_posix(): self._sha256_file(path)
            for path in output.rglob("*")
            if path.is_file()
        }
        self.assertEqual(found, expected_hashes)

    def _assert_binary_payload_fixture_matches_text(
        self,
        scenario_root: Path,
        fixture: dict[str, str],
    ) -> None:
        text_frames = self._payload_frames(scenario_root / fixture["text"])
        binary_payloads = self._read_binary_payload_file(scenario_root / fixture["binary"])
        self.assertEqual(len(binary_payloads), len(text_frames))
        for payload, text_frame in zip(binary_payloads, text_frames, strict=True):
            self.assertEqual(decode_frame(payload), text_frame)
            self.assertEqual(payload, encode_frame(text_frame))

    @staticmethod
    def _payload_frames(path: Path) -> list[Frame]:
        return [
            decode_frame(decode_qr_payload(line.strip()))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    @staticmethod
    def _read_binary_payload_file(path: Path) -> list[bytes]:
        blob = path.read_bytes()
        if len(blob) < 9 or blob[:4] != _BINARY_PAYLOADS_MAGIC:
            raise AssertionError(f"invalid binary payload fixture: {path}")
        if blob[4] != _BINARY_PAYLOADS_VERSION:
            raise AssertionError(f"unsupported binary payload fixture version: {blob[4]}")
        count = struct.unpack(">I", blob[5:9])[0]
        offset = 9
        payloads: list[bytes] = []
        for _ in range(count):
            if offset + 4 > len(blob):
                raise AssertionError(f"truncated binary payload fixture: {path}")
            payload_len = struct.unpack(">I", blob[offset : offset + 4])[0]
            offset += 4
            end = offset + payload_len
            if end > len(blob):
                raise AssertionError(f"truncated binary payload fixture: {path}")
            payloads.append(blob[offset:end])
            offset = end
        if offset != len(blob):
            raise AssertionError(f"extra trailing bytes in binary payload fixture: {path}")
        return payloads

    @staticmethod
    def _sha256_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
