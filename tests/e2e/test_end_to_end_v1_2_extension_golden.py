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
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from tooling.document_inspector_app import MODE_PAYLOADS, inspect_pasted_text

from ethernity.crypto.sharding import KEY_TYPE_PASSPHRASE, decode_shard_payload
from ethernity.crypto.signing import AuthPayload, decode_auth_payload, encode_auth_payload
from ethernity.encoding.framing import VERSION, Frame, FrameType, decode_frame, encode_frame
from ethernity.encoding.qr_payloads import decode_qr_payload, encode_qr_payload
from ethernity.qr.scan import scan_qr_payloads
from tests.test_support import build_cli_env, cli_subprocess_timeout_seconds

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_ROOT = _REPO_ROOT / "tests" / "fixtures" / "v1_2" / "extension_golden"
_BINARY_PAYLOADS_MAGIC = b"EQPB"
_BINARY_PAYLOADS_VERSION = 1


def _run_cli_subprocess(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    kwargs.setdefault("timeout", cli_subprocess_timeout_seconds())
    return subprocess.run(*args, **kwargs)


class TestStableV1_2ExtensionGolden(unittest.TestCase):
    def test_fixture_index_describes_frozen_compatibility_matrix(self) -> None:
        index = json.loads((_FIXTURE_ROOT / "index.json").read_text(encoding="utf-8"))
        self.assertNotIn("builder_sha256", index)
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

    def test_frozen_artifact_hashes_match_snapshots(self) -> None:
        for scenario_root, snapshot in self._snapshots():
            with self.subTest(scenario=str(snapshot["scenario_id"]), profile=snapshot["profile"]):
                hashes = cast(dict[str, str], snapshot["artifact_hashes"])
                for rel_path, expected_hash in hashes.items():
                    artifact = scenario_root / rel_path
                    self.assertTrue(artifact.exists(), msg=f"missing fixture artifact: {artifact}")
                    self.assertEqual(self._sha256_file(artifact), expected_hash)

    def test_default_payload_recovery_selects_latest_state(self) -> None:
        for scenario_root, snapshot in self._snapshots():
            with self.subTest(scenario=str(snapshot["scenario_id"]), profile=snapshot["profile"]):
                self._assert_recover_payload_state(
                    scenario_root,
                    snapshot,
                    state_key=self._latest_state_key(snapshot),
                )

    def test_binary_payload_fixtures_match_text_frames(self) -> None:
        for scenario_root, snapshot in self._snapshots():
            for group_name in ("payload_fixtures", "shard_fixtures"):
                for fixture_name, fixture in cast(dict[str, Any], snapshot[group_name]).items():
                    with self.subTest(
                        scenario=str(snapshot["scenario_id"]),
                        profile=snapshot["profile"],
                        group=group_name,
                        fixture=fixture_name,
                    ):
                        self._assert_binary_payload_fixture_matches_text(
                            scenario_root,
                            cast(dict[str, str], fixture),
                        )

    def test_payload_recovery_selects_root_prior_and_doc_hash_heads(self) -> None:
        for scenario_root, snapshot in self._snapshots():
            if snapshot["scenario_id"] == "loose_scan_append_chain":
                continue
            states = cast(dict[str, dict[str, str]], snapshot["states"])
            with self.subTest(
                scenario=str(snapshot["scenario_id"]),
                profile=snapshot["profile"],
                selection="root",
            ):
                self._assert_recover_payload_state(
                    scenario_root,
                    snapshot,
                    state_key="root",
                    selector_args=["--extension-index", "0"],
                )
            if "extension_01" in states:
                with self.subTest(
                    scenario=str(snapshot["scenario_id"]),
                    profile=snapshot["profile"],
                    selection="index-1",
                ):
                    self._assert_recover_payload_state(
                        scenario_root,
                        snapshot,
                        state_key="extension_01",
                        selector_args=["--extension-index", "1"],
                    )
            latest_key = self._latest_state_key(snapshot)
            if latest_key != "root":
                latest_hash = cast(dict[str, str], snapshot["extension_doc_hashes"])[latest_key]
                with self.subTest(
                    scenario=str(snapshot["scenario_id"]),
                    profile=snapshot["profile"],
                    selection="doc-hash",
                ):
                    self._assert_recover_payload_state(
                        scenario_root,
                        snapshot,
                        state_key=latest_key,
                        selector_args=["--extension-doc-hash", latest_hash],
                    )

    def test_restore_json_preview_accepts_payload_recovery_inputs(self) -> None:
        for scenario_root, snapshot in self._snapshots():
            with self.subTest(scenario=str(snapshot["scenario_id"]), profile=snapshot["profile"]):
                with tempfile.TemporaryDirectory() as tmpdir:
                    result = self._run(
                        self._run_task_args(
                            "restore",
                            "--payloads-file",
                            scenario_root / snapshot["payload_fixtures"]["chain"]["text"],
                            "--output",
                            Path(tmpdir) / "recovered",
                            "--preview",
                            "--json",
                            *self._unlock_args(scenario_root, snapshot, state_key=None),
                        )
                    )
                self.assertEqual(
                    result.returncode,
                    0,
                    msg=result.stderr.strip() or result.stdout.strip(),
                )
                payload = json.loads(result.stdout)
                self.assertEqual(payload["task"], "restore")
                self.assertEqual(payload["status"], "preview")
                self.assertTrue(payload["ready"])

    def test_document_inspector_trusts_complete_chain_and_refuses_extension_only(self) -> None:
        scenario_root = _FIXTURE_ROOT / "base64" / "large_raw_two_extension_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        chain_payloads = self._payload_text(scenario_root, snapshot, "chain")
        chain_result = inspect_pasted_text(
            chain_payloads,
            selected_mode=MODE_PAYLOADS,
            passphrase=str(snapshot["passphrase"]),
            source_label="v1.2 extension golden chain",
        )
        self.assertIsNotNone(chain_result.trust_diagnostic)
        self.assertEqual(chain_result.trust_diagnostic.status, "ok")
        report = json.loads(chain_result.report_json)
        self.assertEqual(report["document"]["kind"], "extension_chain")

        extension_payloads = self._payload_text(scenario_root, snapshot, "extension_01")
        extension_result = inspect_pasted_text(
            extension_payloads,
            selected_mode=MODE_PAYLOADS,
            passphrase=str(snapshot["passphrase"]),
            source_label="v1.2 extension-only golden payloads",
        )
        self.assertIsNotNone(extension_result.trust_diagnostic)
        self.assertEqual(extension_result.trust_diagnostic.status, "refused")

    def test_restore_refuses_extension_only_payloads_as_untrusted(self) -> None:
        scenario_root = _FIXTURE_ROOT / "base64" / "large_raw_two_extension_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        result = self._run(
            self._run_task_args(
                "restore",
                "--payloads-file",
                scenario_root / snapshot["payload_fixtures"]["extension_01"]["text"],
                "--passphrase",
                str(snapshot["passphrase"]),
                "--output",
                tempfile.gettempdir(),
                "--yes",
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("root backup", result.stderr or result.stdout)

    def test_golden_auth_mutations_fail_closed(self) -> None:
        scenario_root = _FIXTURE_ROOT / "base64" / "gzip_replacement_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        root_doc_id = self._projection_doc_id(snapshot, kind="root")
        extension_doc_id = self._projection_doc_id(snapshot, kind="extension", index=1)
        frames = self._payload_frames(scenario_root / snapshot["payload_fixtures"]["chain"]["text"])
        cases = (
            (
                "bad-root-auth",
                self._mutated_auth_frames(
                    frames,
                    doc_id_hex=root_doc_id,
                    mutate=lambda auth: self._auth_with_bad_signature(auth),
                ),
                ["--extension-index", "0"],
                "invalid auth signature",
            ),
            (
                "bad-extension-auth-key",
                self._mutated_auth_frames(
                    frames,
                    doc_id_hex=extension_doc_id,
                    mutate=lambda auth: self._auth_with_bad_sign_pub(auth),
                ),
                [],
                "imported extension AUTH could not be verified: invalid auth signature",
            ),
            (
                "duplicate-extension-auth-conflict",
                self._with_duplicate_mutated_auth(
                    frames,
                    doc_id_hex=extension_doc_id,
                    mutate=lambda auth: self._auth_with_bad_signature(auth),
                ),
                [],
                "conflicting duplicate frames detected",
            ),
        )
        for name, mutated_frames, selector_args, expected_error in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    payloads = Path(tmpdir) / "payloads.txt"
                    output = Path(tmpdir) / "recovered"
                    self._write_payload_frames(payloads, mutated_frames)
                    cmd = self._run_task_args(
                        "restore",
                        "--payloads-file",
                        payloads,
                        "--passphrase",
                        str(snapshot["passphrase"]),
                        "--output",
                        output,
                        "--yes",
                        *selector_args,
                    )
                    result = self._run(cmd)
                    self.assertNotEqual(
                        result.returncode,
                        0,
                        msg=f"{name} unexpectedly recovered successfully",
                    )
                    self.assertIn(expected_error, result.stderr or result.stdout)

    def test_golden_main_document_mutations_fail_closed(self) -> None:
        scenario_root = _FIXTURE_ROOT / "base64" / "gzip_replacement_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        root_doc_id = self._projection_doc_id(snapshot, kind="root")
        extension_doc_id = self._projection_doc_id(snapshot, kind="extension", index=1)
        frames = self._payload_frames(scenario_root / snapshot["payload_fixtures"]["chain"]["text"])
        cases = (
            ("bad-root-main", root_doc_id, ["--extension-index", "0"]),
            ("bad-extension-main", extension_doc_id, []),
        )
        for name, doc_id, selector_args in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    payloads = Path(tmpdir) / "payloads.txt"
                    output = Path(tmpdir) / "recovered"
                    self._write_payload_frames(
                        payloads,
                        self._mutated_main_frames(frames, doc_id_hex=doc_id),
                    )
                    cmd = self._run_task_args(
                        "restore",
                        "--payloads-file",
                        payloads,
                        "--passphrase",
                        str(snapshot["passphrase"]),
                        "--output",
                        output,
                        "--yes",
                        *selector_args,
                    )
                    result = self._run(cmd)
                    self.assertNotEqual(
                        result.returncode,
                        0,
                        msg=f"{name} unexpectedly recovered successfully",
                    )
                    self.assertIn(
                        "doc_id does not match recovered ciphertext",
                        result.stderr or result.stdout,
                    )

    def test_duplicate_extension_index_with_different_doc_hash_fails(self) -> None:
        scenario_root = _FIXTURE_ROOT / "base64" / "gzip_replacement_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            root_source = tmp_path / "root-source"
            root_chain = tmp_path / "root-chain"
            recover_root = self._run_task_args(
                "restore",
                "--payloads-file",
                scenario_root / snapshot["payload_fixtures"]["root"]["text"],
                "--passphrase",
                str(snapshot["passphrase"]),
                "--extension-index",
                "0",
                "--output",
                root_source,
                "--yes",
            )
            self._run_ok(recover_root)
            shutil.copytree(scenario_root / str(snapshot["chain_dir"]), root_chain)
            shutil.rmtree(root_chain / "extensions")
            (root_source / "duplicate-index.txt").write_text(
                "different extension index 1\n",
                encoding="utf-8",
            )
            create_duplicate = self._run_task_args(
                "add-files",
                "--backup-folder",
                root_chain,
                "--input-dir",
                root_source,
                "--base-dir",
                root_source,
                "--passphrase",
                str(snapshot["passphrase"]),
                "--design",
                "forge",
                "--recovery-count",
                "0",
                "--yes",
            )
            self._run_ok(create_duplicate)
            original_ext = next(
                (scenario_root / str(snapshot["chain_dir"]) / "extensions" / "01").glob(
                    "qr_document-*.pdf"
                )
            )
            duplicate_ext = next((root_chain / "extensions" / "01").glob("qr_document-*.pdf"))
            recover = self._run_task_args(
                "restore",
                "--scan",
                root_chain / "qr_document.pdf",
                "--scan",
                original_ext,
                "--scan",
                duplicate_ext,
                "--passphrase",
                str(snapshot["passphrase"]),
                "--output",
                tmp_path / "recovered",
                "--yes",
            )
            result = self._run(recover)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "multiple authenticated extensions for index 1",
                result.stderr or result.stdout,
            )

    def test_base64_canonical_pdf_scan_recovers_latest_state(self) -> None:
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
                cast(dict[str, Any], snapshot["states"])["extension_01"],
            )

    def test_loose_scan_fixture_recovers_latest_without_canonical_layout(self) -> None:
        scenario_root = _FIXTURE_ROOT / "raw" / "loose_scan_append_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        chain_dir = scenario_root / str(snapshot["chain_dir"])
        self.assertFalse((chain_dir / "qr_document.pdf").exists())
        self.assertFalse((chain_dir / "extensions").exists())
        cases = (
            ("latest", "extension_02", []),
            ("root", "root", ["--extension-index", "0"]),
            ("index-1", "extension_01", ["--extension-index", "1"]),
            (
                "doc-hash",
                "extension_02",
                [
                    "--extension-doc-hash",
                    cast(dict[str, str], snapshot["extension_doc_hashes"])["extension_02"],
                ],
            ),
        )
        for name, state_key, selector_args in cases:
            with self.subTest(selection=name):
                self._assert_recover_scan_state(
                    scenario_root,
                    snapshot,
                    state_key=state_key,
                    selector_args=selector_args,
                )

    def test_stale_expected_head_hash_fails_before_recovery(self) -> None:
        scenario_root = _FIXTURE_ROOT / "base64" / "large_raw_two_extension_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recovered"
            cmd = self._recover_payload_cmd(scenario_root, snapshot, output)
            cmd.extend(["--expected-head", str(snapshot["root_doc_hash"])])
            result = self._run(cmd)
            self.assertNotEqual(result.returncode, 0)
            normalized_error = " ".join((result.stderr or result.stdout).lower().split())
            self.assertIn("recovery head doc_hash does not match expected head", normalized_error)

    def test_missing_latest_canonical_carrier_fails_default_but_prior_selection_recovers(
        self,
    ) -> None:
        scenario_root = _FIXTURE_ROOT / "raw" / "large_raw_two_extension_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            copied = tmp_path / "chain"
            shutil.copytree(scenario_root / str(snapshot["chain_dir"]), copied)
            latest_qr = next((copied / "extensions" / "02").glob("qr_document-*.pdf"))
            latest_qr.unlink()

            default_output = tmp_path / "default"
            default = self._run(
                self._run_task_args(
                    "restore",
                    "--scan",
                    copied,
                    "--passphrase",
                    str(snapshot["passphrase"]),
                    "--output",
                    default_output,
                    "--yes",
                )
            )
            self.assertNotEqual(default.returncode, 0)
            normalized_error = " ".join(default.stderr.lower().split())
            self.assertIn("missing its qr document carrier", normalized_error)

            prior_output = tmp_path / "prior"
            prior = self._run(
                self._run_task_args(
                    "restore",
                    "--scan",
                    copied,
                    "--passphrase",
                    str(snapshot["passphrase"]),
                    "--extension-index",
                    "1",
                    "--output",
                    prior_output,
                    "--yes",
                )
            )
            self.assertEqual(prior.returncode, 0, msg=prior.stderr.strip() or prior.stdout.strip())
            self._assert_output_hashes(
                prior_output,
                cast(dict[str, Any], snapshot["states"])["extension_01"],
            )

            compact = self._run(
                self._run_task_args(
                    "rebuild",
                    "--backup-folder",
                    copied,
                    "--passphrase",
                    str(snapshot["passphrase"]),
                    "--output-dir",
                    tmp_path / "compacted",
                    "--yes",
                )
            )
            self.assertNotEqual(compact.returncode, 0)
            compact_error = " ".join(compact.stderr.lower().split())
            self.assertIn("missing its qr document carrier", compact_error)

    def test_mint_from_frozen_extension_head_creates_recoverable_extension_bound_shards(
        self,
    ) -> None:
        scenario_root = _FIXTURE_ROOT / "raw" / "large_raw_two_extension_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        latest_hash = cast(dict[str, str], snapshot["extension_doc_hashes"])["extension_02"]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            mint_dir = tmp_path / "minted"
            mint = self._run_task_args(
                "replace-recovery-docs",
                "--scan",
                scenario_root / str(snapshot["chain_dir"]),
                "--passphrase",
                str(snapshot["passphrase"]),
                "--expected-head",
                latest_hash,
                "--output-dir",
                mint_dir,
                "--recovery-threshold",
                "2",
                "--recovery-count",
                "3",
                "--yes",
            )
            self._run_ok(mint)
            minted_shards = sorted(mint_dir.glob("shard-*.pdf"))
            self.assertEqual(len(minted_shards), 3)
            self.assertEqual(
                self._passphrase_shard_doc_hashes(minted_shards),
                {latest_hash},
            )

            output = tmp_path / "recovered"
            recover = self._run_task_args(
                "restore",
                "--scan",
                scenario_root / str(snapshot["chain_dir"]),
                "--output",
                output,
                "--yes",
            )
            for shard_path in minted_shards[:2]:
                recover.extend(["--recovery-document", str(shard_path)])
            self._run_ok(recover)
            self._assert_output_hashes(
                output,
                cast(dict[str, Any], snapshot["states"])["extension_02"],
            )

    def test_compact_from_frozen_extension_head_preserves_latest_state_and_shard_policy(
        self,
    ) -> None:
        scenario_root = _FIXTURE_ROOT / "raw" / "extension_local_sharded_chain"
        snapshot = self._snapshot_at(scenario_root / "snapshot.json")
        shard_text = snapshot["shard_fixtures"]["extension"]["text"]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            compacted = tmp_path / "compacted"
            compact = self._run_task_args(
                "rebuild",
                "--backup-folder",
                scenario_root / str(snapshot["chain_dir"]),
                "--recovery-payloads-file",
                scenario_root / shard_text,
                "--output-dir",
                compacted,
                "--yes",
            )
            self._run_ok(compact)
            compacted_shards = sorted(compacted.glob("shard-*.pdf"))
            self.assertEqual(len(compacted_shards), 3)

            output = tmp_path / "recovered"
            recover = self._run_task_args(
                "restore",
                "--scan",
                compacted,
                "--output",
                output,
                "--yes",
            )
            for shard_path in compacted_shards[:2]:
                recover.extend(["--recovery-document", str(shard_path)])
            self._run_ok(recover)
            self._assert_output_hashes(
                output,
                cast(dict[str, Any], snapshot["states"])["extension_01"],
            )

    def test_shard_policy_fixtures_are_extension_bound_or_root_reused(self) -> None:
        extension_snapshot = self._snapshot_at(
            _FIXTURE_ROOT / "raw" / "extension_local_sharded_chain" / "snapshot.json"
        )
        extension_shards = extension_snapshot["shard_fixtures"]["extension"]["projection"]
        extension_hash = extension_snapshot["extension_doc_hashes"]["extension_01"]
        self.assertEqual(
            {
                row["doc_hash"]
                for rows in extension_shards.values()
                for row in rows
                if row["key_type"] == "passphrase"
            },
            {extension_hash},
        )

        reuse_snapshot = self._snapshot_at(
            _FIXTURE_ROOT / "raw" / "reuse_root_shards_chain" / "snapshot.json"
        )
        self.assertNotIn("extension", reuse_snapshot["shard_fixtures"])
        root_shards = reuse_snapshot["shard_fixtures"]["root"]["projection"]
        self.assertEqual(
            {row["doc_hash"] for rows in root_shards.values() for row in rows},
            {reuse_snapshot["root_doc_hash"]},
        )

    def _assert_recover_payload_state(
        self,
        scenario_root: Path,
        snapshot: dict[str, Any],
        *,
        state_key: str,
        selector_args: list[str] | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recovered"
            cmd = self._recover_payload_cmd(
                scenario_root,
                snapshot,
                output,
                state_key=state_key,
            )
            if selector_args:
                cmd.extend(selector_args)
            self._run_ok(cmd)
            self._assert_output_hashes(output, cast(dict[str, Any], snapshot["states"])[state_key])

    def _assert_recover_scan_state(
        self,
        scenario_root: Path,
        snapshot: dict[str, Any],
        *,
        state_key: str,
        selector_args: list[str] | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "recovered"
            cmd = self._run_task_args(
                "restore",
                "--output",
                output,
                "--yes",
            )
            for rel_path in cast(list[str], snapshot["scan_paths"]):
                cmd.extend(["--scan", str(scenario_root / rel_path)])
            cmd.extend(self._unlock_args(scenario_root, snapshot, state_key=state_key))
            if selector_args:
                cmd.extend(selector_args)
            self._run_ok(cmd)
            self._assert_output_hashes(output, cast(dict[str, Any], snapshot["states"])[state_key])

    def _recover_payload_cmd(
        self,
        scenario_root: Path,
        snapshot: dict[str, Any],
        output: Path,
        state_key: str | None = None,
    ) -> list[str]:
        cmd = self._run_task_args(
            "restore",
            "--payloads-file",
            scenario_root / snapshot["payload_fixtures"]["chain"]["text"],
            "--output",
            output,
            "--yes",
        )
        cmd.extend(self._unlock_args(scenario_root, snapshot, state_key=state_key))
        return cmd

    def _unlock_args(
        self,
        scenario_root: Path,
        snapshot: dict[str, Any],
        *,
        state_key: str | None,
    ) -> list[str]:
        shard_fixtures = cast(dict[str, Any], snapshot["shard_fixtures"])
        if state_key == "root":
            if "root" in shard_fixtures:
                return [
                    "--recovery-payloads-file",
                    str(scenario_root / shard_fixtures["root"]["text"]),
                ]
            return ["--passphrase", str(snapshot["passphrase"])]
        if "extension" in shard_fixtures:
            return [
                "--recovery-payloads-file",
                str(scenario_root / shard_fixtures["extension"]["text"]),
            ]
        if "root" in shard_fixtures:
            return [
                "--recovery-payloads-file",
                str(scenario_root / shard_fixtures["root"]["text"]),
            ]
        return ["--passphrase", str(snapshot["passphrase"])]

    def _payload_text(self, scenario_root: Path, snapshot: dict[str, Any], name: str) -> str:
        return (scenario_root / snapshot["payload_fixtures"][name]["text"]).read_text(
            encoding="utf-8"
        )

    def _snapshots(self) -> list[tuple[Path, dict[str, Any]]]:
        cases: list[tuple[Path, dict[str, Any]]] = []
        for index_path in sorted(_FIXTURE_ROOT.glob("*/index.json")):
            index = json.loads(index_path.read_text(encoding="utf-8"))
            profile_root = index_path.parent
            for scenario in index["scenarios"]:
                snapshot_path = profile_root / str(scenario["path"])
                cases.append((snapshot_path.parent, self._snapshot_at(snapshot_path)))
        return cases

    @staticmethod
    def _snapshot_at(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _latest_state_key(snapshot: dict[str, Any]) -> str:
        extensions = sorted(cast(dict[str, str], snapshot["extension_doc_hashes"]))
        return extensions[-1] if extensions else "root"

    def _run_ok(self, cmd: list[str]) -> None:
        result = self._run(cmd)
        self.assertEqual(result.returncode, 0, msg=result.stderr.strip() or result.stdout.strip())

    @staticmethod
    def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as xdg_home:
            env = build_cli_env(overrides={"XDG_CONFIG_HOME": xdg_home})
            return _run_cli_subprocess(
                cmd,
                cwd=_REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

    @staticmethod
    def _run_task_args(*args: object) -> list[str]:
        return [sys.executable, "-m", "ethernity", "run", *[str(arg) for arg in args]]

    def _assert_output_hashes(self, output: Path, expected_hashes: dict[str, str]) -> None:
        if output.is_file():
            self.assertEqual(len(expected_hashes), 1)
            only_path = next(iter(expected_hashes))
            self.assertEqual(self._sha256_file(output), expected_hashes[only_path])
            return

        self.assertTrue(output.is_dir(), msg=f"missing recovery output: {output}")
        found = {
            path.relative_to(output).as_posix(): self._sha256_file(path)
            for path in output.rglob("*")
            if path.is_file()
        }
        self.assertEqual(found, expected_hashes)

    def _payload_frames(self, path: Path) -> list[Frame]:
        return [
            decode_frame(decode_qr_payload(line.strip()))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

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

    def _write_payload_frames(self, path: Path, frames: list[Frame]) -> None:
        lines: list[str] = []
        for frame in frames:
            encoded = encode_qr_payload(encode_frame(frame))
            lines.append(encoded.decode("ascii") if isinstance(encoded, bytes) else encoded)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _mutated_auth_frames(
        self,
        frames: list[Frame],
        *,
        doc_id_hex: str,
        mutate: Any,
    ) -> list[Frame]:
        out: list[Frame] = []
        replaced = False
        for frame in frames:
            if frame.frame_type == FrameType.AUTH and frame.doc_id.hex() == doc_id_hex:
                out.append(self._mutated_auth_frame(frame, mutate))
                replaced = True
            else:
                out.append(frame)
        self.assertTrue(replaced, msg=f"missing AUTH frame for doc_id {doc_id_hex}")
        return out

    def _with_duplicate_mutated_auth(
        self,
        frames: list[Frame],
        *,
        doc_id_hex: str,
        mutate: Any,
    ) -> list[Frame]:
        for frame in frames:
            if frame.frame_type == FrameType.AUTH and frame.doc_id.hex() == doc_id_hex:
                return [*frames, self._mutated_auth_frame(frame, mutate)]
        self.fail(f"missing AUTH frame for doc_id {doc_id_hex}")

    def _mutated_main_frames(self, frames: list[Frame], *, doc_id_hex: str) -> list[Frame]:
        out: list[Frame] = []
        replaced = False
        for frame in frames:
            if (
                not replaced
                and frame.frame_type == FrameType.MAIN_DOCUMENT
                and frame.doc_id.hex() == doc_id_hex
            ):
                data = bytes([frame.data[0] ^ 1]) + frame.data[1:]
                out.append(
                    Frame(
                        version=VERSION,
                        frame_type=FrameType.MAIN_DOCUMENT,
                        doc_id=frame.doc_id,
                        index=frame.index,
                        total=frame.total,
                        data=data,
                    )
                )
                replaced = True
            else:
                out.append(frame)
        self.assertTrue(replaced, msg=f"missing MAIN frame for doc_id {doc_id_hex}")
        return out

    @staticmethod
    def _mutated_auth_frame(frame: Frame, mutate: Any) -> Frame:
        auth = decode_auth_payload(frame.data)
        return Frame(
            version=VERSION,
            frame_type=FrameType.AUTH,
            doc_id=frame.doc_id,
            index=frame.index,
            total=frame.total,
            data=mutate(auth),
        )

    @staticmethod
    def _auth_with_bad_signature(auth: AuthPayload) -> bytes:
        signature = bytes([auth.signature[0] ^ 1]) + auth.signature[1:]
        return encode_auth_payload(auth.doc_hash, sign_pub=auth.sign_pub, signature=signature)

    @staticmethod
    def _auth_with_bad_sign_pub(auth: AuthPayload) -> bytes:
        sign_pub = bytes([auth.sign_pub[0] ^ 1]) + auth.sign_pub[1:]
        return encode_auth_payload(auth.doc_hash, sign_pub=sign_pub, signature=auth.signature)

    @staticmethod
    def _projection_doc_id(
        snapshot: dict[str, Any],
        *,
        kind: str,
        index: int | None = None,
    ) -> str:
        for item in cast(list[dict[str, Any]], snapshot["document_projection"]):
            if item["kind"] != kind:
                continue
            if index is not None and item.get("index") != index:
                continue
            return str(item["doc_id"])
        raise AssertionError(f"missing {kind} projection")

    @staticmethod
    def _sha256_file(path: Path) -> str:
        hasher = hashlib.sha256()
        hasher.update(path.read_bytes())
        return hasher.hexdigest()

    def _passphrase_shard_doc_hashes(self, paths: list[Path]) -> set[str]:
        doc_hashes: set[str] = set()
        for encoded_payload in scan_qr_payloads([str(path) for path in paths]):
            try:
                frame = decode_frame(encoded_payload)
            except ValueError:
                frame = decode_frame(decode_qr_payload(encoded_payload))
            if frame.frame_type != FrameType.KEY_DOCUMENT:
                continue
            shard = decode_shard_payload(frame.data)
            if shard.key_type == KEY_TYPE_PASSPHRASE:
                doc_hashes.add(shard.doc_hash.hex())
        return doc_hashes
