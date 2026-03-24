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
from typing import Any, cast

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.crypto import decrypt_bytes
from ethernity.crypto.sharding import decode_shard_payload
from ethernity.encoding.chunking import reassemble_payload
from ethernity.encoding.framing import FrameType, decode_frame, encode_frame
from ethernity.encoding.qr_payloads import (
    QR_PAYLOAD_CODEC_BASE64,
    decode_qr_payload,
    encode_qr_payload,
)
from ethernity.formats.envelope_codec import decode_envelope
from ethernity.qr.scan import scan_qr_payloads
from tests.e2e._mint_fixture_support import (
    MINT_SNAPSHOT_FILENAME,
    MintFrozenCase,
    mint_cases_for_scenario,
    mint_cli_args,
)
from tests.test_support import build_cli_env, ensure_playwright_browsers

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = DEFAULT_CONFIG_PATH
_BINARY_PAYLOADS_MAGIC = b"EQPB"
_BINARY_PAYLOADS_VERSION = 1


class FrozenProfileTestCase(unittest.TestCase):
    __test__ = False
    FIXTURE_VERSION = "v1_0"
    SOURCE_VERSION = "v1_0"
    PROFILE_NAME = ""
    QR_PAYLOAD_CODEC = ""
    INCLUDE_SHARD_SET_FIELDS = False

    @classmethod
    def setUpClass(cls) -> None:
        if not cls.PROFILE_NAME or cls.QR_PAYLOAD_CODEC not in {"raw", "base64"}:
            raise AssertionError("PROFILE_NAME and QR_PAYLOAD_CODEC must be configured")
        ensure_playwright_browsers()
        index_path = cls._golden_root() / cls.PROFILE_NAME / "index.json"
        cls._index = json.loads(index_path.read_text(encoding="utf-8"))
        cls._passphrase = str(cls._index["passphrase"])

    @classmethod
    def _source_root(cls) -> Path:
        return _REPO_ROOT / "tests" / "fixtures" / cls.SOURCE_VERSION / "source"

    @classmethod
    def _golden_root(cls) -> Path:
        return _REPO_ROOT / "tests" / "fixtures" / cls.FIXTURE_VERSION / "golden"

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

    def test_frozen_backup_shards_match_semantic_snapshots(self) -> None:
        expected_version = 2 if self.INCLUDE_SHARD_SET_FIELDS else 1
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                snapshot = self._snapshot(scenario)
                scenario_root = self._profile_root() / str(scenario["id"])
                backup_shard_pdfs = self._backup_shard_pdfs(scenario_root)
                expected_projections = cast(
                    dict[str, list[dict[str, Any]]] | None,
                    snapshot.get("backup_shard_projections"),
                )
                if expected_projections is not None:
                    self.assertEqual(
                        self._shard_projections_by_file(backup_shard_pdfs),
                        expected_projections,
                    )
                self.assertEqual(
                    len([path for path in backup_shard_pdfs if path.name.startswith("shard-")]),
                    int(snapshot["expected_shard_pdfs"]),
                )
                self.assertEqual(
                    len(
                        [
                            path
                            for path in backup_shard_pdfs
                            if path.name.startswith("signing-key-shard-")
                        ]
                    ),
                    int(snapshot["expected_signing_key_shard_pdfs"]),
                )
                for pdf_path in backup_shard_pdfs:
                    with self.subTest(scenario=scenario["id"], artifact=pdf_path.name):
                        frames = self._valid_scanned_frames([pdf_path])
                        self.assertGreaterEqual(
                            len(frames), 1, msg=f"missing shard frames in {pdf_path}"
                        )
                        for frame in frames:
                            payload = decode_shard_payload(frame.data)
                            self.assertEqual(payload.version, expected_version)
                            if self.INCLUDE_SHARD_SET_FIELDS:
                                self.assertIsNotNone(payload.shard_set_id)
                            else:
                                self.assertIsNone(payload.shard_set_id)

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

    def test_shard_binary_payload_fixtures_decode_and_match_semantics(self) -> None:
        expected_version = 2 if self.INCLUDE_SHARD_SET_FIELDS else 1
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                scenario_root = self._profile_root() / str(scenario["id"])
                self._assert_shard_binary_fixture_matches_pdfs(
                    scenario_root / "shard_payloads_threshold.bin",
                    sorted((scenario_root / "backup").glob("shard-*.pdf")),
                    expected_version=expected_version,
                )
                self._assert_shard_binary_fixture_matches_pdfs(
                    scenario_root / "signing_key_shard_payloads_threshold.bin",
                    sorted((scenario_root / "backup").glob("signing-key-shard-*.pdf")),
                    expected_version=expected_version,
                )

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
                        *self._backup_args_for_scenario(str(scenario["id"]), self._source_root()),
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

    def test_mint_from_frozen_backups_matches_snapshots(self) -> None:
        for scenario in self._scenarios():
            scenario_id = str(scenario["id"])
            mint_snapshot = self._mint_snapshot(scenario_id)
            if mint_snapshot is None:
                continue
            for case in mint_cases_for_scenario(scenario_id):
                with self.subTest(scenario=scenario_id, mint_case=case.case_id):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        tmp_path = Path(tmpdir)
                        env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
                        scenario_root = self._profile_root() / scenario_id
                        output_dir = tmp_path / "minted"
                        cmd = [
                            sys.executable,
                            "-m",
                            "ethernity.cli",
                            "--config",
                            str(self._profile_config_path(tmp_path)),
                            *self._mint_args(case, scenario_root, output_dir),
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
                        mint_cases = cast(dict[str, dict[str, Any]], mint_snapshot["mint_cases"])
                        self._assert_mint_hashes(output_dir, mint_cases[case.case_id])

    def test_minted_passphrase_shards_recover_original_payloads(self) -> None:
        for scenario in self._scenarios():
            snapshot = self._snapshot(scenario)
            scenario_id = str(scenario["id"])
            if self._mint_snapshot(scenario_id) is None:
                continue
            cases = [
                case for case in mint_cases_for_scenario(scenario_id) if case.mint_passphrase_shards
            ]
            for case in cases:
                with self.subTest(scenario=scenario_id, mint_case=case.case_id):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        tmp_path = Path(tmpdir)
                        env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
                        scenario_root = self._profile_root() / scenario_id
                        output_dir = tmp_path / "minted"
                        self._run_cli_command(
                            [
                                sys.executable,
                                "-m",
                                "ethernity.cli",
                                "--config",
                                str(self._profile_config_path(tmp_path)),
                                *self._mint_args(case, scenario_root, output_dir),
                            ],
                            env=env,
                        )
                        shard_payloads_file = tmp_path / "minted_shard_payloads.txt"
                        self._write_scanned_payloads(
                            sorted(output_dir.glob("shard-*.pdf"))[: int(case.shard_threshold)],
                            shard_payloads_file,
                        )
                        expected_files = cast(dict[str, str], snapshot["expected_file_sha256"])
                        is_single_file = len(expected_files) == 1
                        recover_output = tmp_path / (
                            "restored.bin" if is_single_file else "restored"
                        )
                        self._run_cli_command(
                            [
                                sys.executable,
                                "-m",
                                "ethernity.cli",
                                "--config",
                                str(self._profile_config_path(tmp_path)),
                                "recover",
                                "--payloads-file",
                                str(scenario_root / "main_payloads.txt"),
                                "--shard-payloads-file",
                                str(shard_payloads_file),
                                "--output",
                                str(recover_output),
                                "--quiet",
                            ],
                            env=env,
                        )
                        self._assert_recovered_hashes(recover_output, expected_files)

    def test_minted_signing_key_shards_allow_followup_remint(self) -> None:
        scenario_id = "sharded_signing_sharded"
        snapshot = self._snapshot({"path": f"{scenario_id}/snapshot.json"})
        self.assertIsNotNone(self._mint_snapshot(scenario_id))
        scenario_root = self._profile_root() / scenario_id
        followup_case = next(
            case
            for case in mint_cases_for_scenario(scenario_id)
            if case.case_id == "external_signing_only"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            first_output = tmp_path / "minted-signing-only"
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    *self._mint_args(followup_case, scenario_root, first_output),
                ],
                env=env,
            )
            minted_signing_payloads = tmp_path / "minted_signing_payloads.txt"
            self._write_scanned_payloads(
                sorted(first_output.glob("signing-key-shard-*.pdf"))[
                    : self._required_int(followup_case.signing_key_shard_threshold)
                ],
                minted_signing_payloads,
            )

            second_output = tmp_path / "followup-passphrase-mint"
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    "mint",
                    "--payloads-file",
                    str(scenario_root / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(scenario_root / "shard_payloads_threshold.txt"),
                    "--signing-key-shard-payloads-file",
                    str(minted_signing_payloads),
                    "--shard-threshold",
                    "2",
                    "--shard-count",
                    "3",
                    "--no-signing-key-shards",
                    "--output-dir",
                    str(second_output),
                    "--quiet",
                ],
                env=env,
            )

            followup_shard_payloads = tmp_path / "followup_shard_payloads.txt"
            self._write_scanned_payloads(
                sorted(second_output.glob("shard-*.pdf"))[:2], followup_shard_payloads
            )
            recover_output = tmp_path / "restored"
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    "recover",
                    "--payloads-file",
                    str(scenario_root / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(followup_shard_payloads),
                    "--output",
                    str(recover_output),
                    "--quiet",
                ],
                env=env,
            )
            self._assert_recovered_hashes(
                recover_output,
                cast(dict[str, str], snapshot["expected_file_sha256"]),
            )

    def test_minted_signing_key_replacement_shards_allow_followup_remint(self) -> None:
        scenario_id = "sharded_signing_sharded"
        snapshot = self._snapshot({"path": f"{scenario_id}/snapshot.json"})
        scenario_root = self._profile_root() / scenario_id
        mint_case = next(
            case
            for case in mint_cases_for_scenario(scenario_id)
            if case.case_id == "external_signing_only"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            first_output = tmp_path / "minted-signing-only"
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    *self._mint_args(mint_case, scenario_root, first_output),
                ],
                env=env,
            )

            provided_signing_payloads = tmp_path / "provided_signing_payloads.txt"
            provided_signing_shards = sorted(first_output.glob("signing-key-shard-*.pdf"))[
                : self._required_int(mint_case.signing_key_shard_threshold)
            ]
            self._write_scanned_payloads(provided_signing_shards, provided_signing_payloads)

            replacement_output = tmp_path / "replacement-signing-only"
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    "mint",
                    "--payloads-file",
                    str(scenario_root / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(scenario_root / "shard_payloads_threshold.txt"),
                    "--signing-key-shard-payloads-file",
                    str(provided_signing_payloads),
                    "--signing-key-replacement-count",
                    "1",
                    "--no-passphrase-shards",
                    "--output-dir",
                    str(replacement_output),
                    "--quiet",
                ],
                env=env,
            )

            replacement_signing_shards = sorted(replacement_output.glob("signing-key-shard-*.pdf"))
            self.assertEqual(len(replacement_signing_shards), 1)

            remint_signing_payloads = tmp_path / "remint_signing_payloads.txt"
            self._write_scanned_payloads(
                [provided_signing_shards[0], replacement_signing_shards[0]],
                remint_signing_payloads,
            )

            followup_output = tmp_path / "followup-passphrase-mint"
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    "mint",
                    "--payloads-file",
                    str(scenario_root / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(scenario_root / "shard_payloads_threshold.txt"),
                    "--signing-key-shard-payloads-file",
                    str(remint_signing_payloads),
                    "--shard-threshold",
                    "2",
                    "--shard-count",
                    "3",
                    "--no-signing-key-shards",
                    "--output-dir",
                    str(followup_output),
                    "--quiet",
                ],
                env=env,
            )

            followup_shard_payloads = tmp_path / "followup_shard_payloads.txt"
            self._write_scanned_payloads(
                sorted(followup_output.glob("shard-*.pdf"))[:2],
                followup_shard_payloads,
            )
            recover_output = tmp_path / "restored-from-replacement-authority"
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    "recover",
                    "--payloads-file",
                    str(scenario_root / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(followup_shard_payloads),
                    "--output",
                    str(recover_output),
                    "--quiet",
                ],
                env=env,
            )
            self._assert_recovered_hashes(
                recover_output,
                cast(dict[str, str], snapshot["expected_file_sha256"]),
            )

    def test_minted_signing_key_replacement_shards_reject_exact_threshold_mixed_sets(self) -> None:
        if not self.INCLUDE_SHARD_SET_FIELDS:
            self.skipTest(
                "mixed-set exact-threshold detection is only enforced in shard payload v2"
            )

        scenario_id = "sharded_signing_sharded"
        scenario_root = self._profile_root() / scenario_id
        mint_case = next(
            case
            for case in mint_cases_for_scenario(scenario_id)
            if case.case_id == "external_signing_only"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            first_output = tmp_path / "minted-signing-first"
            second_output = tmp_path / "minted-signing-second"
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    *self._mint_args(mint_case, scenario_root, first_output),
                ],
                env=env,
            )
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    *self._mint_args(mint_case, scenario_root, second_output),
                ],
                env=env,
            )

            first_signing_shards = sorted(first_output.glob("signing-key-shard-*.pdf"))
            second_signing_shards = sorted(second_output.glob("signing-key-shard-*.pdf"))
            self.assertGreaterEqual(len(first_signing_shards), 2)
            self.assertGreaterEqual(len(second_signing_shards), 2)

            first_projection = self._frame_to_shard_projection(
                self._valid_scanned_frames([first_signing_shards[0]])[0]
            )
            second_projection = self._frame_to_shard_projection(
                self._valid_scanned_frames([second_signing_shards[0]])[0]
            )
            self.assertEqual(len(cast(str, first_projection["set_id"])), 32)
            self.assertEqual(len(cast(str, second_projection["set_id"])), 32)
            self.assertNotEqual(first_projection["set_id"], second_projection["set_id"])

            mixed_signing_payloads = tmp_path / "mixed_signing_payloads.txt"
            self._write_scanned_payloads(
                [first_signing_shards[0], second_signing_shards[1]],
                mixed_signing_payloads,
            )
            replacement_output = tmp_path / "rejected-signing-replacement"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    "mint",
                    "--payloads-file",
                    str(scenario_root / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(scenario_root / "shard_payloads_threshold.txt"),
                    "--signing-key-shard-payloads-file",
                    str(mixed_signing_payloads),
                    "--signing-key-replacement-count",
                    "1",
                    "--no-passphrase-shards",
                    "--output-dir",
                    str(replacement_output),
                    "--quiet",
                ],
                cwd=_REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "not mutually compatible",
                (result.stderr or result.stdout).lower(),
            )

    def test_minted_shards_reject_exact_threshold_mixed_sets(self) -> None:
        if not self.INCLUDE_SHARD_SET_FIELDS:
            self.skipTest(
                "mixed-set exact-threshold detection is only enforced in shard payload v2"
            )

        scenario_id = "sharded_embedded"
        scenario_root = self._profile_root() / scenario_id
        mint_case = next(
            case
            for case in mint_cases_for_scenario(scenario_id)
            if case.case_id == "embedded_from_passphrase_shards_both"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            first_output = tmp_path / "minted-first"
            second_output = tmp_path / "minted-second"
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    *self._mint_args(mint_case, scenario_root, first_output),
                ],
                env=env,
            )
            self._run_cli_command(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    *self._mint_args(mint_case, scenario_root, second_output),
                ],
                env=env,
            )

            first_shards = sorted(first_output.glob("shard-*.pdf"))
            second_shards = sorted(second_output.glob("shard-*.pdf"))
            self.assertGreaterEqual(len(first_shards), 2)
            self.assertGreaterEqual(len(second_shards), 2)

            first_projection = self._frame_to_shard_projection(
                self._valid_scanned_frames([first_shards[0]])[0]
            )
            second_projection = self._frame_to_shard_projection(
                self._valid_scanned_frames([second_shards[0]])[0]
            )
            self.assertEqual(len(cast(str, first_projection["set_id"])), 32)
            self.assertEqual(len(cast(str, second_projection["set_id"])), 32)
            self.assertNotEqual(first_projection["set_id"], second_projection["set_id"])

            mixed_payloads = tmp_path / "mixed_shard_payloads.txt"
            self._write_scanned_payloads([first_shards[0], second_shards[1]], mixed_payloads)
            recover_output = tmp_path / "rejected-restore"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ethernity.cli",
                    "--config",
                    str(self._profile_config_path(tmp_path)),
                    "recover",
                    "--payloads-file",
                    str(scenario_root / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(mixed_payloads),
                    "--output",
                    str(recover_output),
                    "--quiet",
                ],
                cwd=_REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "not mutually compatible",
                (result.stderr or result.stdout).lower(),
            )

    def _profile_root(self) -> Path:
        return self._golden_root() / self.PROFILE_NAME

    def _backup_shard_pdfs(self, scenario_root: Path) -> list[Path]:
        backup_dir = scenario_root / "backup"
        return sorted(backup_dir.glob("shard-*.pdf")) + sorted(
            backup_dir.glob("signing-key-shard-*.pdf")
        )

    def _mint_args(self, case: MintFrozenCase, scenario_root: Path, output_dir: Path) -> list[str]:
        args = mint_cli_args(case, scenario_root, self._passphrase)
        output_index = args.index("--output-dir") + 1
        args[output_index] = str(output_dir)
        return args

    def _scenarios(self) -> list[dict[str, object]]:
        return list(self._index["scenarios"])

    def _snapshot(self, scenario: dict[str, object]) -> dict[str, object]:
        snapshot_path = self._profile_root() / str(scenario["path"])
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    def _mint_snapshot(self, scenario_id: str) -> dict[str, object] | None:
        snapshot_path = self._profile_root() / scenario_id / MINT_SNAPSHOT_FILENAME
        if not snapshot_path.exists():
            return None
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    def _run_cli_command(self, cmd: list[str], *, env: dict[str, str]) -> None:
        result = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.strip() or result.stdout.strip())

    def _assert_mint_hashes(self, output_dir: Path, snapshot: dict[str, Any]) -> None:
        expected_projections = cast(dict[str, list[dict[str, Any]]], snapshot["shard_projections"])
        actual_projections = self._shard_projections_by_file(sorted(output_dir.glob("*.pdf")))
        self.assertEqual(actual_projections, expected_projections)
        self.assertEqual(
            len(list(output_dir.glob("shard-*.pdf"))), int(snapshot["expected_shard_pdfs"])
        )
        self.assertEqual(
            len(list(output_dir.glob("signing-key-shard-*.pdf"))),
            int(snapshot["expected_signing_key_shard_pdfs"]),
        )

    def _write_scanned_payloads(self, pdf_paths: list[Path], destination: Path) -> None:
        payloads = scan_qr_payloads([str(path) for path in pdf_paths])
        normalized: list[str] = []
        for payload in payloads:
            if isinstance(payload, bytes):
                try:
                    frame = decode_frame(payload)
                except ValueError:
                    continue
                encoded = encode_qr_payload(encode_frame(frame), codec=QR_PAYLOAD_CODEC_BASE64)
                normalized.append(
                    encoded.decode("ascii") if isinstance(encoded, bytes) else encoded
                )
            else:
                try:
                    frame = decode_frame(decode_qr_payload(payload))
                except ValueError:
                    continue
                encoded = encode_qr_payload(encode_frame(frame), codec=QR_PAYLOAD_CODEC_BASE64)
                normalized.append(
                    encoded.decode("ascii") if isinstance(encoded, bytes) else encoded
                )
        destination.write_text("\n".join(normalized), encoding="utf-8")

    def _scan_payloads(self, pdf_paths: list[Path]) -> list[str]:
        payloads = scan_qr_payloads([str(path) for path in pdf_paths])
        normalized: list[str] = []
        for payload in payloads:
            if isinstance(payload, bytes):
                encoded = encode_qr_payload(payload, codec=QR_PAYLOAD_CODEC_BASE64)
                normalized.append(
                    encoded.decode("ascii") if isinstance(encoded, bytes) else encoded
                )
            else:
                normalized.append(payload)
        return normalized

    def _shard_projections_by_file(self, pdf_paths: list[Path]) -> dict[str, list[dict[str, Any]]]:
        shard_set_labels: dict[str, str] = {}
        payload_hashes: dict[str, list[dict[str, Any]]] = {}
        for pdf_path in pdf_paths:
            payload_hashes[pdf_path.name] = [
                self._normalize_shard_projection(
                    self._frame_to_shard_projection(frame),
                    shard_set_labels=shard_set_labels,
                )
                for frame in self._valid_scanned_frames([pdf_path])
            ]
        return payload_hashes

    def _normalize_shard_projection(
        self,
        projection: dict[str, Any],
        *,
        shard_set_labels: dict[str, str],
    ) -> dict[str, Any]:
        normalized = dict(projection)
        if not self.INCLUDE_SHARD_SET_FIELDS:
            return normalized
        set_id = cast(str | None, normalized.get("set_id"))
        if set_id is None:
            return normalized
        label = shard_set_labels.get(set_id)
        if label is None:
            label = f"set-{len(shard_set_labels) + 1}"
            shard_set_labels[set_id] = label
        normalized["set_id"] = label
        return normalized

    def _valid_scanned_frames(self, pdf_paths: list[Path]) -> list[Any]:
        payloads = scan_qr_payloads([str(path) for path in pdf_paths])
        frames = []
        for payload in payloads:
            try:
                if isinstance(payload, bytes):
                    frame = decode_frame(payload)
                else:
                    frame = decode_frame(decode_qr_payload(payload))
            except ValueError:
                continue
            frames.append(frame)
        return frames

    def _frame_to_shard_projection(self, frame: Any) -> dict[str, Any]:
        payload = decode_shard_payload(frame.data)
        projection: dict[str, Any] = {
            "doc_id": frame.doc_id.hex(),
            "share_index": payload.share_index,
            "threshold": payload.threshold,
            "share_count": payload.share_count,
            "key_type": payload.key_type,
            "secret_len": payload.secret_len,
            "doc_hash": payload.doc_hash.hex(),
            "sign_pub": payload.sign_pub.hex(),
        }
        if self.INCLUDE_SHARD_SET_FIELDS:
            projection["version"] = payload.version
            projection["set_id"] = (
                None if payload.shard_set_id is None else payload.shard_set_id.hex()
            )
        return projection

    def _assert_shard_binary_fixture_matches_pdfs(
        self,
        binary_path: Path,
        pdf_paths: list[Path],
        *,
        expected_version: int,
    ) -> None:
        if not binary_path.exists():
            self.assertEqual(pdf_paths, [])
            return
        payloads = self._read_binary_payload_file(binary_path)
        frames = [decode_frame(payload) for payload in payloads]
        self.assertGreaterEqual(len(frames), 1, msg=f"missing shard payloads in {binary_path}")
        self._assert_shard_frame_versions(frames, expected_version=expected_version)
        expected_pdf_paths = pdf_paths[: len(frames)]
        self.assertEqual(len(expected_pdf_paths), len(frames))
        self.assertEqual(
            self._shard_projections_from_frames(frames),
            self._shard_projections_from_pdf_paths(expected_pdf_paths),
        )

    def _assert_shard_frame_versions(self, frames: list[Any], *, expected_version: int) -> None:
        for frame in frames:
            payload = decode_shard_payload(frame.data)
            self.assertEqual(payload.version, expected_version)
            if self.INCLUDE_SHARD_SET_FIELDS:
                self.assertIsNotNone(payload.shard_set_id)
            else:
                self.assertIsNone(payload.shard_set_id)

    def _shard_projections_from_frames(self, frames: list[Any]) -> list[dict[str, Any]]:
        shard_set_labels: dict[str, str] = {}
        return [
            self._normalize_shard_projection(
                self._frame_to_shard_projection(frame),
                shard_set_labels=shard_set_labels,
            )
            for frame in frames
        ]

    def _shard_projections_from_pdf_paths(self, pdf_paths: list[Path]) -> list[dict[str, Any]]:
        return self._shard_projections_from_frames(self._valid_scanned_frames(pdf_paths))

    @staticmethod
    def _required_int(value: int | None) -> int:
        if value is None:
            raise AssertionError("expected integer value")
        return value

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
