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
import tomllib
import unittest
from functools import cache
from pathlib import Path
from typing import Any, cast

from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.crypto.sharding import decode_shard_payload
from ethernity.encoding.framing import decode_frame, encode_frame
from ethernity.encoding.qr_payloads import (
    QR_PAYLOAD_CODEC_BASE64,
    decode_qr_payload,
    encode_qr_payload,
)
from ethernity.qr.scan import scan_qr_payloads
from tests.e2e._replacement_fixture_support import (
    REPLACEMENT_SNAPSHOT_FILENAME,
    ReplacementFrozenCase,
    replacement_cases_for_scenario,
    replacement_cli_args,
)
from tests.test_support import (
    build_cli_env,
    cli_subprocess_timeout_seconds,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = DEFAULT_CONFIG_PATH
_BINARY_PAYLOADS_MAGIC = b"EQPB"
_BINARY_PAYLOADS_VERSION = 1


def _run_cli_subprocess(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    kwargs.setdefault("timeout", cli_subprocess_timeout_seconds())
    return subprocess.run(*args, **kwargs)


@cache
def _scan_unchanged_pdf(path: str, _sha256: str) -> tuple[bytes | str, ...]:
    """Decode an immutable PDF once while invalidating the cache when its bytes change."""
    return tuple(scan_qr_payloads([path]))


class FrozenProfileTestCase(unittest.TestCase):
    __test__ = False
    FIXTURE_VERSION = "v1_0"
    PROFILE_NAME = ""
    QR_PAYLOAD_CODEC = ""
    INCLUDE_SHARD_SET_FIELDS = False

    @classmethod
    def setUpClass(cls) -> None:
        if not cls.PROFILE_NAME or cls.QR_PAYLOAD_CODEC not in {"raw", "base64"}:
            raise AssertionError("PROFILE_NAME and QR_PAYLOAD_CODEC must be configured")
        index_path = cls._golden_root() / cls.PROFILE_NAME / "index.json"
        cls._index = json.loads(index_path.read_text(encoding="utf-8"))
        cls._passphrase = str(cls._index["passphrase"])
        cls._prepared_output_context = tempfile.TemporaryDirectory(
            prefix=f"ethernity-{cls.FIXTURE_VERSION}-{cls.PROFILE_NAME}-"
        )
        cls._prepared_output_root = Path(cls._prepared_output_context.name)
        cls._prepared_replacements: dict[tuple[str, str], Path] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._prepared_output_context.cleanup()

    @classmethod
    def _golden_root(cls) -> Path:
        return _REPO_ROOT / "tests" / "fixtures" / cls.FIXTURE_VERSION / "golden"

    def test_frozen_file_hashes_match_snapshots(self) -> None:
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                snapshot = self._snapshot(scenario)
                scenario_root = self._profile_root() / str(scenario["id"])
                for rel_path, expected_hash in snapshot["file_hashes"].items():
                    if rel_path.endswith((".txt", ".bin")):
                        file_path = scenario_root / rel_path
                    else:
                        file_path = scenario_root / "backup" / rel_path
                    self.assertTrue(
                        file_path.exists(),
                        msg=f"missing file: {file_path}",
                    )
                    self.assertEqual(self._sha256_file(file_path), expected_hash)

    def test_frozen_shard_inventory_matches_snapshots(self) -> None:
        expected_version = 2 if self.INCLUDE_SHARD_SET_FIELDS else 1
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                snapshot = self._snapshot(scenario)
                scenario_root = self._profile_root() / str(scenario["id"])
                backup_shard_pdfs = self._backup_shard_pdfs(scenario_root)
                expected_shard_details = cast(
                    dict[str, list[dict[str, Any]]] | None,
                    snapshot.get("backup_shard_projections"),
                )
                if expected_shard_details is not None:
                    self.assertEqual(
                        {path.name for path in backup_shard_pdfs},
                        set(expected_shard_details),
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
                if expected_shard_details is not None:
                    for shard_records in expected_shard_details.values():
                        self.assertGreaterEqual(len(shard_records), 1)
                        for shard_record in shard_records:
                            if self.INCLUDE_SHARD_SET_FIELDS:
                                self.assertEqual(shard_record["version"], expected_version)
                                self.assertIsNotNone(shard_record["set_id"])
                            else:
                                self.assertNotIn("version", shard_record)
                                self.assertNotIn("set_id", shard_record)

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

                    cmd = self._run_task_args(
                        _CONFIG_PATH,
                        "restore",
                        "--payloads-file",
                        main_payloads,
                        "--output",
                        output_path,
                        "--yes",
                    )
                    if shard_payload_count > 0:
                        cmd.extend(
                            [
                                "--recovery-payloads-file",
                                str(scenario_root / "shard_payloads_threshold.txt"),
                            ]
                        )
                    else:
                        cmd.extend(["--passphrase", self._passphrase])

                    result = _run_cli_subprocess(
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

    def _verify_representative_frozen_pdf_backup_recovers(self) -> None:
        scenario_id = "sharded_signing_sharded"
        scenario = next(scenario for scenario in self._scenarios() if scenario["id"] == scenario_id)
        snapshot = self._snapshot(scenario)
        scenario_root = self._profile_root() / scenario_id
        representative_shards = [
            sorted((scenario_root / "backup").glob("shard-*.pdf"))[0],
            sorted((scenario_root / "backup").glob("signing-key-shard-*.pdf"))[0],
        ]
        representative_frames = [
            decode_frame(
                self._read_binary_payload_file(scenario_root / "shard_payloads_threshold.bin")[0]
            ),
            decode_frame(
                self._read_binary_payload_file(
                    scenario_root / "signing_key_shard_payloads_threshold.bin"
                )[0]
            ),
        ]
        expected_rows = self._shard_details_from_frames(representative_frames)
        self.assertEqual(
            self._shard_details_by_file(representative_shards),
            {
                path.name: [expected_row]
                for path, expected_row in zip(
                    representative_shards,
                    expected_rows,
                    strict=True,
                )
            },
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_path = tmp_path / "restored"
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            self._run_cli_command(
                self._run_task_args(
                    _CONFIG_PATH,
                    "restore",
                    "--scan",
                    scenario_root / "backup" / "qr_document.pdf",
                    "--recovery-payloads-file",
                    scenario_root / "shard_payloads_threshold.txt",
                    "--output",
                    output_path,
                    "--yes",
                ),
                env=env,
            )
            self._assert_recovered_hashes(
                output_path,
                cast(dict[str, str], snapshot["expected_file_sha256"]),
            )

    def test_binary_payload_fixtures_match_text_frames(self) -> None:
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                scenario_root = self._profile_root() / str(scenario["id"])
                binary_payloads = self._read_binary_payload_file(
                    scenario_root / "main_payloads.bin"
                )
                text_payloads = [
                    decode_qr_payload(line)
                    for line in (scenario_root / "main_payloads.txt")
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line.strip()
                ]
                self.assertEqual(binary_payloads, text_payloads)
                for payload in binary_payloads:
                    self.assertEqual(encode_frame(decode_frame(payload)), payload)

    def test_shard_binary_payload_fixtures_decode_and_match_semantics(self) -> None:
        expected_version = 2 if self.INCLUDE_SHARD_SET_FIELDS else 1
        for scenario in self._scenarios():
            with self.subTest(scenario=scenario["id"]):
                scenario_root = self._profile_root() / str(scenario["id"])
                snapshot = self._snapshot(scenario)
                expected_shard_details = cast(
                    dict[str, list[dict[str, Any]]] | None,
                    snapshot.get("backup_shard_projections"),
                )
                shard_set_labels: dict[str, str] = {}
                self._assert_shard_binary_fixture_matches_snapshot(
                    scenario_root / "shard_payloads_threshold.bin",
                    scenario_root / "shard_payloads_threshold.txt",
                    sorted((scenario_root / "backup").glob("shard-*.pdf")),
                    expected_version=expected_version,
                    expected_shard_details=expected_shard_details,
                    shard_set_labels=shard_set_labels,
                )
                self._assert_shard_binary_fixture_matches_snapshot(
                    scenario_root / "signing_key_shard_payloads_threshold.bin",
                    scenario_root / "signing_key_shard_payloads_threshold.txt",
                    sorted((scenario_root / "backup").glob("signing-key-shard-*.pdf")),
                    expected_version=expected_version,
                    expected_shard_details=expected_shard_details,
                    shard_set_labels=shard_set_labels,
                )

    def test_replacement_from_frozen_backups_matches_snapshots(self) -> None:
        for scenario in self._scenarios():
            scenario_id = str(scenario["id"])
            replacement_snapshot = self._replacement_snapshot(scenario_id)
            if replacement_snapshot is None:
                continue
            for case in self._replacement_cases_under_test(scenario_id):
                with self.subTest(scenario=scenario_id, replacement_case=case.case_id):
                    output_dir = self._prepared_replacement_output(scenario_id, case)
                    replacement_cases = cast(
                        dict[str, dict[str, Any]], replacement_snapshot["mint_cases"]
                    )
                    self._assert_replacement_hashes(output_dir, replacement_cases[case.case_id])

    def test_replacement_passphrase_shards_recover_original_payloads(self) -> None:
        for scenario in self._scenarios():
            snapshot = self._snapshot(scenario)
            scenario_id = str(scenario["id"])
            if self._replacement_snapshot(scenario_id) is None:
                continue
            cases = [
                case
                for case in self._replacement_cases_under_test(scenario_id)
                if case.create_passphrase_shards
            ]
            for case in cases:
                with self.subTest(scenario=scenario_id, replacement_case=case.case_id):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        tmp_path = Path(tmpdir)
                        env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
                        scenario_root = self._profile_root() / scenario_id
                        output_dir = self._prepared_replacement_output(scenario_id, case)
                        shard_payloads_file = tmp_path / "replacement_shard_payloads.txt"
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
                            self._run_task_args(
                                self._profile_config_path(tmp_path),
                                "restore",
                                "--payloads-file",
                                scenario_root / "main_payloads.txt",
                                "--recovery-payloads-file",
                                shard_payloads_file,
                                "--output",
                                recover_output,
                                "--yes",
                            ),
                            env=env,
                        )
                        self._assert_recovered_hashes(recover_output, expected_files)

    def _verify_replacement_signing_key_shards_allow_followup_replacement(self) -> None:
        scenario_id = "sharded_signing_sharded"
        snapshot = self._snapshot({"path": f"{scenario_id}/snapshot.json"})
        self.assertIsNotNone(self._replacement_snapshot(scenario_id))
        scenario_root = self._profile_root() / scenario_id
        followup_case = next(
            case
            for case in replacement_cases_for_scenario(scenario_id)
            if case.case_id == "external_signing_only"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            first_output = self._prepared_replacement_output(scenario_id, followup_case)
            replacement_signing_payloads = tmp_path / "replacement_signing_payloads.txt"
            self._write_scanned_payloads(
                sorted(first_output.glob("signing-key-shard-*.pdf"))[
                    : self._required_int(followup_case.signing_key_shard_threshold)
                ],
                replacement_signing_payloads,
            )

            second_output = tmp_path / "followup-passphrase-replacement"
            self._run_cli_command(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    "replace-recovery-docs",
                    "--payloads-file",
                    scenario_root / "main_payloads.txt",
                    "--recovery-payloads-file",
                    scenario_root / "shard_payloads_threshold.txt",
                    "--signing-key-payloads-file",
                    replacement_signing_payloads,
                    "--recovery-threshold",
                    "2",
                    "--recovery-count",
                    "3",
                    "--output-dir",
                    second_output,
                    "--yes",
                ),
                env=env,
            )

            followup_shard_payloads = tmp_path / "followup_shard_payloads.txt"
            self._write_scanned_payloads(
                sorted(second_output.glob("shard-*.pdf"))[:2], followup_shard_payloads
            )
            recover_output = tmp_path / "restored"
            self._run_cli_command(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    "restore",
                    "--payloads-file",
                    scenario_root / "main_payloads.txt",
                    "--recovery-payloads-file",
                    followup_shard_payloads,
                    "--output",
                    recover_output,
                    "--yes",
                ),
                env=env,
            )
            self._assert_recovered_hashes(
                recover_output,
                cast(dict[str, str], snapshot["expected_file_sha256"]),
            )

    def _verify_replacement_signing_key_replacement_shards_allow_followup_replacement(
        self,
    ) -> None:
        scenario_id = "sharded_signing_sharded"
        snapshot = self._snapshot({"path": f"{scenario_id}/snapshot.json"})
        scenario_root = self._profile_root() / scenario_id
        replacement_case = next(
            case
            for case in replacement_cases_for_scenario(scenario_id)
            if case.case_id == "external_signing_only"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            first_output = self._prepared_replacement_output(scenario_id, replacement_case)

            provided_signing_payloads = tmp_path / "provided_signing_payloads.txt"
            provided_signing_shards = sorted(first_output.glob("signing-key-shard-*.pdf"))[
                : self._required_int(replacement_case.signing_key_shard_threshold)
            ]
            self._write_scanned_payloads(provided_signing_shards, provided_signing_payloads)

            replacement_output = tmp_path / "replacement-signing-rotated"
            self._run_cli_command(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    "replace-recovery-docs",
                    "--payloads-file",
                    scenario_root / "main_payloads.txt",
                    "--recovery-payloads-file",
                    scenario_root / "shard_payloads_threshold.txt",
                    "--signing-key-payloads-file",
                    provided_signing_payloads,
                    "--signing-key-replacement-count",
                    "1",
                    "--no-passphrase-recovery",
                    "--output-dir",
                    replacement_output,
                    "--yes",
                ),
                env=env,
            )

            replacement_signing_shards = sorted(replacement_output.glob("signing-key-shard-*.pdf"))
            self.assertEqual(len(replacement_signing_shards), 1)

            replacement_signing_payloads = tmp_path / "replacement_signing_payloads.txt"
            self._write_scanned_payloads(
                [provided_signing_shards[0], replacement_signing_shards[0]],
                replacement_signing_payloads,
            )

            followup_output = tmp_path / "followup-passphrase-replacement"
            self._run_cli_command(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    "replace-recovery-docs",
                    "--payloads-file",
                    scenario_root / "main_payloads.txt",
                    "--recovery-payloads-file",
                    scenario_root / "shard_payloads_threshold.txt",
                    "--signing-key-payloads-file",
                    replacement_signing_payloads,
                    "--recovery-threshold",
                    "2",
                    "--recovery-count",
                    "3",
                    "--output-dir",
                    followup_output,
                    "--yes",
                ),
                env=env,
            )

            followup_shard_payloads = tmp_path / "followup_shard_payloads.txt"
            self._write_scanned_payloads(
                sorted(followup_output.glob("shard-*.pdf"))[:2],
                followup_shard_payloads,
            )
            recover_output = tmp_path / "restored-from-replacement-sheets"
            self._run_cli_command(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    "restore",
                    "--payloads-file",
                    scenario_root / "main_payloads.txt",
                    "--recovery-payloads-file",
                    followup_shard_payloads,
                    "--output",
                    recover_output,
                    "--yes",
                ),
                env=env,
            )
            self._assert_recovered_hashes(
                recover_output,
                cast(dict[str, str], snapshot["expected_file_sha256"]),
            )

    def _verify_replacement_signing_key_replacement_shards_reject_exact_threshold_mixed_sets(
        self,
    ) -> None:
        self.assertTrue(self.INCLUDE_SHARD_SET_FIELDS)

        scenario_id = "sharded_signing_sharded"
        scenario_root = self._profile_root() / scenario_id
        replacement_case = next(
            case
            for case in replacement_cases_for_scenario(scenario_id)
            if case.case_id == "external_signing_only"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            first_output = tmp_path / "replacement-signing-first"
            second_output = tmp_path / "replacement-signing-second"
            self._run_cli_command(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    *self._replacement_args(replacement_case, scenario_root, first_output),
                ),
                env=env,
            )
            self._run_cli_command(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    *self._replacement_args(replacement_case, scenario_root, second_output),
                ),
                env=env,
            )

            first_signing_shards = sorted(first_output.glob("signing-key-shard-*.pdf"))
            second_signing_shards = sorted(second_output.glob("signing-key-shard-*.pdf"))
            self.assertGreaterEqual(len(first_signing_shards), 2)
            self.assertGreaterEqual(len(second_signing_shards), 2)

            first_shard_details = self._frame_shard_details(
                self._valid_scanned_frames([first_signing_shards[0]])[0]
            )
            second_shard_details = self._frame_shard_details(
                self._valid_scanned_frames([second_signing_shards[0]])[0]
            )
            self.assertEqual(len(cast(str, first_shard_details["set_id"])), 32)
            self.assertEqual(len(cast(str, second_shard_details["set_id"])), 32)
            self.assertNotEqual(first_shard_details["set_id"], second_shard_details["set_id"])

            mixed_signing_payloads = tmp_path / "mixed_signing_payloads.txt"
            self._write_scanned_payloads(
                [first_signing_shards[0], second_signing_shards[1]],
                mixed_signing_payloads,
            )
            replacement_output = tmp_path / "rejected-signing-replacement"
            result = _run_cli_subprocess(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    "replace-recovery-docs",
                    "--payloads-file",
                    scenario_root / "main_payloads.txt",
                    "--recovery-payloads-file",
                    scenario_root / "shard_payloads_threshold.txt",
                    "--signing-key-payloads-file",
                    mixed_signing_payloads,
                    "--signing-key-replacement-count",
                    "1",
                    "--no-passphrase-recovery",
                    "--output-dir",
                    replacement_output,
                    "--yes",
                ),
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

    def _verify_replacement_shards_reject_exact_threshold_mixed_sets(self) -> None:
        self.assertTrue(self.INCLUDE_SHARD_SET_FIELDS)

        scenario_id = "sharded_embedded"
        scenario_root = self._profile_root() / scenario_id
        replacement_case = next(
            case
            for case in replacement_cases_for_scenario(scenario_id)
            if case.case_id == "embedded_from_passphrase_shards_both"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
            first_output = tmp_path / "replacement-first"
            second_output = tmp_path / "replacement-second"
            self._run_cli_command(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    *self._replacement_args(replacement_case, scenario_root, first_output),
                ),
                env=env,
            )
            self._run_cli_command(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    *self._replacement_args(replacement_case, scenario_root, second_output),
                ),
                env=env,
            )

            first_shards = sorted(first_output.glob("shard-*.pdf"))
            second_shards = sorted(second_output.glob("shard-*.pdf"))
            self.assertGreaterEqual(len(first_shards), 2)
            self.assertGreaterEqual(len(second_shards), 2)

            first_shard_details = self._frame_shard_details(
                self._valid_scanned_frames([first_shards[0]])[0]
            )
            second_shard_details = self._frame_shard_details(
                self._valid_scanned_frames([second_shards[0]])[0]
            )
            self.assertEqual(len(cast(str, first_shard_details["set_id"])), 32)
            self.assertEqual(len(cast(str, second_shard_details["set_id"])), 32)
            self.assertNotEqual(first_shard_details["set_id"], second_shard_details["set_id"])

            mixed_payloads = tmp_path / "mixed_shard_payloads.txt"
            self._write_scanned_payloads([first_shards[0], second_shards[1]], mixed_payloads)
            recover_output = tmp_path / "rejected-restore"
            result = _run_cli_subprocess(
                self._run_task_args(
                    self._profile_config_path(tmp_path),
                    "restore",
                    "--payloads-file",
                    scenario_root / "main_payloads.txt",
                    "--recovery-payloads-file",
                    mixed_payloads,
                    "--output",
                    recover_output,
                    "--yes",
                ),
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

    def _replacement_args(
        self, case: ReplacementFrozenCase, scenario_root: Path, output_dir: Path
    ) -> list[str]:
        args = replacement_cli_args(case, scenario_root, self._passphrase)
        output_index = args.index("--output-dir") + 1
        args[output_index] = str(output_dir)
        return args

    def _replacement_cases_under_test(
        self,
        scenario_id: str,
    ) -> tuple[ReplacementFrozenCase, ...]:
        cases = replacement_cases_for_scenario(scenario_id)
        if self.PROFILE_NAME == "raw":
            return cases
        if scenario_id == "sharded_embedded":
            return cases
        return ()

    def _prepared_replacement_output(
        self,
        scenario_id: str,
        case: ReplacementFrozenCase,
    ) -> Path:
        key = (scenario_id, case.case_id)
        prepared = self._prepared_replacements.get(key)
        if prepared is not None:
            return prepared

        workspace = self._prepared_output_root / scenario_id / case.case_id
        workspace.mkdir(parents=True)
        output_dir = workspace / "replacement"
        scenario_root = self._profile_root() / scenario_id
        env = build_cli_env(overrides={"XDG_CONFIG_HOME": str(workspace / "xdg")})
        self._run_cli_command(
            self._run_task_args(
                self._profile_config_path(workspace),
                *self._replacement_args(case, scenario_root, output_dir),
            ),
            env=env,
        )
        self._prepared_replacements[key] = output_dir
        return output_dir

    def _scenarios(self) -> list[dict[str, object]]:
        return list(self._index["scenarios"])

    def _snapshot(self, scenario: dict[str, object]) -> dict[str, object]:
        snapshot_path = self._profile_root() / str(scenario["path"])
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    def _replacement_snapshot(self, scenario_id: str) -> dict[str, object] | None:
        snapshot_path = self._profile_root() / scenario_id / REPLACEMENT_SNAPSHOT_FILENAME
        if not snapshot_path.exists():
            return None
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    def _run_cli_command(self, cmd: list[str], *, env: dict[str, str]) -> None:
        result = _run_cli_subprocess(
            cmd,
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr.strip() or result.stdout.strip())

    @staticmethod
    def _run_task_args(config_path: Path, *args: object) -> list[str]:
        return [
            sys.executable,
            "-m",
            "ethernity",
            "run",
            "--config",
            str(config_path),
            *[str(arg) for arg in args],
        ]

    def _assert_replacement_hashes(self, output_dir: Path, snapshot: dict[str, Any]) -> None:
        expected_shard_details = cast(
            dict[str, list[dict[str, Any]]], snapshot["shard_projections"]
        )
        actual_shard_details = self._shard_details_by_file(
            sorted(output_dir.glob("*.pdf")),
            qr_payload_codec=self.QR_PAYLOAD_CODEC,
        )
        self.assertEqual(actual_shard_details, expected_shard_details)
        self.assertEqual(
            len(list(output_dir.glob("shard-*.pdf"))), int(snapshot["expected_shard_pdfs"])
        )
        self.assertEqual(
            len(list(output_dir.glob("signing-key-shard-*.pdf"))),
            int(snapshot["expected_signing_key_shard_pdfs"]),
        )

    def _write_scanned_payloads(self, pdf_paths: list[Path], destination: Path) -> None:
        payloads = self._scanned_payloads(pdf_paths)
        normalized: list[str] = []
        for payload in payloads:
            try:
                frame = self._decode_scanned_frame(
                    payload,
                    qr_payload_codec=self.QR_PAYLOAD_CODEC,
                )
            except ValueError:
                continue
            encoded = encode_qr_payload(encode_frame(frame), codec=QR_PAYLOAD_CODEC_BASE64)
            normalized.append(encoded.decode("ascii") if isinstance(encoded, bytes) else encoded)
        destination.write_text("\n".join(normalized), encoding="utf-8")

    def _shard_details_by_file(
        self,
        pdf_paths: list[Path],
        *,
        qr_payload_codec: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        shard_set_labels: dict[str, str] = {}
        shard_records_by_file: dict[str, list[dict[str, Any]]] = {}
        for pdf_path in pdf_paths:
            shard_records: list[dict[str, Any]] = []
            for frame in self._valid_scanned_frames(
                [pdf_path],
                qr_payload_codec=qr_payload_codec,
            ):
                shard_record = self._normalize_shard_details(
                    self._frame_shard_details(frame),
                    shard_set_labels=shard_set_labels,
                )
                if shard_record not in shard_records:
                    shard_records.append(shard_record)
            shard_records_by_file[pdf_path.name] = shard_records
        return shard_records_by_file

    def _normalize_shard_details(
        self,
        details: dict[str, Any],
        *,
        shard_set_labels: dict[str, str],
    ) -> dict[str, Any]:
        normalized = dict(details)
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

    def _valid_scanned_frames(
        self,
        pdf_paths: list[Path],
        *,
        qr_payload_codec: str | None = None,
    ) -> list[Any]:
        payloads = self._scanned_payloads(pdf_paths)
        frames = []
        for payload in payloads:
            try:
                frame = self._decode_scanned_frame(payload, qr_payload_codec=qr_payload_codec)
            except ValueError:
                continue
            frames.append(frame)
        return frames

    @staticmethod
    def _decode_scanned_frame(
        payload: bytes | str,
        *,
        qr_payload_codec: str | None = None,
    ) -> Any:
        if qr_payload_codec == "base64":
            return decode_frame(decode_qr_payload(payload))
        if qr_payload_codec == "raw":
            if isinstance(payload, str):
                raise ValueError("raw QR payload must decode to bytes")
            return decode_frame(payload)
        if isinstance(payload, bytes):
            try:
                return decode_frame(payload)
            except ValueError:
                pass
        return decode_frame(decode_qr_payload(payload))

    def _scanned_payloads(self, pdf_paths: list[Path]) -> list[bytes | str]:
        payloads: list[bytes | str] = []
        for path in pdf_paths:
            resolved = path.resolve()
            payloads.extend(_scan_unchanged_pdf(str(resolved), self._sha256_file(resolved)))
        return payloads

    def _frame_shard_details(self, frame: Any) -> dict[str, Any]:
        payload = decode_shard_payload(frame.data)
        details: dict[str, Any] = {
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
            details["version"] = payload.version
            details["set_id"] = None if payload.shard_set_id is None else payload.shard_set_id.hex()
        return details

    def _assert_shard_binary_fixture_matches_snapshot(
        self,
        binary_path: Path,
        text_path: Path,
        pdf_paths: list[Path],
        *,
        expected_version: int,
        expected_shard_details: dict[str, list[dict[str, Any]]] | None,
        shard_set_labels: dict[str, str],
    ) -> None:
        if not binary_path.exists():
            self.assertFalse(text_path.exists())
            self.assertEqual(pdf_paths, [])
            return
        payloads = self._read_binary_payload_file(binary_path)
        text_payloads = [
            decode_qr_payload(line)
            for line in text_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(payloads, text_payloads)
        frames = [decode_frame(payload) for payload in payloads]
        self.assertGreaterEqual(len(frames), 1, msg=f"missing shard payloads in {binary_path}")
        self._assert_shard_frame_versions(frames, expected_version=expected_version)
        expected_pdf_paths = pdf_paths[: len(frames)]
        self.assertEqual(len(expected_pdf_paths), len(frames))
        if expected_shard_details is not None:
            self.assertEqual(
                self._shard_details_from_frames(
                    frames,
                    shard_set_labels=shard_set_labels,
                ),
                [expected_shard_details[path.name][0] for path in expected_pdf_paths],
            )

    def _assert_shard_frame_versions(self, frames: list[Any], *, expected_version: int) -> None:
        for frame in frames:
            payload = decode_shard_payload(frame.data)
            self.assertEqual(payload.version, expected_version)
            if self.INCLUDE_SHARD_SET_FIELDS:
                self.assertIsNotNone(payload.shard_set_id)
            else:
                self.assertIsNone(payload.shard_set_id)

    def _shard_details_from_frames(
        self,
        frames: list[Any],
        *,
        shard_set_labels: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        labels = {} if shard_set_labels is None else shard_set_labels
        return [
            self._normalize_shard_details(
                self._frame_shard_details(frame),
                shard_set_labels=labels,
            )
            for frame in frames
        ]

    @staticmethod
    def _required_int(value: int | None) -> int:
        if value is None:
            raise AssertionError("expected integer value")
        return value

    def _profile_config_path(self, workspace: Path) -> Path:
        base = _CONFIG_PATH.read_text(encoding="utf-8")
        config_text = base.replace(
            '\nqr_payload_codec = "raw" # required: raw | base64',
            f'\nqr_payload_codec = "{self.QR_PAYLOAD_CODEC}" # required: raw | base64',
            1,
        )
        configured_codec = tomllib.loads(config_text)["defaults"]["backup"]["qr_payload_codec"]
        if configured_codec != self.QR_PAYLOAD_CODEC:
            raise AssertionError(f"failed to configure QR payload codec: {self.QR_PAYLOAD_CODEC}")
        path = workspace / f"config_{self.PROFILE_NAME}.toml"
        path.write_text(config_text, encoding="utf-8")
        return path

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
