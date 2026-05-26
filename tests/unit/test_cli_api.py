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

import io
import json
import os
import re
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import click
from jsonschema import validators
from jsonschema.exceptions import ValidationError
from typer.testing import CliRunner

from ethernity import cli
from ethernity.cli.features.api import command as api_command
from ethernity.cli.features.backup.api_handlers import run_backup_api_command
from ethernity.cli.features.compact.api_handlers import run_compact_api_command
from ethernity.cli.features.config.api_handlers import (
    run_config_get_api_command,
    run_config_set_api_command,
)
from ethernity.cli.features.extend import api_handlers as extend_api_handlers
from ethernity.cli.features.extend.api_handlers import (
    run_extend_api_command,
    run_extend_inspect_api_command,
)
from ethernity.cli.features.extend.models import (
    ExtensionPassphraseShards,
    ExtensionSigningKeyShards,
    PlaintextPassphrase,
    SigningKeyNotStored,
)
from ethernity.cli.features.extend.planning import (
    ExtendInspection,
    ResolvedExtendState,
    _RootRecoveryInspection,
)
from ethernity.cli.features.extend.service import (
    encrypt_prepared_extension_document,
    prepare_extend_run,
)
from ethernity.cli.features.mint.api_handlers import (
    run_mint_api_command,
    run_mint_inspect_api_command,
)
from ethernity.cli.features.recover.api_handlers import (
    run_recover_api_command,
    run_recover_inspect_api_command,
)
from ethernity.cli.features.recover.planning import RecoveryInspection, RecoveryUnlockStatus
from ethernity.cli.features.recover.service import (
    apply_recover_stdin_default,
    execute_recover_plan,
)
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.crypto import doc_id_and_hash_from_ciphertext
from ethernity.cli.shared.ndjson import ApiCommandError, ndjson_session
from ethernity.cli.shared.types import (
    BackupArgs,
    BackupResult,
    CliContextState,
    CompactArgs,
    ConfigGetArgs,
    ConfigSetArgs,
    ExtendArgs,
    InputFile,
    MintArgs,
    MintResult,
    RecoverArgs,
)
from ethernity.config import BackupDefaults, CliDefaults, RecoverDefaults, load_app_config
from ethernity.config.install import ONBOARDING_FIELDS
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.core.models import DocumentPlan, SigningSeedMode
from ethernity.crypto.signing import derive_public_key, encode_auth_payload, sign_auth
from ethernity.encoding.framing import Frame, FrameType
from ethernity.extensions import LogicalFileState
from ethernity.extensions.build import build_extension_document, default_extension_chunker
from ethernity.formats.envelope_codec import (
    build_manifest_and_payload,
    encode_envelope,
    encode_extension_envelope,
)
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile, PayloadPart
from ethernity.formats.extension_envelope import ExtensionChunkingProfile
from ethernity.formats.extension_envelope_constants import CHUNK_ALGORITHM_FASTCDC
from tests.unit.render_test_helpers import render_result_for_inputs


def _extend_root_inspection(
    *,
    passphrase: str | None = None,
    satisfied: bool = False,
) -> RecoveryInspection:
    return RecoveryInspection(
        ciphertext=b"ciphertext",
        doc_id=b"\x11" * 8,
        doc_hash=b"\x22" * 32,
        auth_payload=None,
        auth_status="verified",
        allow_unsigned=False,
        input_label="Backup root directory",
        input_detail="/tmp/root",
        main_frames=(),
        auth_frames=(),
        shard_frames=(),
        shard_fallback_files=(),
        shard_payloads_file=(),
        shard_scan=(),
        unlock=RecoveryUnlockStatus(
            mode="passphrase",
            passphrase_provided=passphrase is not None,
            validated_shard_count=0,
            required_shard_threshold=None,
            satisfied=satisfied,
            resolved_passphrase=passphrase,
            blocking_issues=(),
        ),
        blocking_issues=(),
    )


def _extend_root_recovery(
    *,
    passphrase: str | None = None,
    satisfied: bool = False,
) -> _RootRecoveryInspection:
    return _RootRecoveryInspection(
        _extend_root_inspection(passphrase=passphrase, satisfied=satisfied),
        "none",
    )


REPO_ROOT = Path(__file__).resolve().parents[2]
V1_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden" / "base64" / "file_no_shard"
V1_1_BASE64_ROOT = REPO_ROOT / "tests" / "fixtures" / "v1_1" / "golden" / "base64"
V1_1_RAW_ROOT = REPO_ROOT / "tests" / "fixtures" / "v1_1" / "golden" / "raw"
V1_1_SHARDED_EMBEDDED_FIXTURE_ROOT = V1_1_BASE64_ROOT / "sharded_embedded"
V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT = V1_1_RAW_ROOT / "sharded_signing_sharded"
CLI_API_SCHEMA_PATH = REPO_ROOT / "docs" / "cli_api.schema.json"
CLI_API_CONTRACTS_PATH = REPO_ROOT / "tests" / "fixtures" / "cli_api" / "contracts.json"
FIXTURE_PASSPHRASE = "stable-v1-baseline-passphrase"
FIXTURE_V1_1_PASSPHRASE = "stable-v1_1-golden-passphrase"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TEST_SIGNING_SEED = b"\x33" * 32


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _expected_host_path(path: str) -> str:
    return os.path.normpath(path)


def _main_frame(ciphertext: bytes) -> Frame:
    doc_id, _doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    return Frame(
        version=1,
        frame_type=FrameType.MAIN_DOCUMENT,
        doc_id=doc_id,
        index=0,
        total=1,
        data=ciphertext,
    )


def _auth_frame(ciphertext: bytes, *, signing_seed: bytes = TEST_SIGNING_SEED) -> Frame:
    doc_id, doc_hash = doc_id_and_hash_from_ciphertext(ciphertext)
    sign_pub = derive_public_key(signing_seed)
    return Frame(
        version=1,
        frame_type=FrameType.AUTH,
        doc_id=doc_id,
        index=0,
        total=1,
        data=encode_auth_payload(
            doc_hash,
            sign_pub=sign_pub,
            signature=sign_auth(doc_hash, sign_pub=sign_pub, sign_priv=signing_seed),
        ),
    )


def _root_envelope(data: bytes = b"root") -> bytes:
    manifest, payload = build_manifest_and_payload(
        (PayloadPart(path="a.txt", data=data, mtime=1),),
        sealed=False,
        signing_seed=TEST_SIGNING_SEED,
        input_origin="file",
        input_roots=(),
    )
    return encode_envelope(payload, manifest)


def _extension_envelope(root_doc_hash: bytes) -> bytes:
    built = build_extension_document(
        index=1,
        parent_doc_hash=root_doc_hash,
        root_doc_hash=root_doc_hash,
        chunking=ExtensionChunkingProfile(
            algorithm_id=CHUNK_ALGORITHM_FASTCDC,
            target_size=64 * 1024,
            min_size=16 * 1024,
            max_size=256 * 1024,
        ),
        input_files=(
            InputFile(
                source_path=None,
                relative_path="a.txt",
                data=b"root!",
                mtime=2,
            ),
        ),
        input_origin="file",
        input_roots=(),
        chunker=lambda data, _profile: (data,),
        existing_file_sizes={},
    )
    return encode_extension_envelope(built.document)


def _extend_selected_scope(
    *,
    files: list[str] | None = None,
    directories: list[str] | None = None,
    base_dir: str | None = None,
    file_count: int = 1,
    total_bytes: int = 1,
    input_origin: str | None = "file",
    input_roots: list[str] | None = None,
) -> dict[str, object]:
    return {
        "files": files or [],
        "directories": directories or [],
        "base_dir": base_dir,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "input_origin": input_origin,
        "input_roots": input_roots or [],
    }


def _extend_diff_summary(
    *,
    new_paths: list[str] | None = None,
    changed_paths: list[str] | None = None,
    unchanged_paths: list[str] | None = None,
    missing_paths: list[str] | None = None,
) -> dict[str, object]:
    new_path_values = new_paths or []
    changed_path_values = changed_paths or []
    unchanged_path_values = unchanged_paths or []
    missing_path_values = missing_paths or []
    return {
        "new_paths": new_path_values,
        "changed_paths": changed_path_values,
        "unchanged_paths": unchanged_path_values,
        "missing_paths": missing_path_values,
        "new_count": len(new_path_values),
        "changed_count": len(changed_path_values),
        "unchanged_count": len(unchanged_path_values),
        "missing_count": len(missing_path_values),
    }


def _resolved_extend_state(root_dir: Path) -> ResolvedExtendState:
    inspection = ExtendInspection(
        doc_id="0123456789abcdef",
        root_dir=str(root_dir),
        input_label="Backup root directory",
        input_detail=str(root_dir),
        input_kind="standalone_root",
        source_summary=None,
        frame_counts={"main": 0, "auth": 0, "shard": 0},
        root_doc_id="0123456789abcdef",
        root_doc_hash="22" * 32,
        chain_id="44" * 32,
        auth_status="verified",
        unlock={
            "mode": "passphrase",
            "passphrase_provided": True,
            "validated_shard_count": 0,
            "required_shard_threshold": None,
            "shard_share_count": None,
            "satisfied": True,
        },
        discovered_extension_dirs=(),
        validated_head_index=0,
        validated_head_doc_hash="22" * 32,
        available_extensions=(),
        ancestry_valid=True,
        validated_head_auth_status="verified",
        validated_head_root_authority_verified=True,
        signing_authority={
            "available": True,
            "satisfied": True,
            "source": "embedded_seed",
        },
        selected_scope=None,
        diff_summary=None,
        blocking_issues=(),
    )
    return ResolvedExtendState(
        inspection=inspection,
        loaded_scope=None,
        current_state=None,
        available_chunks=(),
        resolved_passphrase=None,
        root_doc_hash=None,
        parent_doc_hash=None,
        next_index=None,
        signing_seed=None,
        chunking=None,
    )


@lru_cache(maxsize=1)
def _schema_validator():
    schema = json.loads(CLI_API_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator_cls = validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls(schema)


@lru_cache(maxsize=1)
def _recover_manifest_validator():
    schema = json.loads(CLI_API_SCHEMA_PATH.read_text(encoding="utf-8"))
    recover_manifest_schema = schema["$defs"]["recoverManifest"]
    validator_cls = validators.validator_for(recover_manifest_schema)
    validator_cls.check_schema(recover_manifest_schema)
    return validator_cls(recover_manifest_schema)


@lru_cache(maxsize=1)
def _contracts() -> dict[str, object]:
    return json.loads(CLI_API_CONTRACTS_PATH.read_text(encoding="utf-8"))


class TestCliApi(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def _assert_valid_events(self, events: list[dict[str, Any]]) -> None:
        validator = _schema_validator()
        for event in events:
            try:
                validator.validate(event)
            except ValidationError as exc:  # pragma: no cover - assertion helper
                self.fail(f"Schema validation failed for {event!r}: {exc.message}")

    def test_cli_api_schema_is_valid(self) -> None:
        self.assertIsNotNone(_schema_validator())

    def test_extend_result_schema_requires_complete_success_shape(self) -> None:
        schema = json.loads(CLI_API_SCHEMA_PATH.read_text(encoding="utf-8"))
        extend_result_schema = {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            **schema["$defs"]["extendResultEvent"],
        }
        validator_cls = validators.validator_for(schema)
        validator_cls.check_schema(extend_result_schema)
        validator = validator_cls(extend_result_schema)
        event = {
            "type": "result",
            "ok": True,
            "command": "extend",
            "index": 1,
            "doc_id": "11" * 8,
            "doc_hash": "22" * 32,
            "root_doc_id": "33" * 8,
            "root_doc_hash": "44" * 32,
            "chain_id": "55" * 32,
            "parent_head_index": 0,
            "parent_head_doc_hash": "44" * 32,
            "expected_head_doc_hash": None,
            "freshness_scope": "supplied_carriers_only",
            "extension_dir": "/tmp/root/extensions/01",
            "artifacts": {
                "qr_document": "/tmp/root/extensions/01/qr.pdf",
                "recovery_document": "/tmp/root/extensions/01/recovery.pdf",
                "recovery_kit_index": None,
                "shard_documents": [],
                "signing_key_shard_documents": [],
            },
            "selected_scope": _extend_selected_scope(files=["input.txt"]),
            "diff_summary": _extend_diff_summary(changed_paths=["input.txt"]),
            "resolved_policy": {
                "passphrase": {
                    "mode": "plaintext",
                    "threshold": None,
                    "share_count": None,
                },
                "signing_key": {
                    "mode": "not-stored",
                    "threshold": None,
                    "share_count": None,
                },
                "recovery_kit_index": False,
                "qr_chunk_size": 256,
                "layout_debug_dir": None,
            },
            "chunk_reuse": {"reused_chunks": 1, "new_chunks": 1},
            "extension_bytes": 1,
        }
        validator.validate(event)

        for field in (
            "root_doc_id",
            "root_doc_hash",
            "chain_id",
            "selected_scope",
            "diff_summary",
            "chunk_reuse",
        ):
            invalid_event = {**event, field: None}
            with self.assertRaises(ValidationError):
                validator.validate(invalid_event)

    def test_extend_resolved_policy_schema_rejects_impossible_states(self) -> None:
        schema = json.loads(CLI_API_SCHEMA_PATH.read_text(encoding="utf-8"))
        defs = schema["$defs"]
        passphrase_schema = defs["extendPassphrasePolicyPreview"]
        signing_key_schema = defs["extendSigningKeyPolicyPreview"]
        validator_cls = validators.validator_for(schema)
        validator_cls.check_schema(passphrase_schema)
        validator_cls.check_schema(signing_key_schema)
        passphrase_validator = validator_cls(passphrase_schema)
        signing_key_validator = validator_cls(signing_key_schema)

        passphrase_validator.validate(
            {"mode": "extension-shards", "threshold": 2, "share_count": 3}
        )
        passphrase_validator.validate({"mode": "plaintext", "threshold": None, "share_count": None})
        signing_key_validator.validate(
            {"mode": "extension-shards", "threshold": 2, "share_count": 3}
        )
        signing_key_validator.validate(
            {"mode": "not-stored", "threshold": None, "share_count": None}
        )

        for invalid_policy, validator in (
            (
                {"mode": "extension-shards", "threshold": None, "share_count": None},
                passphrase_validator,
            ),
            (
                {"mode": "not-stored", "threshold": 1, "share_count": 1},
                signing_key_validator,
            ),
            (
                {"mode": "reuse-root-shards", "threshold": None, "share_count": 2},
                passphrase_validator,
            ),
            (
                {"mode": "plaintext", "threshold": 1, "share_count": 1},
                passphrase_validator,
            ),
            (
                {"mode": "extension-shards", "threshold": 1, "share_count": 256},
                passphrase_validator,
            ),
            (
                {"mode": "extension-shards", "threshold": 1, "share_count": 256},
                signing_key_validator,
            ),
        ):
            with self.assertRaises(ValidationError):
                validator.validate(invalid_policy)

    def test_recover_manifest_schema_enforces_payload_raw_len_by_codec(self) -> None:
        validator = _recover_manifest_validator()

        raw_manifest = {
            "format_version": 1,
            "input_origin": "file",
            "input_roots": [],
            "sealed": False,
            "payload_codec": "raw",
            "payload_raw_len": None,
            "file_count": 1,
        }
        gzip_manifest = {
            "format_version": 1,
            "input_origin": "directory",
            "input_roots": ["root"],
            "sealed": False,
            "payload_codec": "gzip",
            "payload_raw_len": 7,
            "file_count": 1,
        }

        validator.validate(raw_manifest)
        validator.validate(gzip_manifest)

        for invalid_manifest in (
            {**raw_manifest, "payload_raw_len": 7},
            {**gzip_manifest, "payload_raw_len": None},
            {**gzip_manifest, "payload_raw_len": 0},
        ):
            with self.assertRaises(ValidationError):
                validator.validate(invalid_manifest)

    def test_cli_api_contract_codes_match_fixture(self) -> None:
        contracts = _contracts()
        self.assertEqual(
            list(api_codes.STABLE_COMMAND_ERROR_CODES),
            contracts["stable_command_error_codes"],
        )
        self.assertEqual(
            list(api_codes.STABLE_GENERIC_ERROR_CODES),
            contracts["stable_generic_error_codes"],
        )
        self.assertEqual(list(api_codes.STABLE_WARNING_CODES), contracts["stable_warning_codes"])
        self.assertEqual(
            list(api_codes.STABLE_BLOCKING_ISSUE_CODES),
            contracts["stable_blocking_issue_codes"],
        )

    def test_cli_api_schema_documented_code_enums_match_contract_fixture(self) -> None:
        contracts = _contracts()
        schema = json.loads(CLI_API_SCHEMA_PATH.read_text(encoding="utf-8"))
        defs = schema["$defs"]

        self.assertEqual(
            defs["documentedErrorCode"]["enum"],
            [
                *contracts["stable_command_error_codes"],
                *contracts["stable_generic_error_codes"],
            ],
        )
        self.assertEqual(
            defs["documentedWarningCode"]["enum"],
            contracts["stable_warning_codes"],
        )
        self.assertEqual(
            defs["documentedBlockingIssueCode"]["enum"],
            contracts["stable_blocking_issue_codes"],
        )

    def test_extend_promoted_blocking_codes_are_stable_command_errors(self) -> None:
        self.assertLessEqual(
            set(api_codes.STABLE_BLOCKING_ISSUE_CODES),
            set(api_codes.STABLE_COMMAND_ERROR_CODES),
        )

    def test_extend_started_events_accept_zero_shard_policy_values(self) -> None:
        validator = _schema_validator()
        shared_args = {
            "config": None,
            "paper": None,
            "design": None,
            "root_dir": "/tmp/root",
            "input": ["input.txt"],
            "input_dir": [],
            "base_dir": None,
            "layout_debug_dir": None,
            "qr_chunk_size": None,
            "has_passphrase": False,
            "shard_fallback_file": [],
            "shard_payloads_file": [],
            "shard_scan": [],
            "unlock_policy": "self-contained",
            "shard_threshold": 0,
            "shard_count": 0,
            "signing_key_mode": None,
            "signing_key_shard_threshold": 0,
            "signing_key_shard_count": 0,
            "expected_head_doc_hash": None,
            "quiet": True,
            "debug": False,
        }
        extend_started = {
            "type": "started",
            "schema_version": 1,
            "command": "extend",
            "args": {
                **shared_args,
            },
        }
        inspect_extend_started = {
            "type": "started",
            "schema_version": 1,
            "command": "extend",
            "args": {
                **shared_args,
                "operation": "inspect",
            },
        }

        validator.validate(extend_started)
        validator.validate(inspect_extend_started)

    def test_extend_started_events_reject_shard_policy_values_above_max(self) -> None:
        validator = _schema_validator()
        shared_args = {
            "config": None,
            "paper": None,
            "design": None,
            "root_dir": "/tmp/root",
            "input": ["input.txt"],
            "input_dir": [],
            "base_dir": None,
            "layout_debug_dir": None,
            "qr_chunk_size": None,
            "has_passphrase": False,
            "shard_fallback_file": [],
            "shard_payloads_file": [],
            "shard_scan": [],
            "unlock_policy": "self-contained",
            "shard_threshold": 0,
            "shard_count": 0,
            "signing_key_mode": None,
            "signing_key_shard_threshold": 0,
            "signing_key_shard_count": 0,
            "quiet": True,
            "debug": False,
        }
        for operation in (None, "inspect"):
            for field in (
                "shard_threshold",
                "shard_count",
                "signing_key_shard_threshold",
                "signing_key_shard_count",
            ):
                args = {**shared_args, field: 256}
                if operation is not None:
                    args["operation"] = operation
                event = {
                    "type": "started",
                    "schema_version": 1,
                    "command": "extend",
                    "args": args,
                }
                with self.assertRaises(ValidationError):
                    validator.validate(event)

    def test_api_help_lists_recover(self) -> None:
        with mock.patch(
            "ethernity.cli.bootstrap.app.run_startup", return_value=False
        ) as run_startup:
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "--help"],
            )
        self.assertEqual(result.exit_code, 0)
        run_startup.assert_not_called()
        self.assertIn("backup", result.output)
        self.assertIn("config", result.output)
        self.assertIn("inspect", result.output)
        self.assertIn("mint", result.output)
        self.assertIn("recover", result.output)

    def test_root_short_help_flag_prints_top_level_help(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(cli.app, ["-h"])

        self.assertEqual(result.exit_code, 0, result.output)
        output = _strip_ansi(result.output)
        self.assertIn("Ethernity CLI.", output)
        self.assertIn("backup", output)
        self.assertIn("api", output)

    def test_api_short_help_flag_prints_command_help(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "recover", "-h"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        output = _strip_ansi(result.output)
        self.assertIn("Recover data from QR payloads or fallback text", output)
        self.assertIn("--output", output)

    def test_api_inspect_help_mentions_extend(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "inspect", "--help"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        output = _strip_ansi(result.output)
        self.assertIn("recover, extend, and mint readiness", output)
        self.assertIn("extend", output)

    def test_api_extend_help_surfaces_required_and_typed_options(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "extend", "--help"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        output = " ".join(_strip_ansi(result.output).split())
        self.assertIn("Required in API mode", output)
        self.assertIn("Accepted values:", output)
        self.assertIn("self-contained, reuse-root", output)
        self.assertIn("not-stored, sharded", output)
        self.assertIn("INTEGER", output)
        self.assertIn("POLICY", output)
        self.assertIn("MODE", output)

    def test_api_inspect_extend_help_uses_current_copy(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "inspect", "extend", "--help"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        output = " ".join(_strip_ansi(result.output).split())
        self.assertIn("Passphrase to validate", output)
        self.assertIn("Backup root folder", output)
        self.assertIn("extension unlock", output)
        self.assertNotIn("when validation lands", output)

    def test_api_backup_help_surfaces_typed_contract_labels(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "backup", "--help"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        output = " ".join(_strip_ansi(result.output).split())
        self.assertIn("--qr-chunk-size", output)
        self.assertIn("--passphrase-words", output)
        self.assertIn("--signing-key-mode", output)
        self.assertIn("INTEGER", output)
        self.assertIn("MODE", output)

    def test_api_recover_help_surfaces_extension_index_as_integer(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "recover", "--help"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        output = " ".join(_strip_ansi(result.output).split())
        self.assertIn("--extension-index", output)
        self.assertIn("INTEGER", output)

    def test_api_inspect_recover_rejects_negative_extension_index_with_schema_valid_events(
        self,
    ) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "recover",
                    "--payloads-file",
                    str(V1_FIXTURE_ROOT / "main_payloads.txt"),
                    "--extension-index",
                    "-1",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertIsNone(events[0]["args"]["extension_index"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--extension-index must be >= 0", events[-1]["message"])

    def test_api_config_get_ignores_bootstrap_default_config_when_no_explicit_config(self) -> None:
        captured: dict[str, object] = {}

        def _capture(args) -> int:
            captured["config"] = args.config
            return 0

        with mock.patch(
            "ethernity.cli.features.api.command.run_config_get_api_command", side_effect=_capture
        ):
            result = self.runner.invoke(
                cli.app,
                ["api", "config", "get"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(captured["config"])

    def test_run_config_get_api_command_emits_snapshot(self) -> None:
        values = {
            "templates": {
                "default_name": "sentinel",
                "template_name": None,
                "recovery_template_name": None,
                "shard_template_name": None,
                "signing_key_shard_template_name": None,
                "kit_template_name": None,
            },
            "page": {"size": "A4"},
            "qr": {"error": "M", "chunk_size": 512},
            "extension": {
                "chunking": {
                    "target_size": 16384,
                    "min_size": 4096,
                    "max_size": 65536,
                }
            },
            "defaults": {
                "backup": {
                    "base_dir": None,
                    "output_dir": None,
                    "shard_threshold": None,
                    "shard_count": None,
                    "signing_key_mode": None,
                    "signing_key_shard_threshold": None,
                    "signing_key_shard_count": None,
                    "payload_codec": "auto",
                    "qr_payload_codec": "raw",
                },
                "recover": {"output": None},
            },
            "ui": {"quiet": False, "no_color": False, "no_animations": False},
            "debug": {"max_bytes": 1024},
            "runtime": {"render_jobs": "auto"},
        }
        options = {
            "template_designs": ["archive", "forge", "ledger", "maritime", "sentinel"],
            "page_sizes": ["A4", "LETTER"],
            "qr_error_correction": ["L", "M", "Q", "H"],
            "payload_codecs": ["auto", "raw", "gzip"],
            "qr_payload_codecs": ["raw", "base64"],
            "signing_key_modes": ["embedded", "sharded"],
            "onboarding_fields": list(ONBOARDING_FIELDS),
        }
        snapshot = SimpleNamespace(
            path="/tmp/config.toml",
            source="user",
            status="valid",
            errors=(),
            values=values,
            options=options,
            onboarding={
                "needed": True,
                "configured_fields": [],
                "available_fields": list(ONBOARDING_FIELDS),
            },
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.config.api_handlers.get_api_config_snapshot",
                return_value=snapshot,
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_config_get_api_command(ConfigGetArgs(config=None))

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "phase", "result"])
        self.assertEqual(events[-1]["command"], "config")
        self.assertEqual(events[-1]["operation"], "get")
        self.assertEqual(events[-1]["path"], snapshot.path)
        self.assertEqual(events[-1]["status"], "valid")
        self.assertEqual(events[-1]["errors"], [])
        self.assertEqual(events[-1]["onboarding"]["needed"], True)

    def test_run_config_set_api_command_reads_stdin_patch(self) -> None:
        values = {
            "templates": {
                "default_name": "sentinel",
                "template_name": None,
                "recovery_template_name": None,
                "shard_template_name": None,
                "signing_key_shard_template_name": None,
                "kit_template_name": None,
            },
            "page": {"size": "LETTER"},
            "qr": {"error": "Q", "chunk_size": 768},
            "extension": {
                "chunking": {
                    "target_size": 16384,
                    "min_size": 4096,
                    "max_size": 65536,
                }
            },
            "defaults": {
                "backup": {
                    "base_dir": None,
                    "output_dir": None,
                    "shard_threshold": None,
                    "shard_count": None,
                    "signing_key_mode": None,
                    "signing_key_shard_threshold": None,
                    "signing_key_shard_count": None,
                    "payload_codec": "auto",
                    "qr_payload_codec": "raw",
                },
                "recover": {"output": None},
            },
            "ui": {"quiet": False, "no_color": False, "no_animations": False},
            "debug": {"max_bytes": 1024},
            "runtime": {"render_jobs": "auto"},
        }
        options = {
            "template_designs": ["archive", "forge", "ledger", "maritime", "sentinel"],
            "page_sizes": ["A4", "LETTER"],
            "qr_error_correction": ["L", "M", "Q", "H"],
            "payload_codecs": ["auto", "raw", "gzip"],
            "qr_payload_codecs": ["raw", "base64"],
            "signing_key_modes": ["embedded", "sharded"],
            "onboarding_fields": list(ONBOARDING_FIELDS),
        }
        snapshot = SimpleNamespace(
            path="/tmp/config.toml",
            source="user",
            status="valid",
            errors=(),
            values=values,
            options=options,
            onboarding={
                "needed": False,
                "configured_fields": ["page_size"],
                "available_fields": list(ONBOARDING_FIELDS),
            },
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.config.api_handlers.apply_api_config_patch",
                return_value=snapshot,
            ) as apply_patch,
            ndjson_session(stream=buffer),
            mock.patch(
                "ethernity.cli.features.config.api_handlers.sys.stdin",
                io.StringIO('{"values":{"page":{"size":"LETTER"}}}'),
            ),
        ):
            exit_code = run_config_set_api_command(ConfigSetArgs(config=None, input_json="-"))

        self.assertEqual(exit_code, 0)
        apply_patch.assert_called_once_with(None, {"values": {"page": {"size": "LETTER"}}})
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events], ["started", "phase", "phase", "result"]
        )
        self.assertEqual(events[-1]["operation"], "set")

    def test_api_config_set_invalid_json_emits_structured_error(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["api", "config", "set", "--input-json", "-"],
                input="{not-json}",
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["code"], api_codes.CONFIG_JSON_INVALID)

    def test_api_config_set_without_input_json_emits_started_then_error(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(cli.app, ["api", "config", "set"])

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], api_codes.CONFIG_INPUT_REQUIRED)
        self.assertEqual(
            events[-1]["message"],
            "--input-json is required for `ethernity api config set`",
        )

    def test_api_config_set_rejects_non_object_json(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["api", "config", "set", "--input-json", "-"],
                input='["not-an-object"]',
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["code"], api_codes.CONFIG_JSON_INVALID)

    def test_api_config_set_rejects_non_utf8_patch_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            patch_path = Path(tmpdir) / "patch.json"
            patch_path.write_bytes(b"\xff\xfe\xfd")
            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    ["api", "config", "set", "--input-json", str(patch_path)],
                )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["code"], api_codes.CONFIG_JSON_INVALID)
        self.assertEqual(events[-1]["message"], "config patch is not valid UTF-8")

    def test_api_config_set_invalid_patch_does_not_create_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "ethernity" / "config.toml"
            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    ["api", "config", "set", "--input-json", "-"],
                    input='{"values":"not-an-object"}',
                    env={"XDG_CONFIG_HOME": tmpdir},
                )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["code"], "CONFIG_INVALID_VALUE")
        self.assertFalse(config_path.exists())

    def test_api_config_set_invalid_values_do_not_emit_write_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    ["api", "config", "set", "--input-json", "-"],
                    input='{"values":{"page":{"size":"LEGAL"}}}',
                    env={"XDG_CONFIG_HOME": tmpdir},
                )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "phase", "error"])
        self.assertEqual(
            [event["id"] for event in events if event["type"] == "phase"],
            ["validate"],
        )
        self.assertEqual(events[-1]["code"], api_codes.CONFIG_INVALID_VALUE)

    def test_api_config_set_missing_patch_file_emits_not_found(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["api", "config", "set", "--input-json", "/no/such/patch.json"],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["code"], api_codes.NOT_FOUND)
        self.assertEqual(events[-1]["details"]["path"], _expected_host_path("/no/such/patch.json"))

    def test_api_command_does_not_run_startup(self) -> None:
        with (
            mock.patch(
                "ethernity.cli.bootstrap.app.run_startup",
                side_effect=AssertionError("startup-called"),
            ) as run_startup,
            mock.patch("ethernity.cli.features.api.command.run_backup_api_command", return_value=0),
        ):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "backup", "--input", "-"],
                input="payload",
            )

        self.assertEqual(result.exit_code, 0, result.output)
        run_startup.assert_not_called()

    def test_api_defaults_load_failure_emits_ndjson_error(self) -> None:
        with (
            mock.patch(
                "ethernity.cli.bootstrap.app.load_cli_defaults",
                side_effect=ValueError("defaults-failed"),
            ),
        ):
            result = self.runner.invoke(
                cli.app,
                ["api", "backup", "--input", "-"],
                input="payload",
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "error")
        self.assertEqual(events[0]["code"], api_codes.INVALID_INPUT)
        self.assertEqual(events[0]["message"], "defaults-failed")

    def test_api_unexpected_exception_emits_runtime_error(self) -> None:
        class CustomFailure(Exception):
            pass

        with (
            mock.patch(
                "ethernity.cli.bootstrap.app.run_startup",
                side_effect=AssertionError("startup-called"),
            ) as run_startup,
            mock.patch(
                "ethernity.cli.features.api.command.run_backup_api_command",
                side_effect=CustomFailure("boom"),
            ),
        ):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "backup", "--input", "-"],
                input="payload",
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        run_startup.assert_not_called()
        self.assertEqual(events[-1]["code"], api_codes.RUNTIME_ERROR)
        self.assertEqual(events[-1]["details"]["error_type"], "CustomFailure")

    def test_api_click_abort_emits_cancelled_and_exit_130(self) -> None:
        with (
            mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            mock.patch(
                "ethernity.cli.features.api.command.run_backup_api_command",
                side_effect=click.Abort(),
            ),
        ):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "backup", "--input", "-"],
                input="payload",
            )

        self.assertEqual(result.exit_code, 130)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], api_codes.CANCELLED)

    def test_api_backup_flag_values_reach_command(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: BackupArgs) -> int:
            captured["input"] = list(args.input or [])
            captured["output_dir"] = args.output_dir
            captured["output_dir_existing_parent"] = args.output_dir_existing_parent
            captured["shard_threshold"] = args.shard_threshold
            return 0

        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.features.api.command.run_backup_api_command",
                side_effect=_capture_args,
            ):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "backup",
                        "--input",
                        "-",
                        "--output-dir",
                        "./api-out",
                        "--shard-threshold",
                        "2",
                    ],
                    input="payload",
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["input"], ["-"])
        self.assertEqual(captured["output_dir"], "./api-out")
        self.assertTrue(captured["output_dir_existing_parent"])
        self.assertEqual(captured["shard_threshold"], 2)

    def test_api_extend_flag_values_reach_command(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: ExtendArgs, *, debug: bool = False) -> int:
            captured["root_dir"] = args.root_dir
            captured["input"] = list(args.input or [])
            captured["qr_chunk_size"] = args.qr_chunk_size
            captured["shard_scan"] = list(args.shard_scan or [])
            captured["unlock_policy"] = args.unlock_policy
            captured["shard_threshold"] = args.shard_threshold
            captured["signing_key_mode"] = args.signing_key_mode
            captured["debug"] = debug
            return 0

        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.features.api.command.run_extend_api_command",
                side_effect=_capture_args,
            ):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "extend",
                        "--root-dir",
                        "/tmp/root",
                        "--input",
                        "-",
                        "--qr-chunk-size",
                        "32",
                        "--shard-scan",
                        "scan-a.pdf",
                        "--unlock-policy",
                        "reuse-root",
                        "--shard-threshold",
                        "2",
                        "--signing-key-mode",
                        "sharded",
                    ],
                    input="payload",
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["root_dir"], "/tmp/root")
        self.assertEqual(captured["input"], ["-"])
        self.assertEqual(captured["qr_chunk_size"], 32)
        self.assertEqual(captured["shard_scan"], ["scan-a.pdf"])
        self.assertEqual(captured["unlock_policy"], "reuse-root")
        self.assertEqual(captured["shard_threshold"], 2)
        self.assertEqual(captured["signing_key_mode"], "sharded")
        self.assertFalse(captured["debug"])

    def test_api_inspect_extend_flag_values_reach_command(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: ExtendArgs, *, debug: bool = False) -> int:
            captured["root_dir"] = args.root_dir
            captured["input"] = list(args.input or [])
            captured["shard_scan"] = list(args.shard_scan or [])
            captured["layout_debug_dir"] = args.layout_debug_dir
            captured["qr_chunk_size"] = args.qr_chunk_size
            captured["unlock_policy"] = args.unlock_policy
            captured["shard_threshold"] = args.shard_threshold
            captured["shard_count"] = args.shard_count
            captured["signing_key_mode"] = args.signing_key_mode
            captured["signing_key_shard_threshold"] = args.signing_key_shard_threshold
            captured["signing_key_shard_count"] = args.signing_key_shard_count
            captured["debug"] = debug
            return 0

        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.features.api.command.run_extend_inspect_api_command",
                side_effect=_capture_args,
            ):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "inspect",
                        "extend",
                        "--root-dir",
                        "/tmp/root",
                        "--input",
                        "-",
                        "--shard-scan",
                        "scan-a.pdf",
                        "--layout-debug-dir",
                        "/tmp/layout",
                        "--qr-chunk-size",
                        "32",
                        "--unlock-policy",
                        "reuse-root",
                        "--shard-threshold",
                        "2",
                        "--shard-count",
                        "3",
                        "--signing-key-mode",
                        "sharded",
                        "--signing-key-shard-threshold",
                        "2",
                        "--signing-key-shard-count",
                        "4",
                    ],
                    input="payload",
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["root_dir"], "/tmp/root")
        self.assertEqual(captured["input"], ["-"])
        self.assertEqual(captured["shard_scan"], ["scan-a.pdf"])
        self.assertEqual(captured["layout_debug_dir"], "/tmp/layout")
        self.assertEqual(captured["qr_chunk_size"], 32)
        self.assertEqual(captured["unlock_policy"], "reuse-root")
        self.assertEqual(captured["shard_threshold"], 2)
        self.assertEqual(captured["shard_count"], 3)
        self.assertEqual(captured["signing_key_mode"], "sharded")
        self.assertEqual(captured["signing_key_shard_threshold"], 2)
        self.assertEqual(captured["signing_key_shard_count"], 4)
        self.assertFalse(captured["debug"])

    def test_build_extend_api_args_preserves_raw_policy_values(self) -> None:
        state = CliContextState(
            backup_defaults=BackupDefaults(
                base_dir="/saved/base",
                shard_threshold=2,
                shard_count=3,
                signing_key_mode="sharded",
                signing_key_shard_threshold=2,
                signing_key_shard_count=4,
            )
        )

        def _build_args(unlock_policy: str | None) -> ExtendArgs:
            return api_command._build_extend_api_args(
                state=state,
                config_value=None,
                paper_value=None,
                design=None,
                root_dir="/tmp/root",
                input=["input.txt"],
                input_dir=None,
                base_dir=None,
                layout_debug_dir=None,
                qr_chunk_size=None,
                passphrase="secret",
                shard_fallback_file=None,
                shard_payloads_file=None,
                shard_scan=None,
                unlock_policy=unlock_policy,
                shard_threshold=None,
                shard_count=None,
                signing_key_mode=None,
                signing_key_shard_threshold=None,
                signing_key_shard_count=None,
            )

        self_contained_args = _build_args(None)
        reuse_root_args = _build_args("reuse-root")

        self.assertEqual(self_contained_args.base_dir, "/saved/base")
        self.assertIsNone(self_contained_args.unlock_policy)
        self.assertIsNone(self_contained_args.shard_threshold)
        self.assertIsNone(self_contained_args.shard_count)
        self.assertIsNone(self_contained_args.signing_key_mode)
        self.assertIsNone(self_contained_args.signing_key_shard_threshold)
        self.assertIsNone(self_contained_args.signing_key_shard_count)
        self.assertEqual(reuse_root_args.unlock_policy, "reuse-root")
        self.assertEqual(reuse_root_args.base_dir, "/saved/base")
        self.assertIsNone(reuse_root_args.shard_threshold)
        self.assertIsNone(reuse_root_args.shard_count)
        self.assertIsNone(reuse_root_args.signing_key_mode)
        self.assertIsNone(reuse_root_args.signing_key_shard_threshold)
        self.assertIsNone(reuse_root_args.signing_key_shard_count)

    def test_build_extend_api_args_parses_explicit_policy_values(self) -> None:
        args = api_command._build_extend_api_args(
            state=None,
            config_value=None,
            paper_value=None,
            design=None,
            root_dir="/tmp/root",
            input=["input.txt"],
            input_dir=None,
            base_dir=None,
            layout_debug_dir=None,
            qr_chunk_size=None,
            passphrase="secret",
            shard_fallback_file=None,
            shard_payloads_file=None,
            shard_scan=None,
            unlock_policy="self-contained",
            shard_threshold="2",
            shard_count="3",
            signing_key_mode="sharded",
            signing_key_shard_threshold="2",
            signing_key_shard_count="4",
        )

        self.assertEqual(args.unlock_policy, "self-contained")
        self.assertEqual(args.shard_threshold, 2)
        self.assertEqual(args.shard_count, 3)
        self.assertEqual(args.signing_key_mode, "sharded")
        self.assertEqual(args.signing_key_shard_threshold, 2)
        self.assertEqual(args.signing_key_shard_count, 4)

        not_stored_args = api_command._build_extend_api_args(
            state=None,
            config_value=None,
            paper_value=None,
            design=None,
            root_dir="/tmp/root",
            input=["input.txt"],
            input_dir=None,
            base_dir=None,
            layout_debug_dir=None,
            qr_chunk_size=None,
            passphrase="secret",
            shard_fallback_file=None,
            shard_payloads_file=None,
            shard_scan=None,
            unlock_policy=None,
            shard_threshold=None,
            shard_count=None,
            signing_key_mode="not-stored",
            signing_key_shard_threshold=None,
            signing_key_shard_count=None,
        )

        self.assertEqual(not_stored_args.signing_key_mode, "not-stored")

    def test_build_extend_api_args_rejects_schema_invalid_integer_values(self) -> None:
        base_kwargs = {
            "state": None,
            "config_value": None,
            "paper_value": None,
            "design": None,
            "root_dir": "/tmp/root",
            "input": ["input.txt"],
            "input_dir": None,
            "base_dir": None,
            "layout_debug_dir": None,
            "qr_chunk_size": None,
            "passphrase": "secret",
            "shard_fallback_file": None,
            "shard_payloads_file": None,
            "shard_scan": None,
            "unlock_policy": None,
            "shard_threshold": None,
            "shard_count": None,
            "signing_key_mode": None,
            "signing_key_shard_threshold": None,
            "signing_key_shard_count": None,
        }

        invalid_values = (
            ("qr_chunk_size", "0"),
            ("shard_threshold", "-1"),
            ("shard_count", "-1"),
            ("signing_key_shard_threshold", "-1"),
            ("signing_key_shard_count", "-1"),
            ("shard_threshold", "256"),
            ("shard_count", "256"),
            ("signing_key_shard_threshold", "256"),
            ("signing_key_shard_count", "256"),
        )
        for field, value in invalid_values:
            with self.subTest(field=field), self.assertRaises(ApiCommandError) as caught:
                api_command._build_extend_api_args(**{**base_kwargs, field: value})

            self.assertEqual(caught.exception.code, api_codes.INVALID_INPUT)

        with self.assertRaises(ApiCommandError) as caught:
            api_command._build_extend_api_args(**{**base_kwargs, "signing_key_mode": "embedded"})

        self.assertEqual(caught.exception.code, api_codes.EXTENSION_INVALID_POLICY)
        self.assertIn("not-stored", caught.exception.message)

        with self.assertRaises(ApiCommandError) as caught:
            api_command._build_extend_api_args(**{**base_kwargs, "unlock_policy": "detached"})

        self.assertEqual(caught.exception.code, api_codes.EXTENSION_INVALID_POLICY)
        self.assertIn("self-contained", caught.exception.message)

    def test_api_extend_rejects_invalid_qr_chunk_size_with_schema_valid_events(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "extend",
                    "--root-dir",
                    "/tmp/root",
                    "--input",
                    "input.txt",
                    "--qr-chunk-size",
                    "0",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertIsNone(events[0]["args"]["qr_chunk_size"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--qr-chunk-size must be >= 1", events[-1]["message"])

    def test_api_inspect_extend_rejects_oversized_shard_count_with_schema_valid_events(
        self,
    ) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "extend",
                    "--root-dir",
                    "/tmp/root",
                    "--shard-count",
                    "999",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertIsNone(events[0]["args"]["shard_count"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--shard-count must be <= 255", events[-1]["message"])

    def test_api_inspect_extend_empty_layout_debug_dir_started_arg_is_null(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "extend",
                    "--root-dir",
                    "/tmp/root",
                    "--layout-debug-dir",
                    "",
                    "--qr-chunk-size",
                    "0",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertIsNone(events[0]["args"]["layout_debug_dir"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)

    def test_api_compact_rejects_invalid_qr_chunk_size_with_schema_valid_events(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "compact",
                    "--root-dir",
                    "/tmp/root",
                    "--output-dir",
                    "/tmp/out",
                    "--qr-chunk-size",
                    "0",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertIsNone(events[0]["args"]["qr_chunk_size"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--qr-chunk-size must be >= 1", events[-1]["message"])

    def test_api_inspect_mint_rejects_zero_shard_threshold_with_schema_valid_events(
        self,
    ) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "mint",
                    "--shard-threshold",
                    "0",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertIsNone(events[0]["args"]["shard_threshold"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--shard-threshold must be >= 1", events[-1]["message"])

    def test_api_compact_flag_values_reach_command(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: CompactArgs, *, debug: bool = False) -> int:
            captured["root_dir"] = args.root_dir
            captured["output_dir"] = args.output_dir
            captured["qr_chunk_size"] = args.qr_chunk_size
            captured["design"] = args.design
            captured["shard_scan"] = args.shard_scan
            captured["auth_payloads_file"] = args.auth_payloads_file
            captured["debug"] = debug
            return 0

        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.features.api.command.run_compact_api_command",
                side_effect=_capture_args,
            ):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "compact",
                        "--root-dir",
                        "/tmp/root",
                        "--output-dir",
                        "/tmp/out",
                        "--shard-scan",
                        "shard-a.pdf",
                        "--auth-payloads-file",
                        "auth.payloads",
                        "--qr-chunk-size",
                        "32",
                        "--design",
                        "forge",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["root_dir"], "/tmp/root")
        self.assertEqual(captured["output_dir"], "/tmp/out")
        self.assertEqual(captured["qr_chunk_size"], 32)
        self.assertEqual(captured["design"], "forge")
        self.assertEqual(captured["shard_scan"], ["shard-a.pdf"])
        self.assertEqual(captured["auth_payloads_file"], "auth.payloads")
        self.assertFalse(captured["debug"])

    def test_api_compact_output_dir_remains_explicit_even_with_backup_default(self) -> None:
        args = api_command._build_compact_api_args(
            state=CliContextState(backup_defaults=BackupDefaults(output_dir="/tmp/default-out")),
            config_value=None,
            paper_value=None,
            design=None,
            root_dir="/tmp/root",
            output_dir=None,
            shard_fallback_file=None,
            shard_payloads_file=None,
            shard_scan=None,
            auth_fallback_file=None,
            auth_payloads_file=None,
            layout_debug_dir=None,
            qr_chunk_size=None,
            passphrase=None,
        )

        self.assertIsNone(args.output_dir)

    def test_apply_recover_stdin_default_skips_stdin_for_extension_selectors(self) -> None:
        self.assertIsNone(
            apply_recover_stdin_default(
                None,
                None,
                [],
                extension_selector_present=True,
                stdin_is_tty=False,
            )
        )

    def test_api_recover_emits_ndjson_and_writes_output(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "recovered.bin"
            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "recover",
                        "--payloads-file",
                        str(payloads_file),
                        "--passphrase",
                        FIXTURE_PASSPHRASE,
                        "--output",
                        str(output_path),
                    ],
                )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
            self._assert_valid_events(events)
            self.assertEqual(
                [event["type"] for event in events],
                _contracts()["recover_success_event_types"],
            )
            self.assertEqual(events[0]["args"]["config"], str(DEFAULT_CONFIG_PATH))
            self.assertEqual(events[2]["phase"], "plan")
            self.assertEqual(events[4]["phase"], "decrypt")
            self.assertEqual(events[6]["phase"], "write")
            self.assertEqual(events[-1]["output_path"], str(output_path))
            self.assertEqual(events[-1]["output_path_kind"], "file")
            self.assertEqual(events[-1]["manifest"]["file_count"], 1)
            self.assertTrue(output_path.exists())
            self.assertEqual(events[-2]["path"], str(output_path))

    def test_api_recover_result_uses_same_normalized_path_as_artifact(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        with self.runner.isolated_filesystem():
            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "recover",
                        "--payloads-file",
                        str(payloads_file),
                        "--passphrase",
                        FIXTURE_PASSPHRASE,
                        "--output",
                        "./recovered.bin",
                    ],
                )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
            self._assert_valid_events(events)
            self.assertEqual(events[-1]["output_path"], events[-2]["path"])
            self.assertEqual(events[-1]["output_path_kind"], "file")
            self.assertEqual(events[-1]["output_path"], "recovered.bin")

    def test_run_recover_api_command_reports_selected_extension_metadata(self) -> None:
        args = RecoverArgs(scan=["/tmp/root"], passphrase="secret", output="/tmp/out", quiet=True)
        execution = SimpleNamespace(
            plan=SimpleNamespace(
                doc_id=b"\x01" * 8,
                auth_status="verified",
                input_label="Backup root directory",
                input_detail="/tmp/root",
            ),
            output_path="/tmp/out",
            output_path_kind="directory",
            manifest=SimpleNamespace(
                format_version=1,
                input_origin="directory",
                input_roots=("selected",),
                sealed=False,
                payload_codec="raw",
                payload_raw_len=None,
                files=(object(),),
            ),
            file_payloads=(),
            selected_extension_index=2,
            selected_extension_doc_hash="ab" * 32,
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.prepare_recover_plan",
                return_value=SimpleNamespace(),
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.execute_recover_plan",
                return_value=execution,
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["selected_extension_index"], 2)
        self.assertEqual(events[-1]["selected_extension_doc_hash"], "ab" * 32)

    def test_api_recover_with_valid_auth_emits_no_skip_warning(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "recovered.bin"
            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "recover",
                        "--payloads-file",
                        str(payloads_file),
                        "--passphrase",
                        FIXTURE_PASSPHRASE,
                        "--output",
                        str(output_path),
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        warning_events = [event for event in events if event["type"] == "warning"]
        self.assertEqual(warning_events, [])

    def test_api_recover_without_output_emits_structured_error(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "recover",
                    "--payloads-file",
                    str(payloads_file),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], "OUTPUT_REQUIRED")
        self.assertIn("--output is required", events[-1]["message"])

    def test_api_recover_without_output_ignores_config_default(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        defaults = CliDefaults(recover=RecoverDefaults(output="/tmp/stale-output.bin"))
        with (
            mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            mock.patch("ethernity.cli.bootstrap.app.load_cli_defaults", return_value=defaults),
        ):
            result = self.runner.invoke(
                cli.app,
                [
                    "api",
                    "recover",
                    "--payloads-file",
                    str(payloads_file),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], "OUTPUT_REQUIRED")

    def test_api_inspect_recover_accepts_input_flags_without_output(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args, **_kwargs) -> int:
            captured["payloads_file"] = args.payloads_file
            captured["passphrase"] = args.passphrase
            captured["output"] = args.output
            return 0

        with (
            mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            mock.patch(
                "ethernity.cli.features.api.command.run_recover_inspect_api_command",
                side_effect=_capture_args,
            ),
        ):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "recover",
                    "--payloads-file",
                    str(V1_FIXTURE_ROOT / "main_payloads.txt"),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["payloads_file"], str(V1_FIXTURE_ROOT / "main_payloads.txt"))
        self.assertEqual(captured["passphrase"], FIXTURE_PASSPHRASE)
        self.assertIsNone(captured["output"])

    def test_api_inspect_recover_emits_ndjson_without_artifacts(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "recover",
                    "--payloads-file",
                    str(V1_FIXTURE_ROOT / "main_payloads.txt"),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["started", "phase", "progress", "phase", "progress", "result"],
        )
        self.assertEqual(events[-1]["command"], "recover")
        self.assertEqual(events[-1]["operation"], "inspect")
        self.assertEqual(events[-1]["unlock"]["satisfied"], True)
        self.assertIsNotNone(events[-1]["source_summary"])
        self.assertEqual([event for event in events if event["type"] == "artifact"], [])

    def test_api_inspect_recover_reuses_stdin_payloads_for_source_summary(self) -> None:
        payload_text = (V1_FIXTURE_ROOT / "main_payloads.txt").read_text(encoding="utf-8")
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "recover",
                    "--payloads-file",
                    "-",
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                ],
                input=payload_text,
            )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["operation"], "inspect")
        self.assertTrue(events[-1]["unlock"]["satisfied"])
        self.assertIsNotNone(events[-1]["source_summary"])
        self.assertEqual(events[-1]["blocking_issues"], [])

    def test_api_inspect_recover_under_quorum_returns_blocking_issue(self) -> None:
        threshold_payloads = (
            V1_1_SHARDED_EMBEDDED_FIXTURE_ROOT / "shard_payloads_threshold.txt"
        ).read_text(encoding="utf-8")
        first_line = next(line for line in threshold_payloads.splitlines() if line.strip())
        with tempfile.TemporaryDirectory() as tmpdir:
            shard_payloads_path = Path(tmpdir) / "single-shard.txt"
            shard_payloads_path.write_text(first_line + "\n", encoding="utf-8")
            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "inspect",
                        "recover",
                        "--payloads-file",
                        str(V1_1_SHARDED_EMBEDDED_FIXTURE_ROOT / "main_payloads.txt"),
                        "--shard-payloads-file",
                        str(shard_payloads_path),
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["operation"], "inspect")
        self.assertIsNone(events[-1]["source_summary"])
        self.assertEqual(events[-1]["unlock"]["validated_shard_count"], 1)
        self.assertEqual(events[-1]["unlock"]["required_shard_threshold"], 2)
        self.assertEqual(events[-1]["unlock"]["shard_share_count"], 3)
        self.assertEqual(events[-1]["unlock"]["satisfied"], False)
        self.assertTrue(events[-1]["blocking_issues"])
        self.assertEqual([event for event in events if event["type"] == "artifact"], [])

    def test_api_inspect_recover_mixed_import_without_passphrase_returns_readiness(self) -> None:
        root_ciphertext = _root_envelope()
        _root_doc_id, root_doc_hash = doc_id_and_hash_from_ciphertext(root_ciphertext)
        extension_ciphertext = _extension_envelope(root_doc_hash)
        frames = [_main_frame(root_ciphertext), _main_frame(extension_ciphertext)]
        auth_frames = [_auth_frame(root_ciphertext), _auth_frame(extension_ciphertext)]
        args = RecoverArgs(payloads_file="/tmp/imported-payloads.txt", quiet=True)
        buffer = io.StringIO()

        with (
            mock.patch(
                "ethernity.cli.features.recover.planning.resolve_recover_config",
                return_value=object(),
            ),
            mock.patch(
                "ethernity.cli.features.recover.planning._frames_from_args",
                return_value=(frames, "QR payloads", "/tmp/imported-payloads.txt", None),
            ),
            mock.patch(
                "ethernity.cli.features.recover.planning._extra_auth_frames_from_args",
                return_value=auth_frames,
            ),
            mock.patch(
                "ethernity.cli.features.recover.planning._shard_frames_from_args",
                return_value=([], [], [], []),
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events], ["started", "phase", "progress", "result"]
        )
        result = events[-1]
        self.assertEqual(result["operation"], "inspect")
        self.assertIsNone(result["source_summary"])
        self.assertEqual(result["frame_counts"], {"main": 2, "auth": 2, "shard": 0})
        self.assertEqual(result["unlock"]["mode"], "missing")
        self.assertFalse(result["unlock"]["satisfied"])
        self.assertIn(
            "PASSPHRASE_REQUIRED",
            {issue["code"] for issue in result["blocking_issues"]},
        )
        self.assertEqual([event for event in events if event["type"] == "artifact"], [])

    def test_api_inspect_recover_mixed_import_bad_passphrase_returns_readiness(self) -> None:
        root_ciphertext = _root_envelope()
        _root_doc_id, root_doc_hash = doc_id_and_hash_from_ciphertext(root_ciphertext)
        extension_ciphertext = _extension_envelope(root_doc_hash)
        frames = [_main_frame(root_ciphertext), _main_frame(extension_ciphertext)]
        args = RecoverArgs(
            payloads_file="/tmp/imported-payloads.txt",
            passphrase="wrong-passphrase",
            quiet=True,
        )
        buffer = io.StringIO()

        with (
            mock.patch(
                "ethernity.cli.features.recover.planning.resolve_recover_config",
                return_value=object(),
            ),
            mock.patch(
                "ethernity.cli.features.recover.planning._frames_from_args",
                return_value=(frames, "QR payloads", "/tmp/imported-payloads.txt", None),
            ),
            mock.patch(
                "ethernity.cli.features.recover.planning._extra_auth_frames_from_args",
                return_value=[],
            ),
            mock.patch(
                "ethernity.cli.features.recover.planning._shard_frames_from_args",
                return_value=([], [], [], []),
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        result = events[-1]
        self.assertIsNone(result["source_summary"])
        self.assertEqual(result["unlock"]["mode"], "passphrase")
        self.assertTrue(result["unlock"]["passphrase_provided"])
        self.assertFalse(result["unlock"]["satisfied"])
        self.assertIn(
            "UNLOCK_FAILED",
            {issue["code"] for issue in result["blocking_issues"]},
        )

    def test_run_recover_inspect_api_command_replays_selected_extension_manifest(self) -> None:
        args = RecoverArgs(
            payloads_file="/tmp/payloads.txt",
            passphrase="secret",
            extension_index=1,
            quiet=True,
        )
        inspection = _extend_root_inspection(passphrase="secret", satisfied=True)
        selected_manifest = EnvelopeManifest(
            format_version=1,
            created_at=0.0,
            input_origin="directory",
            input_roots=("selected",),
            sealed=False,
            signing_seed=b"\x33" * 32,
            payload_codec="raw",
            payload_raw_len=None,
            files=(ManifestFile(path="updated.txt", size=7, sha256=b"\x44" * 32, mtime=2),),
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.inspect_from_args",
                return_value=inspection,
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.plan_from_inspection",
                return_value=SimpleNamespace(import_documents=(object(),)),
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.recover_chain_entries",
                return_value=SimpleNamespace(
                    manifest=selected_manifest,
                    selected_extension_index=1,
                    selected_extension_doc_hash="ab" * 32,
                ),
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["source_summary"]["input_origin"], "directory")
        self.assertEqual(events[-1]["source_summary"]["input_roots"], ["selected"])
        self.assertEqual(events[-1]["source_summary"]["file_count"], 1)
        self.assertEqual(events[-1]["selected_extension_index"], 1)
        self.assertEqual(events[-1]["selected_extension_doc_hash"], "ab" * 32)

    def test_recover_started_event_normalizes_extension_doc_hash(self) -> None:
        args = RecoverArgs(
            scan=["/tmp/root"],
            passphrase="secret",
            extension_doc_hash=("AB" * 32),
            quiet=True,
        )
        inspection = _extend_root_inspection(passphrase="secret", satisfied=False)
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.inspect_from_args",
                return_value=inspection,
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[0]["args"]["extension_doc_hash"], "ab" * 32)

    def test_api_recover_rejects_invalid_extension_doc_hash_with_schema_valid_events(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "recover",
                    "--fallback-file",
                    str(V1_FIXTURE_ROOT / "main_fallback.txt"),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                    "--output",
                    "/tmp/recovered.bin",
                    "--extension-doc-hash",
                    "not-a-doc-hash",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertIsNone(events[0]["args"]["extension_doc_hash"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--extension-doc-hash", events[-1]["message"])

    def test_run_recover_inspect_api_command_validates_root_authority_for_direct_scan(self) -> None:
        args = RecoverArgs(
            scan=["/tmp/qr_document.pdf"],
            passphrase="secret",
            quiet=True,
        )
        inspection = _extend_root_inspection(passphrase="secret", satisfied=True)
        manifest = EnvelopeManifest(
            format_version=1,
            created_at=0.0,
            input_origin="file",
            input_roots=(),
            sealed=False,
            signing_seed=b"\x33" * 32,
            payload_codec="raw",
            payload_raw_len=None,
            files=(),
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.inspect_from_args",
                return_value=inspection,
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.plan_from_inspection",
                return_value=SimpleNamespace(import_documents=()),
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.decrypt_bytes",
                return_value=b"plaintext",
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.decode_envelope",
                return_value=(manifest, b"payload"),
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.validate_root_manifest_authority",
                side_effect=ApiCommandError(
                    code="ROOT_AUTHORITY_MISMATCH",
                    message="embedded signing seed does not match the verified root AUTH authority",
                ),
            ) as validate_root_manifest_authority,
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        validate_root_manifest_authority.assert_called_once_with(
            manifest,
            inspection.auth_payload,
            doc_hash=inspection.doc_hash,
        )
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["source_summary"], None)
        self.assertEqual(
            events[-1]["blocking_issues"],
            [
                {
                    "code": "ROOT_AUTHORITY_MISMATCH",
                    "message": (
                        "embedded signing seed does not match the verified root AUTH authority"
                    ),
                    "details": {},
                }
            ],
        )

    def test_run_recover_inspect_api_command_reports_expected_head_mismatch_for_direct_scan(
        self,
    ) -> None:
        args = RecoverArgs(
            scan=["/tmp/qr_document.pdf"],
            passphrase="secret",
            expected_head_doc_hash="aa" * 32,
            quiet=True,
        )
        inspection = _extend_root_inspection(passphrase="secret", satisfied=True)
        manifest = EnvelopeManifest(
            format_version=1,
            created_at=0.0,
            input_origin="file",
            input_roots=(),
            sealed=False,
            signing_seed=b"\x33" * 32,
            payload_codec="raw",
            payload_raw_len=None,
            files=(),
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.inspect_from_args",
                return_value=inspection,
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.plan_from_inspection",
                return_value=SimpleNamespace(
                    import_documents=(),
                    doc_hash=inspection.doc_hash,
                    expected_head_doc_hash="aa" * 32,
                ),
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.decrypt_bytes",
                return_value=b"plaintext",
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.decode_envelope",
                return_value=(manifest, b"payload"),
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertIsNone(events[-1]["source_summary"])
        self.assertEqual(events[-1]["validated_head_index"], 0)
        self.assertEqual(events[-1]["validated_head_doc_hash"], inspection.doc_hash.hex())
        self.assertEqual(
            events[-1]["blocking_issues"][0]["code"],
            api_codes.RECOVERY_HEAD_UNTRUSTED,
        )

    def test_run_recover_inspect_api_command_preserves_plan_stage_trust_code(self) -> None:
        args = RecoverArgs(
            scan=["/tmp/root"],
            passphrase="secret",
            extension_doc_hash="ab" * 32,
            quiet=True,
        )
        inspection = _extend_root_inspection(passphrase="secret", satisfied=True)
        trust_details = {
            "stage": "replay",
            "failure_stage": "reconstruction",
            "latest_head_index": 2,
            "requested_head_doc_hash": "ab" * 32,
            "validated_head_index": 1,
            "validated_head_doc_hash": "cd" * 32,
            "explicit_selection": True,
        }
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.inspect_from_args",
                return_value=inspection,
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.plan_from_inspection",
                side_effect=ApiCommandError(
                    code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                    message="requested recovery head could not be trusted: latest suffix degraded",
                    details=trust_details,
                ),
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["source_summary"], None)
        self.assertEqual(
            events[-1]["blocking_issues"],
            [
                {
                    "code": api_codes.RECOVERY_HEAD_UNTRUSTED,
                    "message": (
                        "requested recovery head could not be trusted: latest suffix degraded"
                    ),
                    "details": trust_details,
                }
            ],
        )

    def test_run_recover_inspect_api_command_maps_chain_replay_failure_to_untrusted_head(
        self,
    ) -> None:
        args = RecoverArgs(
            scan=["/tmp/root"],
            passphrase="secret",
            extension_doc_hash="ab" * 32,
            quiet=True,
        )
        inspection = _extend_root_inspection(passphrase="secret", satisfied=True)
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.inspect_from_args",
                return_value=inspection,
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.plan_from_inspection",
                return_value=SimpleNamespace(import_documents=(object(),)),
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.recover_chain_entries",
                side_effect=ValueError("extension doc_hash was not found"),
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["source_summary"], None)
        self.assertEqual(
            events[-1]["blocking_issues"],
            [
                {
                    "code": api_codes.RECOVERY_HEAD_UNTRUSTED,
                    "message": "extension doc_hash was not found",
                    "details": {"stage": "replay"},
                }
            ],
        )

    def test_run_recover_inspect_api_command_preserves_root_authority_mismatch_code(self) -> None:
        args = RecoverArgs(
            scan=["/tmp/root"],
            passphrase="secret",
            extension_doc_hash="ab" * 32,
            quiet=True,
        )
        inspection = _extend_root_inspection(passphrase="secret", satisfied=True)
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.inspect_from_args",
                return_value=inspection,
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.plan_from_inspection",
                return_value=SimpleNamespace(import_documents=(object(),)),
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.recover_chain_entries",
                side_effect=ApiCommandError(
                    code="ROOT_AUTHORITY_MISMATCH",
                    message="embedded signing seed does not match the verified root AUTH authority",
                ),
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_recover_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            events[-1]["blocking_issues"],
            [
                {
                    "code": "ROOT_AUTHORITY_MISMATCH",
                    "message": (
                        "embedded signing seed does not match the verified root AUTH authority"
                    ),
                    "details": {},
                }
            ],
        )

    def test_api_inspect_extend_emits_ndjson_without_artifacts(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_extend_root_recovery(),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_published_extension_inventory",
                return_value=SimpleNamespace(
                    extensions=(
                        SimpleNamespace(
                            index=1,
                            dir_name="01",
                            doc_id_hex="deadbeefcafebabe",
                            doc_hash=b"\xca" * 32,
                        ),
                    ),
                    failure=None,
                ),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            extension_dir = root_dir / "extensions" / "01"
            scope_dir = Path(tmpdir) / "scope"
            extension_dir.mkdir(parents=True)
            scope_dir.mkdir(parents=True)
            (extension_dir / "qr_document-01-deadbeefcafebabe.pdf").write_bytes(b"x")
            (extension_dir / "recovery_document-01-deadbeefcafebabe.pdf").write_bytes(b"y")
            (scope_dir / "alpha.txt").write_text("alpha", encoding="utf-8")

            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "inspect",
                        "extend",
                        "--root-dir",
                        str(root_dir),
                        "--input",
                        str(scope_dir / "alpha.txt"),
                        "--base-dir",
                        str(scope_dir),
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["started", "phase", "progress", "result"],
        )
        self.assertEqual(events[-1]["command"], "extend")
        self.assertEqual(events[-1]["operation"], "inspect")
        self.assertEqual(events[-1]["input_kind"], "extended_root")
        self.assertEqual(events[-1]["doc_id"], "1111111111111111")
        self.assertEqual(events[-1]["discovered_extension_dirs"], [1])
        self.assertEqual(
            events[-1]["available_extensions"],
            [
                {
                    "index": 1,
                    "dir_name": "01",
                    "doc_id": "deadbeefcafebabe",
                    "doc_hash": "ca" * 32,
                }
            ],
        )
        self.assertEqual(
            events[-1]["selected_scope"],
            {
                "files": [str(scope_dir / "alpha.txt")],
                "directories": [],
                "base_dir": str(scope_dir),
                "file_count": 1,
                "total_bytes": 5,
                "input_origin": "file",
                "input_roots": [],
            },
        )
        self.assertEqual([event for event in events if event["type"] == "artifact"], [])

    def test_api_inspect_extend_surfaces_invalid_layout_as_blocking_issue(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_extend_root_recovery(),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            invalid_dir = root_dir / "extensions" / "001"
            invalid_dir.mkdir(parents=True)

            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "inspect",
                        "extend",
                        "--root-dir",
                        str(root_dir),
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["command"], "extend")
        self.assertEqual(events[-1]["operation"], "inspect")
        self.assertEqual(events[-1]["discovered_extension_dirs"], [])
        self.assertEqual(events[-1]["available_extensions"], [])
        self.assertEqual(events[-1]["blocking_issues"][0]["code"], "EXTENSION_LAYOUT_INVALID")

    def test_api_inspect_extend_emits_root_only_trust_metadata_fields(self) -> None:
        inspection = SimpleNamespace(
            doc_id="1111111111111111",
            input_label="Backup root directory",
            input_detail="/tmp/root",
            input_kind="extended_root",
            source_summary=None,
            frame_counts={"main": 0, "auth": 0, "shard": 0},
            root_doc_id="1111111111111111",
            root_doc_hash="22" * 32,
            chain_id="33" * 32,
            auth_status="verified",
            unlock={
                "mode": "passphrase",
                "passphrase_provided": True,
                "validated_shard_count": 0,
                "required_shard_threshold": None,
                "shard_share_count": None,
                "satisfied": True,
            },
            discovered_extension_dirs=(),
            validated_head_index=0,
            validated_head_doc_hash="22" * 32,
            available_extensions=(),
            ancestry_valid=True,
            validated_head_auth_status="verified",
            validated_head_root_authority_verified=True,
            signing_authority={"available": True, "satisfied": True, "source": "embedded_seed"},
            selected_scope=None,
            diff_summary=None,
            blocking_issues=(),
            root_dir="/tmp/root",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                return_value=SimpleNamespace(inspection=inspection),
            ),
            ndjson_session(stream=buffer),
        ):
            result = run_extend_inspect_api_command(ExtendArgs(root_dir="/tmp/root", quiet=True))

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["validated_head_index"], 0)
        self.assertEqual(events[-1]["validated_head_doc_hash"], "22" * 32)
        self.assertEqual(events[-1]["validated_head_auth_status"], "verified")
        self.assertEqual(events[-1]["validated_head_root_authority_verified"], True)
        self.assertEqual(events[-1]["available_extensions"], [])
        self.assertEqual(
            events[-1]["blocking_issues"][0]["code"],
            api_codes.EXTENSION_INPUT_REQUIRED,
        )

    def test_extend_unlock_payload_rejects_incomplete_shape(self) -> None:
        with self.assertRaises(ApiCommandError) as ctx:
            extend_api_handlers._unlock_payload(
                {
                    "mode": "passphrase",
                    "passphrase_provided": True,
                    "validated_shard_count": 0,
                    "required_shard_threshold": None,
                    "satisfied": True,
                }
            )

        self.assertEqual(ctx.exception.code, api_codes.RUNTIME_ERROR)
        self.assertEqual(ctx.exception.details, {"missing_fields": ["shard_share_count"]})

    def test_api_inspect_extend_preserves_null_validated_head_trust_fields(self) -> None:
        trust_details = {
            "stage": "replay",
            "failure_stage": "discovery",
            "failure_message": "missing required MAIN documents",
            "failure_head_index": 2,
            "failure_head_doc_hash": None,
            "failure_head_dir_name": "02",
            "latest_head_index": 2,
            "latest_head_doc_hash": None,
            "latest_head_dir_name": "02",
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": 0,
            "validated_head_doc_hash": "22" * 32,
            "validated_head_auth_status": None,
            "validated_head_root_authority_verified": None,
            "explicit_selection": False,
        }
        inspection = SimpleNamespace(
            doc_id="1111111111111111",
            input_label="Backup root directory",
            input_detail="/tmp/root",
            input_kind="extended_root",
            source_summary=None,
            frame_counts={"main": 0, "auth": 0, "shard": 0},
            root_doc_id="1111111111111111",
            root_doc_hash="22" * 32,
            chain_id="33" * 32,
            auth_status="verified",
            unlock={
                "mode": "passphrase",
                "passphrase_provided": True,
                "validated_shard_count": 0,
                "required_shard_threshold": None,
                "shard_share_count": None,
                "satisfied": True,
            },
            discovered_extension_dirs=(1,),
            validated_head_index=0,
            validated_head_doc_hash="22" * 32,
            available_extensions=(
                {
                    "index": 1,
                    "dir_name": "01",
                    "doc_id": "deadbeefcafebabe",
                    "doc_hash": "aa" * 32,
                },
            ),
            ancestry_valid=False,
            validated_head_auth_status=None,
            validated_head_root_authority_verified=None,
            signing_authority={"available": True, "satisfied": True, "source": "embedded_seed"},
            selected_scope=None,
            diff_summary=None,
            blocking_issues=(
                {
                    "code": api_codes.RECOVERY_HEAD_UNTRUSTED,
                    "message": (
                        "latest supplied recovery head could not be trusted: "
                        "missing required MAIN documents"
                    ),
                    "details": trust_details,
                },
            ),
            root_dir="/tmp/root",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                return_value=SimpleNamespace(inspection=inspection),
            ),
            ndjson_session(stream=buffer),
        ):
            result = run_extend_inspect_api_command(ExtendArgs(root_dir="/tmp/root", quiet=True))

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertIsNone(events[-1]["validated_head_auth_status"])
        self.assertIsNone(events[-1]["validated_head_root_authority_verified"])
        self.assertEqual(events[-1]["blocking_issues"][0]["details"], trust_details)
        self.assertEqual(
            [issue["code"] for issue in events[-1]["blocking_issues"]],
            [api_codes.RECOVERY_HEAD_UNTRUSTED, api_codes.EXTENSION_INPUT_REQUIRED],
        )

    def test_api_inspect_extend_rejects_incomplete_diff_summary(self) -> None:
        inspection = SimpleNamespace(
            doc_id="1111111111111111",
            input_label="Backup root directory",
            input_detail="/tmp/root",
            input_kind="standalone_root",
            source_summary=None,
            frame_counts={"main": 0, "auth": 0, "shard": 0},
            root_doc_id="1111111111111111",
            root_doc_hash="22" * 32,
            chain_id="33" * 32,
            auth_status="verified",
            unlock={
                "mode": "passphrase",
                "passphrase_provided": True,
                "validated_shard_count": 0,
                "required_shard_threshold": None,
                "shard_share_count": None,
                "satisfied": True,
            },
            discovered_extension_dirs=(),
            validated_head_index=0,
            validated_head_doc_hash="22" * 32,
            available_extensions=(),
            ancestry_valid=True,
            validated_head_auth_status="verified",
            validated_head_root_authority_verified=True,
            signing_authority={"available": True, "satisfied": True, "source": "embedded_seed"},
            selected_scope=_extend_selected_scope(files=["/tmp/root/alpha.txt"]),
            diff_summary={
                "new_paths": ["alpha.txt"],
                "unchanged_paths": [],
                "missing_paths": [],
            },
            blocking_issues=(),
            root_dir="/tmp/root",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                return_value=SimpleNamespace(inspection=inspection),
            ),
            ndjson_session(stream=buffer),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                run_extend_inspect_api_command(
                    ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/alpha.txt"], quiet=True)
                )

        self.assertEqual(ctx.exception.code, api_codes.RUNTIME_ERROR)
        self.assertEqual(ctx.exception.details, {"missing_field": "changed_paths"})

    def test_api_inspect_extend_preserves_recovery_head_untrusted_blocking_issue(self) -> None:
        trust_details = {
            "stage": "replay",
            "failure_stage": "discovery",
            "failure_message": "missing required MAIN documents",
            "failure_head_index": 2,
            "failure_head_doc_hash": None,
            "failure_head_dir_name": "02",
            "latest_head_index": 2,
            "latest_head_doc_hash": None,
            "latest_head_dir_name": "02",
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": 1,
            "validated_head_doc_hash": "aa" * 32,
            "validated_head_auth_status": "verified",
            "validated_head_root_authority_verified": True,
            "explicit_selection": False,
        }
        inspection = SimpleNamespace(
            doc_id="1111111111111111",
            input_label="Backup root directory",
            input_detail="/tmp/root",
            input_kind="extended_root",
            source_summary=None,
            frame_counts={"main": 0, "auth": 0, "shard": 0},
            root_doc_id="1111111111111111",
            root_doc_hash="22" * 32,
            chain_id="33" * 32,
            auth_status="verified",
            unlock={
                "mode": "passphrase",
                "passphrase_provided": True,
                "validated_shard_count": 0,
                "required_shard_threshold": None,
                "shard_share_count": None,
                "satisfied": True,
            },
            discovered_extension_dirs=(1,),
            validated_head_index=1,
            validated_head_doc_hash="aa" * 32,
            available_extensions=(
                {
                    "index": 1,
                    "dir_name": "01",
                    "doc_id": "deadbeefcafebabe",
                    "doc_hash": "aa" * 32,
                    "auth_status": "verified",
                    "root_authority_verified": True,
                },
            ),
            ancestry_valid=False,
            validated_head_auth_status="verified",
            validated_head_root_authority_verified=True,
            signing_authority={"available": True, "satisfied": True, "source": "embedded_seed"},
            selected_scope=None,
            diff_summary=_extend_diff_summary(changed_paths=["alpha.txt"]),
            blocking_issues=(
                {
                    "code": api_codes.RECOVERY_HEAD_UNTRUSTED,
                    "message": (
                        "latest supplied recovery head could not be trusted: "
                        "missing required MAIN documents"
                    ),
                    "details": trust_details,
                },
            ),
            root_dir="/tmp/root",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                return_value=SimpleNamespace(inspection=inspection),
            ),
            ndjson_session(stream=buffer),
        ):
            result = run_extend_inspect_api_command(
                ExtendArgs(
                    root_dir="/tmp/root",
                    input=["/tmp/root/alpha.txt"],
                    quiet=True,
                )
            )

        self.assertEqual(result, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["validated_head_doc_hash"], "aa" * 32)
        self.assertEqual(
            events[-1]["blocking_issues"],
            [
                {
                    "code": api_codes.RECOVERY_HEAD_UNTRUSTED,
                    "message": (
                        "latest supplied recovery head could not be trusted: "
                        "missing required MAIN documents"
                    ),
                    "details": trust_details,
                }
            ],
        )

    def test_run_extend_inspect_api_command_converts_preview_value_error_to_blocking_issue(
        self,
    ) -> None:
        args = ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"], quiet=True)
        inspection = SimpleNamespace(
            doc_id="1111111111111111",
            input_label="Backup root directory",
            input_detail="/tmp/root",
            input_kind="extended_root",
            source_summary=None,
            frame_counts={"main": 0, "auth": 0, "shard": 0},
            root_doc_id="1111111111111111",
            root_doc_hash="22" * 32,
            chain_id="33" * 32,
            auth_status="verified",
            unlock={
                "mode": "passphrase",
                "passphrase_provided": True,
                "validated_shard_count": 0,
                "required_shard_threshold": None,
                "shard_share_count": None,
                "satisfied": True,
            },
            discovered_extension_dirs=(),
            validated_head_index=None,
            validated_head_doc_hash=None,
            available_extensions=(),
            ancestry_valid=True,
            validated_head_auth_status=None,
            validated_head_root_authority_verified=None,
            signing_authority={"available": True, "satisfied": True, "source": "embedded_seed"},
            selected_scope=None,
            diff_summary=_extend_diff_summary(changed_paths=["updated.txt"]),
            blocking_issues=(),
            root_dir="/tmp/root",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                return_value=SimpleNamespace(inspection=inspection),
            ),
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.prepare_extend_run_from_state",
                side_effect=ValueError("bad shard scan"),
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_extend_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["blocking_issues"][0]["code"], "EXTENSION_LAYOUT_INVALID")
        self.assertEqual(events[-1]["blocking_issues"][0]["message"], "bad shard scan")
        self.assertEqual(events[-1]["blocking_issues"][0]["details"]["cause_code"], "INVALID_INPUT")

    def test_run_extend_inspect_api_command_preserves_delete_not_supported_issue(self) -> None:
        args = ExtendArgs(root_dir="/tmp/root", input=["/tmp/root/example.txt"], quiet=True)
        inspection = SimpleNamespace(
            doc_id="1111111111111111",
            input_label="Backup root directory",
            input_detail="/tmp/root",
            input_kind="extended_root",
            source_summary=None,
            frame_counts={"main": 0, "auth": 0, "shard": 0},
            root_doc_id="1111111111111111",
            root_doc_hash="22" * 32,
            chain_id="33" * 32,
            auth_status="verified",
            unlock={
                "mode": "passphrase",
                "passphrase_provided": True,
                "validated_shard_count": 0,
                "required_shard_threshold": None,
                "shard_share_count": None,
                "satisfied": True,
            },
            discovered_extension_dirs=(),
            validated_head_index=None,
            validated_head_doc_hash=None,
            available_extensions=(),
            ancestry_valid=True,
            validated_head_auth_status=None,
            validated_head_root_authority_verified=None,
            signing_authority={"available": True, "satisfied": True, "source": "embedded_seed"},
            selected_scope=None,
            diff_summary=_extend_diff_summary(
                changed_paths=["updated.txt"],
                missing_paths=["removed.txt"],
            ),
            blocking_issues=(),
            root_dir="/tmp/root",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                return_value=SimpleNamespace(inspection=inspection),
            ),
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.prepare_extend_run_from_state",
                side_effect=ApiCommandError(
                    code=api_codes.DELETE_NOT_SUPPORTED,
                    message=(
                        "selected scope omits previously backed paths; delete/rename is unsupported"
                    ),
                    details={"missing_paths": ["removed.txt"]},
                ),
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_extend_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            events[-1]["blocking_issues"],
            [
                {
                    "code": api_codes.DELETE_NOT_SUPPORTED,
                    "message": (
                        "selected scope omits previously backed paths; delete/rename is unsupported"
                    ),
                    "details": {"missing_paths": ["removed.txt"]},
                }
            ],
        )
        self.assertIsNone(events[-1]["chunk_reuse"])

    def test_run_extend_inspect_api_command_preflights_publish_target(self) -> None:
        args = ExtendArgs(
            root_dir="/tmp/request-root",
            input=["/tmp/request-root/example.txt"],
            quiet=True,
        )
        inspection = SimpleNamespace(
            doc_id="1111111111111111",
            input_label="Backup root directory",
            input_detail="/tmp/root",
            input_kind="standalone_root",
            source_summary=None,
            frame_counts={"main": 1, "auth": 1, "shard": 0},
            root_doc_id="1111111111111111",
            root_doc_hash="22" * 32,
            chain_id="33" * 32,
            auth_status="verified",
            unlock={
                "mode": "passphrase",
                "passphrase_provided": True,
                "validated_shard_count": 0,
                "required_shard_threshold": None,
                "shard_share_count": None,
                "satisfied": True,
            },
            discovered_extension_dirs=(),
            validated_head_index=0,
            validated_head_doc_hash="22" * 32,
            available_extensions=(),
            ancestry_valid=True,
            validated_head_auth_status="verified",
            validated_head_root_authority_verified=True,
            signing_authority={"available": True, "satisfied": True, "source": "embedded_seed"},
            selected_scope=None,
            diff_summary=_extend_diff_summary(changed_paths=["updated.txt"]),
            blocking_issues=(),
            root_dir="/tmp/inspection-root",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                return_value=SimpleNamespace(inspection=inspection),
            ),
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.prepare_extend_run_from_state",
                return_value=SimpleNamespace(next_index=1),
            ),
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.preflight_extension_publish_target",
                side_effect=ValueError("extensions path is not writable"),
            ) as preflight,
            ndjson_session(stream=buffer),
        ):
            exit_code = run_extend_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            events[-1]["blocking_issues"],
            [
                {
                    "code": api_codes.EXTENSION_PUBLISH_TARGET_INVALID,
                    "message": "extensions path is not writable",
                    "details": {"stage": "publish_target"},
                }
            ],
        )
        self.assertIsNone(events[-1]["chunk_reuse"])
        self.assertIsNone(events[-1]["estimated_extension_bytes"])
        preflight.assert_called_once_with("/tmp/inspection-root", index=1)

    def test_api_inspect_extend_emits_unlocked_diff_summary(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_extend_root_recovery(passphrase="secret", satisfied=True),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning._decode_root_manifest",
                return_value=(manifest, payload),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            scope_dir = Path(tmpdir) / "scope"
            root_dir.mkdir()
            scope_dir.mkdir()
            (scope_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
            alpha_mtime = int((scope_dir / "alpha.txt").stat().st_mtime)

            with (
                mock.patch(
                    "ethernity.cli.features.extend.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="alpha.txt",
                            size=5,
                            sha256=manifest.files[0].sha256,
                            mtime=alpha_mtime,
                            data=b"alpha",
                        ),
                    ),
                ),
                mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            ):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "inspect",
                        "extend",
                        "--root-dir",
                        str(root_dir),
                        "--input",
                        str(scope_dir / "alpha.txt"),
                        "--base-dir",
                        str(scope_dir),
                        "--passphrase",
                        "secret",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["source_summary"]["file_count"], 1)
        self.assertEqual(
            events[-1]["signing_authority"],
            {"available": True, "satisfied": True, "source": "embedded_seed"},
        )
        self.assertEqual(
            events[-1]["diff_summary"],
            {
                "new_paths": [],
                "changed_paths": [],
                "unchanged_paths": ["alpha.txt"],
                "missing_paths": [],
                "new_count": 0,
                "changed_count": 0,
                "unchanged_count": 1,
                "missing_count": 0,
            },
        )
        self.assertIsNone(events[-1]["chunk_reuse"])
        self.assertIsNone(events[-1]["estimated_extension_bytes"])
        self.assertEqual(events[-1]["blocking_issues"][0]["code"], "EXTENSION_NO_CHANGES")

    def test_api_inspect_extend_emits_preview_metrics_for_pending_changes(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_extend_root_recovery(passphrase="secret", satisfied=True),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning._decode_root_manifest",
                return_value=(manifest, payload),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            scope_dir = Path(tmpdir) / "scope"
            root_dir.mkdir()
            scope_dir.mkdir()
            (scope_dir / "alpha.txt").write_text("alpha-updated", encoding="utf-8")
            alpha_mtime = int((scope_dir / "alpha.txt").stat().st_mtime)

            with (
                mock.patch(
                    "ethernity.cli.features.extend.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="alpha.txt",
                            size=5,
                            sha256=manifest.files[0].sha256,
                            mtime=alpha_mtime - 1,
                            data=b"alpha",
                        ),
                    ),
                ),
                mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            ):
                expected_prepared = prepare_extend_run(
                    ExtendArgs(
                        root_dir=str(root_dir),
                        input=[str(scope_dir / "alpha.txt")],
                        base_dir=str(scope_dir),
                        passphrase="secret",
                        shard_count=0,
                    )
                )
                expected_encrypted = encrypt_prepared_extension_document(
                    expected_prepared,
                    chunker=default_extension_chunker,
                )
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "inspect",
                        "extend",
                        "--root-dir",
                        str(root_dir),
                        "--input",
                        str(scope_dir / "alpha.txt"),
                        "--base-dir",
                        str(scope_dir),
                        "--passphrase",
                        "secret",
                        "--shard-count",
                        "0",
                        "--qr-chunk-size",
                        "32",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            events[-1]["diff_summary"]["changed_paths"],
            ["alpha.txt"],
        )
        self.assertEqual(
            events[-1]["chunk_reuse"],
            {
                "reused_chunks": expected_encrypted.built.stats.reused_chunks,
                "new_chunks": expected_encrypted.built.stats.new_chunks,
            },
        )
        self.assertEqual(
            events[-1]["estimated_extension_bytes"],
            len(expected_encrypted.ciphertext),
        )
        self.assertEqual(
            events[-1]["resolved_policy"],
            {
                "passphrase": {
                    "mode": "plaintext",
                    "threshold": None,
                    "share_count": None,
                },
                "signing_key": {
                    "mode": "not-stored",
                    "threshold": None,
                    "share_count": None,
                },
                "recovery_kit_index": True,
                "qr_chunk_size": 32,
                "layout_debug_dir": None,
            },
        )

    def test_api_inspect_extend_reuses_stdin_scope_for_preview_metrics(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="data.txt", data=b"root", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_extend_root_recovery(passphrase="secret", satisfied=True),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning._decode_root_manifest",
                return_value=(manifest, payload),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning.extract_root_logical_state",
                return_value=(
                    LogicalFileState(
                        path="data.txt",
                        size=4,
                        sha256=manifest.files[0].sha256,
                        mtime=1,
                        data=b"root",
                    ),
                ),
            ),
            mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "extend",
                    "--root-dir",
                    str(root_dir),
                    "--input",
                    "-",
                    "--passphrase",
                    "secret",
                    "--shard-count",
                    "0",
                ],
                input="updated",
            )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["diff_summary"]["changed_paths"], ["data.txt"])
        self.assertEqual(events[-1]["blocking_issues"], [])
        self.assertIsNotNone(events[-1]["chunk_reuse"])
        self.assertIsNotNone(events[-1]["estimated_extension_bytes"])

    def test_api_inspect_extend_reports_ciphertext_size_preview_as_blocking_issue(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_extend_root_recovery(passphrase="secret", satisfied=True),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning._decode_root_manifest",
                return_value=(manifest, payload),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            scope_dir = Path(tmpdir) / "scope"
            root_dir.mkdir()
            scope_dir.mkdir()
            (scope_dir / "alpha.txt").write_text("alpha-updated", encoding="utf-8")
            alpha_mtime = int((scope_dir / "alpha.txt").stat().st_mtime)

            with (
                mock.patch(
                    "ethernity.cli.features.extend.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="alpha.txt",
                            size=5,
                            sha256=manifest.files[0].sha256,
                            mtime=alpha_mtime - 1,
                            data=b"alpha",
                        ),
                    ),
                ),
                mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
                mock.patch(
                    "ethernity.cli.features.extend.api_handlers.MAX_CIPHERTEXT_BYTES",
                    1,
                ),
            ):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "inspect",
                        "extend",
                        "--root-dir",
                        str(root_dir),
                        "--input",
                        str(scope_dir / "alpha.txt"),
                        "--base-dir",
                        str(scope_dir),
                        "--passphrase",
                        "secret",
                        "--shard-count",
                        "0",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertIsNone(events[-1]["chunk_reuse"])
        self.assertIsNone(events[-1]["estimated_extension_bytes"])
        blocking_issue = events[-1]["blocking_issues"][0]
        self.assertEqual(blocking_issue["code"], api_codes.EXTENSION_TOO_LARGE)
        self.assertEqual(blocking_issue["details"], {})
        self.assertRegex(
            blocking_issue["message"],
            r"extension ciphertext exceeds MAX_CIPHERTEXT_BYTES \(1\): \d+ bytes",
        )

    def test_api_inspect_extend_surfaces_runtime_readiness_failures(self) -> None:
        manifest, payload = build_manifest_and_payload(
            (PayloadPart(path="alpha.txt", data=b"alpha", mtime=1),),
            sealed=False,
            signing_seed=b"\x33" * 32,
            created_at=1.0,
            input_origin="file",
            input_roots=(),
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.extend.planning._inspect_root_recovery",
                return_value=_extend_root_recovery(passphrase="secret", satisfied=True),
            ),
            mock.patch(
                "ethernity.cli.features.extend.planning._decode_root_manifest",
                return_value=(manifest, payload),
            ),
        ):
            root_dir = Path(tmpdir) / "backup-root"
            scope_dir = Path(tmpdir) / "scope"
            root_dir.mkdir()
            scope_dir.mkdir()
            (scope_dir / "alpha.txt").write_text("alpha-updated", encoding="utf-8")
            alpha_mtime = int((scope_dir / "alpha.txt").stat().st_mtime)

            with (
                mock.patch(
                    "ethernity.cli.features.extend.planning.extract_root_logical_state",
                    return_value=(
                        LogicalFileState(
                            path="alpha.txt",
                            size=5,
                            sha256=manifest.files[0].sha256,
                            mtime=alpha_mtime - 1,
                            data=b"alpha",
                        ),
                    ),
                ),
                mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
                mock.patch(
                    "ethernity.cli.features.extend.api_handlers.resolve_extend_runtime",
                    side_effect=ApiCommandError(
                        code="EXTENSION_INVALID_POLICY",
                        message=(
                            "active design cannot render an inherited recovery_kit_index document"
                        ),
                    ),
                ),
            ):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "inspect",
                        "extend",
                        "--root-dir",
                        str(root_dir),
                        "--input",
                        str(scope_dir / "alpha.txt"),
                        "--base-dir",
                        str(scope_dir),
                        "--passphrase",
                        "secret",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertIsNone(events[-1]["chunk_reuse"])
        self.assertIsNone(events[-1]["estimated_extension_bytes"])
        self.assertIn(
            {
                "code": "EXTENSION_INVALID_POLICY",
                "message": "active design cannot render an inherited recovery_kit_index document",
                "details": {},
            },
            events[-1]["blocking_issues"],
        )

    def test_api_inspect_extend_validates_layout_debug_dir_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            resolved = _resolved_extend_state(root_dir)
            buffer = io.StringIO()
            with (
                mock.patch(
                    "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                    return_value=resolved,
                ),
                ndjson_session(stream=buffer),
            ):
                exit_code = run_extend_inspect_api_command(
                    ExtendArgs(
                        root_dir=str(root_dir),
                        layout_debug_dir=str(root_dir / "extensions" / "debug"),
                    )
                )

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        issue_codes = {issue["code"] for issue in events[-1]["blocking_issues"]}
        self.assertIn(api_codes.EXTENSION_INPUT_REQUIRED, issue_codes)
        self.assertIn(api_codes.EXTENSION_INVALID_POLICY, issue_codes)

    def test_api_inspect_extend_rejects_uncreatable_layout_debug_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            parent_file = Path(tmpdir) / "not-a-dir"
            parent_file.write_text("nope", encoding="utf-8")
            resolved = _resolved_extend_state(root_dir)
            buffer = io.StringIO()
            with (
                mock.patch(
                    "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                    return_value=resolved,
                ),
                ndjson_session(stream=buffer),
            ):
                exit_code = run_extend_inspect_api_command(
                    ExtendArgs(
                        root_dir=str(root_dir),
                        layout_debug_dir=str(parent_file / "layout-debug"),
                    )
                )

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        blocking_issues = events[-1]["blocking_issues"]
        self.assertIn(
            api_codes.EXTENSION_INVALID_POLICY,
            {issue["code"] for issue in blocking_issues},
        )
        self.assertTrue(
            any("--layout-debug-dir is not usable" in issue["message"] for issue in blocking_issues)
        )

    def test_run_extend_inspect_api_command_empty_layout_debug_dir_started_arg_is_null(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "backup-root"
            root_dir.mkdir()
            resolved = _resolved_extend_state(root_dir)
            buffer = io.StringIO()
            with (
                mock.patch(
                    "ethernity.cli.features.extend.api_handlers.resolve_extend_state",
                    return_value=resolved,
                ),
                ndjson_session(stream=buffer),
            ):
                exit_code = run_extend_inspect_api_command(
                    ExtendArgs(root_dir=str(root_dir), layout_debug_dir="")
                )

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertIsNone(events[0]["args"]["layout_debug_dir"])

    def test_api_recover_does_not_implicitly_read_stdin(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args, **_kwargs) -> int:
            captured["fallback_file"] = args.fallback_file
            captured["payloads_file"] = args.payloads_file
            captured["scan"] = list(args.scan or [])
            return 0

        with (
            mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            mock.patch(
                "ethernity.cli.features.api.command.run_recover_api_command",
                side_effect=_capture_args,
            ),
        ):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "recover",
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                    "--output",
                    "/tmp/recovered.bin",
                ],
                input="stdin should be ignored",
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(captured["fallback_file"])
        self.assertIsNone(captured["payloads_file"])
        self.assertEqual(captured["scan"], [])

    def test_api_recover_explicit_stdin_payloads_succeeds(self) -> None:
        payload_text = (V1_FIXTURE_ROOT / "main_payloads.txt").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "recovered.bin"
            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "recover",
                        "--payloads-file",
                        "-",
                        "--passphrase",
                        FIXTURE_PASSPHRASE,
                        "--output",
                        str(output_path),
                    ],
                    input=payload_text,
                )

            recovered = output_path.read_bytes()

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["command"], "recover")
        self.assertTrue(recovered)

    def test_api_recover_missing_shard_dir_emits_structured_error_code(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "recover",
                    "--payloads-file",
                    str(V1_FIXTURE_ROOT / "main_payloads.txt"),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                    "--output",
                    "/tmp/recovered.bin",
                    "--shard-dir",
                    "/no/such/shards",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], "SHARD_DIR_NOT_FOUND")

    def test_api_recover_missing_payload_file_emits_not_found(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "recover",
                    "--payloads-file",
                    "/no/such/payloads.txt",
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                    "--output",
                    "/tmp/recovered.bin",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["code"], api_codes.NOT_FOUND)
        self.assertEqual(
            events[-1]["details"]["path"],
            _expected_host_path("/no/such/payloads.txt"),
        )

    def test_api_recover_invalid_paper_emits_ndjson_error(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "recover",
                    "--paper",
                    "legal",
                    "--payloads-file",
                    str(payloads_file),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                    "--output",
                    "/tmp/recovered.bin",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("paper must be A4 or LETTER", events[-1]["message"])

    def test_api_recover_forwards_debug_limits(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        output_path = "/tmp/recovered.bin"
        captured: dict[str, object] = {}

        def _capture_execute(plan, **kwargs):
            captured["debug_max_bytes"] = kwargs["debug_max_bytes"]
            captured["debug_reveal_secrets"] = kwargs["debug_reveal_secrets"]
            captured["quiet"] = kwargs["quiet"]
            captured["debug"] = kwargs["debug"]
            captured["emit_file_artifacts"] = kwargs["emit_file_artifacts"]
            return SimpleNamespace(
                plan=SimpleNamespace(
                    output_path=output_path,
                    doc_id=b"\x11" * 8,
                    auth_status="verified",
                    input_label="QR payloads",
                    input_detail=str(payloads_file),
                ),
                manifest=SimpleNamespace(
                    format_version=1,
                    input_origin="file",
                    input_roots=(),
                    sealed=False,
                    payload_codec="raw",
                    payload_raw_len=7,
                    files=(),
                ),
                extracted=(),
                written_paths=(),
                file_payloads=(),
                output_path=output_path,
                output_path_kind="file",
                selected_extension_index=None,
                selected_extension_doc_hash=None,
            )

        with (
            mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.prepare_recover_plan",
                return_value=SimpleNamespace(allow_unsigned=False),
            ),
            mock.patch(
                "ethernity.cli.features.recover.api_handlers.execute_recover_plan",
                side_effect=_capture_execute,
            ),
        ):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "--debug",
                    "--debug-max-bytes",
                    "32",
                    "api",
                    "recover",
                    "--payloads-file",
                    str(payloads_file),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                    "--output",
                    output_path,
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["debug_max_bytes"], 32)
        self.assertFalse(captured["debug_reveal_secrets"])
        self.assertTrue(captured["debug"])
        self.assertFalse(captured["emit_file_artifacts"])
        self.assertTrue(captured["quiet"])

    def test_api_backup_without_inputs_emits_structured_error(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "backup"],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], "INPUT_REQUIRED")

    def test_api_extend_without_root_dir_emits_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "alpha.txt"
            input_path.write_text("alpha", encoding="utf-8")

            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "extend",
                        "--input",
                        str(input_path),
                    ],
                )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], "INPUT_REQUIRED")
        self.assertEqual(events[-1]["message"], "--root-dir is required for `ethernity api extend`")

    def test_api_inspect_extend_without_root_dir_emits_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "alpha.txt"
            input_path.write_text("alpha", encoding="utf-8")

            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "inspect",
                        "extend",
                        "--input",
                        str(input_path),
                    ],
                )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], "INPUT_REQUIRED")
        self.assertEqual(
            events[-1]["message"],
            "--root-dir is required for `ethernity api inspect extend`",
        )

    def test_api_backup_missing_input_file_emits_not_found(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "backup",
                    "--input",
                    "/no/such/input.txt",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["code"], api_codes.NOT_FOUND)
        self.assertEqual(events[-1]["details"]["path"], _expected_host_path("/no/such/input.txt"))

    def test_api_backup_invalid_paper_emits_ndjson_error(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "backup",
                    "--paper",
                    "legal",
                    "--input",
                    "-",
                ],
                input="payload",
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("paper must be A4 or LETTER", events[-1]["message"])

    def test_api_backup_invalid_signing_key_mode_emits_ndjson_error(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "backup",
                    "--input",
                    "-",
                    "--signing-key-mode",
                    "invalid-mode",
                ],
                input="payload",
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--signing-key-mode", events[-1]["message"])

    def test_api_backup_invalid_integer_option_emits_ndjson_error(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "backup",
                    "--input",
                    "-",
                    "--shard-threshold",
                    "two",
                ],
                input="payload",
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "error"])
        self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--shard-threshold must be an integer", events[-1]["message"])

    def test_api_backup_rejects_empty_passphrase(self) -> None:
        with self.runner.isolated_filesystem():
            input_path = Path("payload.bin")
            input_path.write_bytes(b"payload")

            with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "backup",
                        "--input",
                        str(input_path),
                        "--output-dir",
                        "out",
                        "--passphrase",
                        "",
                    ],
                )

            self.assertEqual(result.exit_code, 2)
            events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
            self._assert_valid_events(events)
            self.assertEqual(events[-1]["code"], api_codes.INVALID_INPUT)
            self.assertIn("passphrase cannot be empty", events[-1]["message"])
            self.assertFalse(Path("out").exists())

    def test_run_backup_api_command_emits_ndjson_artifacts(self) -> None:
        args = BackupArgs(
            config="config.toml",
            paper="A4",
            design="forge",
            input=["input.txt"],
            output_dir="/tmp/out",
            layout_debug_dir="/tmp/layout",
            passphrase="secret words",
            quiet=True,
        )
        input_file = InputFile(
            source_path=Path("input.txt"),
            relative_path="input.txt",
            data=b"payload",
            mtime=123,
        )
        result = BackupResult(
            doc_id=b"\x01" * 8,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            kit_index_path="/tmp/out/recovery_kit_index.pdf",
            shard_paths=("/tmp/out/shard-1.pdf",),
            signing_key_shard_paths=("/tmp/out/signing-key-shard-1.pdf",),
            passphrase_used="secret words",
        )
        buffer = io.StringIO()
        prepared = SimpleNamespace(
            args=args,
            input_files=(input_file,),
            input_origin="file",
            input_roots=(),
            plan=DocumentPlan(
                version=1,
                sealed=True,
                signing_seed_mode=SigningSeedMode.SHARDED,
                sharding=None,
            ),
        )
        with (
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.ensure_playwright_browsers"
            ) as ensure_playwright_browsers,
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.execute_prepared_backup",
                return_value=result,
            ),
            mock.patch(
                "pathlib.Path.exists",
                return_value=False,
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_backup_api_command(args)

        self.assertEqual(exit_code, 0)
        ensure_playwright_browsers.assert_called_once_with(quiet=True)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events], _contracts()["backup_mocked_event_types"]
        )
        self.assertEqual(events[0]["args"]["config"], "config.toml")
        self.assertEqual(events[0]["args"]["paper"], "A4")
        self.assertEqual(events[0]["args"]["design"], "forge")
        self.assertEqual(events[1]["kind"], "qr_document")
        self.assertEqual(events[2]["kind"], "recovery_document")
        self.assertEqual(events[3]["kind"], "recovery_kit_index")
        self.assertEqual(events[4]["kind"], "shard_document")
        self.assertEqual(events[5]["kind"], "signing_key_shard_document")
        self.assertEqual(events[6]["artifacts"]["qr_document"], result.qr_path)
        self.assertIsNone(events[6]["generated_passphrase"])

    def test_run_backup_api_command_started_reports_effective_passphrase_generation(self) -> None:
        args = BackupArgs(
            input=["input.txt"],
            output_dir="/tmp/out",
            quiet=True,
            passphrase_generate=False,
        )
        prepared = SimpleNamespace(
            args=args,
            input_files=(
                InputFile(
                    source_path=Path("input.txt"),
                    relative_path="input.txt",
                    data=b"payload",
                    mtime=123,
                ),
            ),
            input_origin="file",
            input_roots=(),
            plan=DocumentPlan(version=1, sealed=False, sharding=None),
        )
        result = BackupResult(
            doc_id=b"\x01" * 8,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            shard_paths=(),
            signing_key_shard_paths=(),
            passphrase_used="generated words here",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.execute_prepared_backup",
                return_value=result,
            ),
            mock.patch("pathlib.Path.exists", return_value=False),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_backup_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertTrue(events[0]["args"]["passphrase_generate"])
        self.assertFalse(events[0]["args"]["passphrase_generate_requested"])

    def test_run_backup_api_command_reports_effective_signing_key_mode(self) -> None:
        args = BackupArgs(
            input=["input.txt"],
            output_dir="/tmp/out",
            passphrase="secret words",
            quiet=True,
        )
        prepared = SimpleNamespace(
            args=args,
            input_files=(
                InputFile(
                    source_path=Path("input.txt"),
                    relative_path="input.txt",
                    data=b"payload",
                    mtime=123,
                ),
            ),
            input_origin="file",
            input_roots=(),
            plan=DocumentPlan(
                version=1,
                sealed=True,
                signing_seed_mode=SigningSeedMode.SHARDED,
                sharding=None,
            ),
        )
        result = BackupResult(
            doc_id=b"\x01" * 8,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            shard_paths=(),
            signing_key_shard_paths=(),
            passphrase_used="secret words",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.execute_prepared_backup",
                return_value=result,
            ),
            mock.patch("pathlib.Path.exists", return_value=False),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_backup_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["plan"]["signing_key_mode"], "embedded")
        self.assertIsNone(events[-1]["plan"]["signing_key_shard_threshold"])
        self.assertIsNone(events[-1]["plan"]["signing_key_shard_count"])

    def test_run_backup_api_command_only_emits_generated_passphrase(self) -> None:
        args = BackupArgs(
            input=["input.txt"],
            output_dir="/tmp/out",
            quiet=True,
        )
        prepared = SimpleNamespace(
            args=args,
            input_files=(
                InputFile(
                    source_path=Path("input.txt"),
                    relative_path="input.txt",
                    data=b"payload",
                    mtime=123,
                ),
            ),
            input_origin="file",
            input_roots=(),
            plan=DocumentPlan(version=1, sealed=False, sharding=None),
        )
        result = BackupResult(
            doc_id=b"\x01" * 8,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            shard_paths=(),
            signing_key_shard_paths=(),
            passphrase_used="generated words here",
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.execute_prepared_backup",
                return_value=result,
            ),
            mock.patch("pathlib.Path.exists", return_value=False),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_backup_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["generated_passphrase"], "generated words here")

    def test_run_mint_api_command_emits_ndjson_artifacts(self) -> None:
        args = MintArgs(
            payloads_file="main.txt",
            passphrase="secret words",
            shard_scan=["passphrase-a.pdf", "passphrase-b.png"],
            output_dir="/tmp/mint-out",
            shard_threshold=2,
            shard_count=3,
            quiet=True,
        )
        result = MintResult(
            doc_id=b"\x02" * 8,
            doc_hash=b"\x55" * 32,
            output_dir="/tmp/mint-out",
            shard_paths=("/tmp/mint-out/shard-1.pdf",),
            signing_key_shard_paths=("/tmp/mint-out/signing-key-shard-1.pdf",),
            signing_key_source="embedded signing seed",
            notes=("legacy note",),
            selected_extension_index=2,
            selected_extension_doc_hash="55" * 32,
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.mint.api_handlers.ensure_playwright_browsers"
            ) as ensure_playwright_browsers,
            mock.patch(
                "ethernity.cli.features.mint.api_handlers.execute_mint", return_value=result
            ),
            mock.patch("pathlib.Path.exists", return_value=False),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_mint_api_command(args)

        self.assertEqual(exit_code, 0)
        ensure_playwright_browsers.assert_called_once_with(quiet=True)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events], ["started", "artifact", "artifact", "result"]
        )
        self.assertEqual(events[0]["command"], "mint")
        self.assertEqual(events[0]["args"]["shard_scan"], ["passphrase-a.pdf", "passphrase-b.png"])
        self.assertEqual(events[1]["kind"], "shard_document")
        self.assertEqual(events[2]["kind"], "signing_key_shard_document")
        self.assertEqual(events[-1]["artifacts"]["shard_documents"], list(result.shard_paths))
        self.assertEqual(events[-1]["doc_hash"], "55" * 32)
        self.assertEqual(events[-1]["selected_extension_index"], 2)
        self.assertEqual(events[-1]["selected_extension_doc_hash"], "55" * 32)
        self.assertEqual(events[-1]["signing_key_source"], result.signing_key_source)
        self.assertEqual(events[-1]["notes"], list(result.notes))

    def test_run_extend_api_command_emits_ndjson_artifacts(self) -> None:
        args = ExtendArgs(
            config="config.toml",
            paper="A4",
            design="forge",
            root_dir="/tmp/request-root",
            input=["input.txt"],
            layout_debug_dir="/tmp/layout",
            passphrase="secret words",
            shard_scan=["shard-a.pdf"],
            shard_threshold=2,
            shard_count=3,
            signing_key_mode="sharded",
            signing_key_shard_threshold=2,
            signing_key_shard_count=2,
            quiet=True,
        )
        prepared = SimpleNamespace(
            inspection=SimpleNamespace(
                root_dir="/tmp/prepared-root",
                root_doc_id="11" * 8,
                root_doc_hash="22" * 32,
                chain_id="33" * 32,
                selected_scope=_extend_selected_scope(files=["input.txt"]),
                diff_summary=_extend_diff_summary(changed_paths=["input.txt"]),
            ),
            next_index=2,
            changed_paths=("input.txt",),
            new_paths=(),
        )
        result = SimpleNamespace(
            index=2,
            doc_id=b"\x44" * 8,
            doc_hash=b"\x55" * 32,
            final_dir=Path("/tmp/root/extensions/02"),
            qr_document_path=Path("/tmp/root/extensions/02/qr_document-02-deadbeefcafebabe.pdf"),
            recovery_document_path=Path(
                "/tmp/root/extensions/02/recovery_document-02-deadbeefcafebabe.pdf"
            ),
            recovery_kit_index_path=Path(
                "/tmp/root/extensions/02/recovery_kit_index-02-deadbeefcafebabe.pdf"
            ),
            shard_paths=(Path("/tmp/root/extensions/02/shard-02-deadbeefcafebabe-1-of-2.pdf"),),
            signing_key_shard_paths=(
                Path("/tmp/root/extensions/02/signing-key-shard-02-deadbeefcafebabe-1-of-2.pdf"),
            ),
        )
        executed = SimpleNamespace(
            prepared=prepared,
            runtime=SimpleNamespace(
                passphrase=ExtensionPassphraseShards(threshold=2, share_count=3),
                signing_key=ExtensionSigningKeyShards(threshold=2, share_count=2),
                kit_index_template_path=Path("/tmp/templates/recovery_kit_index.html.j2"),
                qr_chunk_size=512,
                layout_debug_dir="/tmp/layout",
            ),
            publish=SimpleNamespace(
                encrypted=SimpleNamespace(
                    built=SimpleNamespace(stats=SimpleNamespace(reused_chunks=1, new_chunks=2)),
                    ciphertext=b"ciphertext",
                )
            ),
            result=result,
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.ensure_playwright_browsers"
            ) as ensure_playwright_browsers,
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.prepare_extend_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.preflight_extension_publish_target"
            ) as preflight,
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.execute_prepared_extend",
                return_value=executed,
            ),
            mock.patch("pathlib.Path.exists", return_value=False),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_extend_api_command(args)

        self.assertEqual(exit_code, 0)
        ensure_playwright_browsers.assert_called_once_with(quiet=True)
        preflight.assert_called_once_with("/tmp/prepared-root", index=2)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events], _contracts()["extend_mocked_event_types"]
        )
        self.assertEqual(events[0]["args"]["root_dir"], "/tmp/request-root")
        self.assertEqual(events[0]["args"]["shard_scan"], ["shard-a.pdf"])
        progress_events = [event for event in events if event["type"] == "progress"]
        self.assertEqual(
            progress_events[0]["details"],
            {
                "root_dir": "/tmp/prepared-root",
                "next_index": 2,
                "changed_count": 1,
                "new_count": 0,
            },
        )
        artifacts = [event for event in events if event["type"] == "artifact"]
        self.assertEqual(artifacts[0]["kind"], "qr_document")
        self.assertEqual(artifacts[1]["kind"], "recovery_document")
        self.assertEqual(artifacts[2]["kind"], "recovery_kit_index")
        self.assertEqual(artifacts[3]["kind"], "shard_document")
        self.assertEqual(artifacts[4]["kind"], "signing_key_shard_document")
        self.assertEqual(events[-1]["extension_dir"], str(result.final_dir))
        self.assertEqual(events[-1]["artifacts"]["qr_document"], str(result.qr_document_path))
        self.assertEqual(
            events[-1]["resolved_policy"],
            {
                "passphrase": {
                    "mode": "extension-shards",
                    "threshold": 2,
                    "share_count": 3,
                },
                "signing_key": {
                    "mode": "extension-shards",
                    "threshold": 2,
                    "share_count": 2,
                },
                "recovery_kit_index": True,
                "qr_chunk_size": 512,
                "layout_debug_dir": "/tmp/layout",
            },
        )
        self.assertEqual(events[-1]["chunk_reuse"]["reused_chunks"], 1)
        self.assertEqual(events[-1]["extension_bytes"], len(b"ciphertext"))

    def test_run_extend_api_command_maps_publish_target_preflight_errors(self) -> None:
        args = ExtendArgs(
            root_dir="/tmp/request-root",
            input=["input.txt"],
            passphrase="secret words",
            quiet=True,
        )
        prepared = SimpleNamespace(
            inspection=SimpleNamespace(root_dir="/tmp/prepared-root"),
            next_index=2,
            changed_paths=("input.txt",),
            new_paths=(),
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.prepare_extend_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.preflight_extension_publish_target",
                side_effect=ValueError("canonical extension directory already exists: 02"),
            ) as preflight,
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.ensure_playwright_browsers"
            ) as ensure_playwright_browsers,
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.execute_prepared_extend"
            ) as execute_prepared_extend,
            ndjson_session(stream=buffer),
        ):
            with self.assertRaises(ApiCommandError) as ctx:
                run_extend_api_command(args)

        self.assertEqual(ctx.exception.code, api_codes.EXTENSION_PUBLISH_TARGET_INVALID)
        self.assertEqual(ctx.exception.details, {"stage": "publish_target"})
        self.assertIn("canonical extension directory already exists", str(ctx.exception))
        preflight.assert_called_once_with("/tmp/prepared-root", index=2)
        ensure_playwright_browsers.assert_not_called()
        execute_prepared_extend.assert_not_called()
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual([event["type"] for event in events], ["started", "phase"])

    def test_run_extend_api_command_emits_minimal_optional_artifact_shape(self) -> None:
        args = ExtendArgs(
            config="config.toml",
            root_dir="/tmp/root",
            input=["/tmp/root/file.txt"],
            passphrase="secret",
            quiet=True,
        )
        prepared = SimpleNamespace(
            inspection=SimpleNamespace(
                root_dir="/tmp/root",
                root_doc_id="11" * 8,
                root_doc_hash="22" * 32,
                chain_id="33" * 32,
                selected_scope=_extend_selected_scope(files=["/tmp/root/file.txt"]),
                diff_summary=_extend_diff_summary(new_paths=["file.txt"]),
            ),
            next_index=1,
            changed_paths=(),
            new_paths=("file.txt",),
        )
        result = SimpleNamespace(
            index=1,
            doc_id=b"\x44" * 8,
            doc_hash=b"\x55" * 32,
            final_dir=Path("/tmp/root/extensions/01"),
            qr_document_path=Path("/tmp/root/extensions/01/qr_document-01-deadbeefcafebabe.pdf"),
            recovery_document_path=Path(
                "/tmp/root/extensions/01/recovery_document-01-deadbeefcafebabe.pdf"
            ),
            recovery_kit_index_path=None,
            shard_paths=(),
            signing_key_shard_paths=(),
        )
        executed = SimpleNamespace(
            prepared=prepared,
            runtime=SimpleNamespace(
                passphrase=PlaintextPassphrase(),
                signing_key=SigningKeyNotStored(),
                kit_index_template_path=None,
                qr_chunk_size=256,
                layout_debug_dir=None,
            ),
            publish=SimpleNamespace(
                encrypted=SimpleNamespace(
                    built=SimpleNamespace(stats=SimpleNamespace(reused_chunks=0, new_chunks=1)),
                    ciphertext=b"ciphertext",
                )
            ),
            result=result,
        )
        buffer = io.StringIO()
        with (
            mock.patch("ethernity.cli.features.extend.api_handlers.ensure_playwright_browsers"),
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.prepare_extend_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.preflight_extension_publish_target"
            ) as preflight,
            mock.patch(
                "ethernity.cli.features.extend.api_handlers.execute_prepared_extend",
                return_value=executed,
            ),
            mock.patch("pathlib.Path.exists", return_value=False),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_extend_api_command(args)

        self.assertEqual(exit_code, 0)
        preflight.assert_called_once_with("/tmp/root", index=1)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events], _contracts()["extend_minimal_event_types"]
        )
        artifacts = [event for event in events if event["type"] == "artifact"]
        self.assertEqual(artifacts[0]["kind"], "qr_document")
        self.assertEqual(artifacts[1]["kind"], "recovery_document")
        self.assertIsNone(events[-1]["artifacts"]["recovery_kit_index"])
        self.assertEqual(events[-1]["artifacts"]["shard_documents"], [])
        self.assertEqual(events[-1]["artifacts"]["signing_key_shard_documents"], [])
        self.assertEqual(
            events[-1]["resolved_policy"],
            {
                "passphrase": {
                    "mode": "plaintext",
                    "threshold": None,
                    "share_count": None,
                },
                "signing_key": {
                    "mode": "not-stored",
                    "threshold": None,
                    "share_count": None,
                },
                "recovery_kit_index": False,
                "qr_chunk_size": 256,
                "layout_debug_dir": None,
            },
        )

    def test_run_compact_api_command_emits_ndjson_artifacts(self) -> None:
        args = CompactArgs(
            config="config.toml",
            paper="A4",
            design="forge",
            root_dir="/tmp/root",
            output_dir="/tmp/out",
            shard_fallback_file=["shard-a.txt"],
            shard_payloads_file=["shard-a.payloads"],
            shard_scan=["shard-a.pdf"],
            auth_fallback_file="auth.txt",
            auth_payloads_file="auth.payloads",
            layout_debug_dir="/tmp/layout",
            qr_chunk_size=32,
            passphrase="secret words",
            quiet=True,
        )
        result = BackupResult(
            doc_id=b"\x44" * 8,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            kit_index_path="/tmp/out/recovery_kit_index.pdf",
            shard_paths=("/tmp/out/shard-deadbeef-1-of-2.pdf",),
            signing_key_shard_paths=("/tmp/out/signing-key-shard-deadbeef-1-of-2.pdf",),
            passphrase_used=None,
            source_head_index=0,
            source_head_doc_hash="55" * 32,
            expected_head_doc_hash=None,
            freshness_scope=None,
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.compact.api_handlers.ensure_playwright_browsers"
            ) as ensure_playwright_browsers,
            mock.patch(
                "ethernity.cli.features.compact.api_handlers.run_compact",
                return_value=result,
            ),
            mock.patch("pathlib.Path.exists", return_value=False),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_compact_api_command(args)

        self.assertEqual(exit_code, 0)
        ensure_playwright_browsers.assert_called_once_with(quiet=True)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events], _contracts()["compact_mocked_event_types"]
        )
        self.assertEqual(events[0]["command"], "compact")
        self.assertEqual(events[0]["args"]["root_dir"], "/tmp/root")
        self.assertEqual(events[0]["args"]["shard_scan"], ["shard-a.pdf"])
        self.assertEqual(events[0]["args"]["auth_payloads_file"], "auth.payloads")
        phase_events = [event for event in events if event["type"] == "phase"]
        self.assertEqual(phase_events[0]["id"], "compact")
        progress_events = [event for event in events if event["type"] == "progress"]
        self.assertEqual([event["current"] for event in progress_events], [0, 1])
        self.assertEqual(progress_events[0]["details"]["root_dir"], "/tmp/root")
        self.assertEqual(progress_events[1]["details"]["output_dir"], "/tmp/out")
        artifact_events = [event for event in events if event["type"] == "artifact"]
        self.assertEqual(
            [event["kind"] for event in artifact_events],
            [
                "qr_document",
                "recovery_document",
                "recovery_kit_index",
                "shard_document",
                "signing_key_shard_document",
            ],
        )
        self.assertEqual(events[-1]["root_dir"], "/tmp/root")
        self.assertEqual(events[-1]["output_dir"], "/tmp/out")

    def test_api_compact_head_untrusted_emits_started_then_error_without_artifacts(self) -> None:
        trust_details = {
            "stage": "replay",
            "failure_stage": "discovery",
            "failure_message": "missing required MAIN documents",
            "failure_head_index": 2,
            "failure_head_doc_hash": None,
            "failure_head_dir_name": "02",
            "latest_head_index": 2,
            "latest_head_doc_hash": None,
            "latest_head_dir_name": "02",
            "requested_head_index": None,
            "requested_head_doc_hash": None,
            "validated_head_index": 0,
            "validated_head_doc_hash": "44" * 32,
            "validated_head_auth_status": None,
            "validated_head_root_authority_verified": None,
            "explicit_selection": False,
            "checkpoint_created": False,
        }

        with (
            mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            mock.patch("ethernity.cli.features.compact.api_handlers.ensure_playwright_browsers"),
            mock.patch(
                "ethernity.cli.features.compact.api_handlers.run_compact",
                side_effect=ApiCommandError(
                    code=api_codes.RECOVERY_HEAD_UNTRUSTED,
                    message=(
                        "latest supplied compact head could not be trusted; "
                        "no checkpoint was created: missing required MAIN documents"
                    ),
                    details=trust_details,
                ),
            ),
        ):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "compact",
                    "--root-dir",
                    "/tmp/root",
                    "--output-dir",
                    "/tmp/out",
                    "--passphrase",
                    "secret",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["started", "phase", "progress", "error"],
        )
        self.assertEqual(events[0]["command"], "compact")
        self.assertEqual(events[0]["args"]["root_dir"], "/tmp/root")
        self.assertEqual(events[1]["id"], "compact")
        self.assertEqual(events[2]["phase"], "compact")
        self.assertEqual(events[2]["current"], 0)
        self.assertEqual(events[-1]["code"], api_codes.RECOVERY_HEAD_UNTRUSTED)
        self.assertEqual(
            events[-1]["message"],
            (
                "latest supplied compact head could not be trusted; "
                "no checkpoint was created: missing required MAIN documents"
            ),
        )
        self.assertEqual(
            events[-1]["details"],
            {"error_type": "CommandError", **trust_details},
        )
        self.assertEqual([event for event in events if event["type"] == "artifact"], [])
        self.assertEqual([event for event in events if event["type"] == "result"], [])

    def test_run_compact_api_command_requires_root_dir_with_stable_code(self) -> None:
        buffer = io.StringIO()
        with ndjson_session(stream=buffer):
            with self.assertRaises(ApiCommandError) as ctx:
                run_compact_api_command(CompactArgs(output_dir="/tmp/out"))

        self.assertEqual(ctx.exception.code, api_codes.INPUT_REQUIRED)
        self.assertEqual(str(ctx.exception), "--root-dir is required for `ethernity api compact`")

    def test_api_inspect_mint_accepts_input_flags_without_output_dir(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args, **_kwargs) -> int:
            captured["payloads_file"] = args.payloads_file
            captured["output_dir"] = args.output_dir
            captured["shard_scan"] = list(args.shard_scan or [])
            captured["signing_key_shard_payloads_file"] = list(
                args.signing_key_shard_payloads_file or []
            )
            captured["signing_key_shard_scan"] = list(args.signing_key_shard_scan or [])
            return 0

        with (
            mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            mock.patch(
                "ethernity.cli.features.api.command.run_mint_inspect_api_command",
                side_effect=_capture_args,
            ),
        ):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "mint",
                    "--payloads-file",
                    str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "main_payloads.txt"),
                    "--shard-scan",
                    "passphrase-a.pdf",
                    "--shard-scan",
                    "passphrase-b.png",
                    "--signing-key-shard-payloads-file",
                    str(
                        V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT
                        / "signing_key_shard_payloads_threshold.txt"
                    ),
                    "--signing-key-shard-scan",
                    "signing-a.pdf",
                    "--signing-key-shard-scan",
                    "signing-b.png",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            captured["payloads_file"],
            str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "main_payloads.txt"),
        )
        self.assertIsNone(captured["output_dir"])
        self.assertEqual(captured["shard_scan"], ["passphrase-a.pdf", "passphrase-b.png"])
        self.assertEqual(
            captured["signing_key_shard_payloads_file"],
            [
                str(
                    V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT
                    / "signing_key_shard_payloads_threshold.txt"
                )
            ],
        )
        self.assertEqual(captured["signing_key_shard_scan"], ["signing-a.pdf", "signing-b.png"])

    def test_api_inspect_mint_rejects_layout_debug_dir_option(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "mint",
                    "--payloads-file",
                    str(V1_FIXTURE_ROOT / "main_payloads.txt"),
                    "--layout-debug-dir",
                    "/tmp/layout",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("No such option", result.output)
        self.assertIn("--layout-debug-dir", _strip_ansi(result.output))

    def test_api_inspect_mint_emits_success_with_valid_inputs(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "mint",
                    "--payloads-file",
                    str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "shard_payloads_threshold.txt"),
                    "--signing-key-shard-payloads-file",
                    str(
                        V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT
                        / "signing_key_shard_payloads_threshold.txt"
                    ),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["started", "phase", "progress", "result"],
        )
        self.assertNotIn("layout_debug_dir", events[0]["args"])
        self.assertEqual(events[-1]["command"], "mint")
        self.assertEqual(events[-1]["operation"], "inspect")
        self.assertEqual(events[-1]["unlock"]["validated_passphrase_shard_count"], 2)
        self.assertEqual(events[-1]["unlock"]["required_passphrase_threshold"], 2)
        self.assertEqual(events[-1]["unlock"]["satisfied"], True)
        self.assertEqual(events[-1]["frame_counts"]["signing_key_shard"], 1)
        self.assertEqual(events[-1]["signing_key"]["validated_shard_count"], 0)
        self.assertIsNone(events[-1]["signing_key"]["required_threshold"])
        self.assertEqual(events[-1]["signing_key"]["satisfied"], True)
        self.assertEqual(events[-1]["signing_key"]["source"], "embedded signing seed")
        self.assertEqual(events[-1]["mint_capabilities"]["can_mint_passphrase_shards"], True)
        self.assertEqual(events[-1]["mint_capabilities"]["can_mint_signing_key_shards"], True)
        self.assertIsNotNone(events[-1]["source_summary"])
        self.assertEqual([event for event in events if event["type"] == "artifact"], [])

    def test_api_inspect_mint_disables_passphrase_capability_when_replacement_inputs_missing(
        self,
    ) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "mint",
                    "--payloads-file",
                    str(V1_FIXTURE_ROOT / "main_payloads.txt"),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                    "--passphrase-replacement-count",
                    "1",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            events[-1]["blocking_issues"][0]["code"],
            "PASSPHRASE_REPLACEMENT_NOT_READY",
        )
        self.assertFalse(events[-1]["mint_capabilities"]["can_mint_passphrase_shards"])
        self.assertTrue(events[-1]["mint_capabilities"]["can_mint_signing_key_shards"])

    def test_api_inspect_mint_disables_signing_key_capability_when_replacement_inputs_missing(
        self,
    ) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "mint",
                    "--payloads-file",
                    str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "shard_payloads_threshold.txt"),
                    "--signing-key-replacement-count",
                    "1",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            events[-1]["blocking_issues"][0]["code"],
            "SIGNING_KEY_REPLACEMENT_NOT_READY",
        )
        self.assertTrue(events[-1]["mint_capabilities"]["can_mint_passphrase_shards"])
        self.assertFalse(events[-1]["mint_capabilities"]["can_mint_signing_key_shards"])

    def test_api_inspect_mint_disables_passphrase_capability_when_output_flag_disabled(
        self,
    ) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "mint",
                    "--payloads-file",
                    str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "shard_payloads_threshold.txt"),
                    "--signing-key-shard-payloads-file",
                    str(
                        V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT
                        / "signing_key_shard_payloads_threshold.txt"
                    ),
                    "--no-passphrase-shards",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertFalse(events[-1]["mint_capabilities"]["can_mint_passphrase_shards"])
        self.assertTrue(events[-1]["mint_capabilities"]["can_mint_signing_key_shards"])

    def test_api_inspect_mint_disables_signing_key_capability_when_output_flag_disabled(
        self,
    ) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "inspect",
                    "mint",
                    "--payloads-file",
                    str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "main_payloads.txt"),
                    "--shard-payloads-file",
                    str(V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT / "shard_payloads_threshold.txt"),
                    "--signing-key-shard-payloads-file",
                    str(
                        V1_1_SHARDED_SIGNING_SHARDED_FIXTURE_ROOT
                        / "signing_key_shard_payloads_threshold.txt"
                    ),
                    "--no-signing-key-shards",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertTrue(events[-1]["mint_capabilities"]["can_mint_passphrase_shards"])
        self.assertFalse(events[-1]["mint_capabilities"]["can_mint_signing_key_shards"])

    def test_run_mint_inspect_api_command_returns_blocking_issue_for_missing_auth(self) -> None:
        args = MintArgs(
            payloads_file="main.txt",
            shard_payloads_file=["shards.txt"],
            quiet=True,
        )
        inspection = SimpleNamespace(
            recovery=SimpleNamespace(
                doc_id=b"\x02" * 8,
                doc_hash=b"\x22" * 32,
                auth_status="missing",
                input_label="QR payloads",
                input_detail="main.txt",
                main_frames=(object(), object()),
                auth_frames=(),
                shard_frames=(object(), object()),
                unlock=SimpleNamespace(
                    validated_shard_count=2,
                    required_shard_threshold=2,
                    satisfied=True,
                ),
            ),
            manifest=None,
            source_summary=None,
            selected_extension_index=None,
            selected_extension_doc_hash=None,
            signing_key_frame_count=0,
            signing_key_validated_shard_count=0,
            signing_key_required_threshold=None,
            signing_key_satisfied=False,
            signing_key_source=None,
            mint_capabilities={
                "can_mint_passphrase_shards": False,
                "can_mint_signing_key_shards": False,
            },
            blocking_issues=(
                {
                    "code": "AUTH_REQUIRED",
                    "message": (
                        "minting requires an authenticated backup input with an AUTH payload"
                    ),
                    "details": {},
                },
            ),
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.mint.api_handlers.inspect_mint_inputs",
                return_value=inspection,
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_mint_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events],
            ["started", "phase", "progress", "result"],
        )
        self.assertEqual(events[-1]["operation"], "inspect")
        self.assertEqual(events[-1]["auth_status"], "missing")
        self.assertEqual(events[-1]["blocking_issues"][0]["code"], "AUTH_REQUIRED")
        self.assertFalse(events[-1]["unlock"]["satisfied"])
        self.assertEqual([event for event in events if event["type"] == "artifact"], [])

    def test_run_mint_inspect_api_command_reports_input_signing_key_frame_count(self) -> None:
        args = MintArgs(payloads_file="main.txt", shard_scan=["passphrase-a.pdf"], quiet=True)
        inspection = SimpleNamespace(
            recovery=SimpleNamespace(
                doc_id=b"\x03" * 8,
                doc_hash=b"\x33" * 32,
                auth_status="verified",
                input_label="QR payloads",
                input_detail="main.txt",
                main_frames=(object(), object()),
                auth_frames=(object(),),
                shard_frames=(object(), object()),
                unlock=SimpleNamespace(
                    validated_shard_count=2,
                    required_shard_threshold=2,
                    satisfied=True,
                ),
            ),
            manifest=object(),
            source_summary={"sealed": True},
            selected_extension_index=None,
            selected_extension_doc_hash=None,
            signing_key_frame_count=1,
            signing_key_validated_shard_count=0,
            signing_key_required_threshold=None,
            signing_key_satisfied=True,
            signing_key_source="embedded signing seed",
            mint_capabilities={
                "can_mint_passphrase_shards": True,
                "can_mint_signing_key_shards": True,
            },
            blocking_issues=(),
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.features.mint.api_handlers.inspect_mint_inputs",
                return_value=inspection,
            ),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_mint_inspect_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[0]["args"]["shard_scan"], ["passphrase-a.pdf"])
        self.assertEqual(events[2]["details"]["signing_key_shard_frame_count"], 1)
        self.assertEqual(events[-1]["frame_counts"]["signing_key_shard"], 1)
        self.assertIsNone(events[-1]["selected_extension_index"])
        self.assertIsNone(events[-1]["selected_extension_doc_hash"])
        self.assertEqual(events[-1]["signing_key"]["validated_shard_count"], 0)

    def test_api_mint_signing_key_shard_dir_error_is_structured(self) -> None:
        with mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "mint",
                    "--payloads-file",
                    "main.txt",
                    "--passphrase",
                    "secret words",
                    "--signing-key-shard-dir",
                    "/definitely/missing",
                ],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["code"], api_codes.SIGNING_KEY_SHARD_DIR_NOT_FOUND)

    def test_run_backup_api_command_emits_layout_debug_artifacts(self) -> None:
        args = BackupArgs(
            input=["input.txt"],
            output_dir="/tmp/out",
            layout_debug_dir="/tmp/layout-debug",
            quiet=True,
        )
        prepared = SimpleNamespace(
            args=args,
            input_files=(
                InputFile(
                    source_path=Path("input.txt"),
                    relative_path="input.txt",
                    data=b"payload",
                    mtime=123,
                ),
            ),
            input_origin="file",
            input_roots=(),
            plan=DocumentPlan(version=1, sealed=False, sharding=None),
        )
        result = BackupResult(
            doc_id=b"\x01" * 8,
            qr_path="/tmp/out/qr_document.pdf",
            recovery_path="/tmp/out/recovery_document.pdf",
            shard_paths=("/tmp/out/shard-01010101-1-of-1.pdf",),
            signing_key_shard_paths=(),
            passphrase_used=None,
        )
        buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            layout_dir = Path(tmpdir)
            args.layout_debug_dir = str(layout_dir)
            (layout_dir / "qr_document.layout.json").write_text("{}", encoding="utf-8")
            (layout_dir / "recovery_document.layout.json").write_text("{}", encoding="utf-8")
            (layout_dir / "shard-01-of-01.layout.json").write_text("{}", encoding="utf-8")
            with (
                mock.patch(
                    "ethernity.cli.features.backup.api_handlers.prepare_backup_run",
                    return_value=prepared,
                ),
                mock.patch(
                    "ethernity.cli.features.backup.api_handlers.execute_prepared_backup",
                    return_value=result,
                ),
                ndjson_session(stream=buffer),
            ):
                exit_code = run_backup_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        layout_artifacts = [event for event in events if event.get("kind") == "layout_debug_json"]
        self.assertEqual(len(layout_artifacts), 3)

    def test_execute_recover_plan_preserves_requested_and_selected_extension_metadata(self) -> None:
        manifest = EnvelopeManifest(
            format_version=1,
            created_at=0.0,
            input_origin="directory",
            input_roots=("selected",),
            sealed=False,
            signing_seed=None,
            payload_codec="raw",
            payload_raw_len=None,
            files=(ManifestFile(path="updated.txt", size=7, sha256=b"\x44" * 32, mtime=2),),
        )
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            passphrase="stable passphrase",
            auth_status="verified",
            allow_unsigned=False,
            output_path="/tmp/out",
            extension_index=1,
            extension_doc_hash=None,
        )

        with (
            mock.patch(
                "ethernity.cli.features.recover.service.decrypt_manifest_extract_selection",
                return_value=SimpleNamespace(
                    manifest=manifest,
                    extracted=[(manifest.files[0], b"updated")],
                    selected_extension_index=1,
                    selected_extension_doc_hash="ab" * 32,
                ),
            ),
            mock.patch(
                "ethernity.cli.features.recover.service.write_recovered_outputs",
                return_value=["/tmp/out/updated.txt"],
            ),
        ):
            execution = execute_recover_plan(cast(Any, plan), quiet=True, emit_file_artifacts=False)

        self.assertEqual(execution.requested_extension_index, 1)
        self.assertIsNone(execution.requested_extension_doc_hash)
        self.assertEqual(execution.selected_extension_index, 1)
        self.assertEqual(execution.selected_extension_doc_hash, "ab" * 32)

    def test_execute_recover_plan_emits_write_events_per_file(self) -> None:
        manifest = EnvelopeManifest(
            format_version=1,
            created_at=0.0,
            input_origin="directory",
            input_roots=("root",),
            sealed=True,
            signing_seed=None,
            payload_codec="raw",
            payload_raw_len=6,
            files=(
                ManifestFile(path="a.txt", size=3, sha256=b"\x00" * 32, mtime=1),
                ManifestFile(path="b.txt", size=3, sha256=b"\x01" * 32, mtime=2),
            ),
        )
        extracted = [
            (manifest.files[0], b"one"),
            (manifest.files[1], b"two"),
        ]
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            passphrase="stable passphrase",
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
        )
        buffer = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.cli.features.recover.service.decrypt_manifest_extract_selection",
                return_value=SimpleNamespace(
                    manifest=manifest,
                    extracted=extracted,
                    selected_extension_index=None,
                    selected_extension_doc_hash=None,
                ),
            ),
            ndjson_session(stream=buffer),
        ):
            plan.output_path = tmpdir
            execute_recover_plan(cast(Any, plan), quiet=True)

        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        write_events = [event for event in events if event.get("phase") == "write"]
        self.assertEqual([event["current"] for event in write_events], [1, 2])
        artifact_paths = [event["path"] for event in events if event["type"] == "artifact"]
        self.assertEqual(len(artifact_paths), 2)

    def test_execute_recover_plan_reports_directory_output_kind_for_single_directory_entry(
        self,
    ) -> None:
        manifest = EnvelopeManifest(
            format_version=1,
            created_at=0.0,
            input_origin="directory",
            input_roots=("root",),
            sealed=True,
            signing_seed=None,
            payload_codec="raw",
            payload_raw_len=3,
            files=(ManifestFile(path="a.txt", size=3, sha256=b"\x00" * 32, mtime=1),),
        )
        extracted = [(manifest.files[0], b"one")]
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            passphrase="stable passphrase",
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "ethernity.cli.features.recover.service.decrypt_manifest_extract_selection",
                return_value=SimpleNamespace(
                    manifest=manifest,
                    extracted=extracted,
                    selected_extension_index=None,
                    selected_extension_doc_hash=None,
                ),
            ):
                plan.output_path = tmpdir
                execution = execute_recover_plan(
                    cast(Any, plan), quiet=True, emit_file_artifacts=False
                )

        self.assertEqual(execution.output_path_kind, "directory")
        self.assertEqual(execution.output_path, tmpdir)

    def test_execute_recover_plan_reports_requested_root_for_nested_directory_outputs(self) -> None:
        manifest = EnvelopeManifest(
            format_version=1,
            created_at=0.0,
            input_origin="directory",
            input_roots=("root",),
            sealed=True,
            signing_seed=None,
            payload_codec="raw",
            payload_raw_len=3,
            files=(
                ManifestFile(path="nested/a.txt", size=3, sha256=b"\x00" * 32, mtime=1),
                ManifestFile(path="nested/b.txt", size=3, sha256=b"\x01" * 32, mtime=1),
            ),
        )
        extracted = [(manifest.files[0], b"one"), (manifest.files[1], b"two")]
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            passphrase="stable passphrase",
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "ethernity.cli.features.recover.service.decrypt_manifest_extract_selection",
                return_value=SimpleNamespace(
                    manifest=manifest,
                    extracted=extracted,
                    selected_extension_index=None,
                    selected_extension_doc_hash=None,
                ),
            ):
                plan.output_path = tmpdir
                execution = execute_recover_plan(
                    cast(Any, plan), quiet=True, emit_file_artifacts=False
                )

        self.assertEqual(execution.output_path_kind, "directory")
        self.assertEqual(execution.output_path, tmpdir)
        self.assertEqual(
            execution.written_paths,
            (
                str(Path(tmpdir) / "nested" / "a.txt"),
                str(Path(tmpdir) / "nested" / "b.txt"),
            ),
        )

    def test_execute_recover_plan_treats_existing_output_directory_as_directory(self) -> None:
        manifest = EnvelopeManifest(
            format_version=1,
            created_at=0.0,
            input_origin="file",
            input_roots=("payload.bin",),
            sealed=True,
            signing_seed=None,
            payload_codec="raw",
            payload_raw_len=3,
            files=(ManifestFile(path="payload.bin", size=3, sha256=b"\x00" * 32, mtime=1),),
        )
        extracted = [(manifest.files[0], b"one")]
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            passphrase="stable passphrase",
            auth_status="verified",
            allow_unsigned=False,
            output_path=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch(
                "ethernity.cli.features.recover.service.decrypt_manifest_extract_selection",
                return_value=SimpleNamespace(
                    manifest=manifest,
                    extracted=extracted,
                    selected_extension_index=None,
                    selected_extension_doc_hash=None,
                ),
            ):
                plan.output_path = tmpdir
                execution = execute_recover_plan(
                    cast(Any, plan),
                    quiet=True,
                    emit_file_artifacts=False,
                )

        self.assertEqual(execution.output_path_kind, "directory")
        self.assertEqual(execution.output_path, tmpdir)
        self.assertEqual(execution.written_paths, (str(Path(tmpdir) / "payload.bin"),))

    def test_api_recover_accepts_uppercase_shard_extensions(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args, **_kwargs) -> int:
            captured["shard_fallback_file"] = list(args.shard_fallback_file or [])
            return 0

        with tempfile.TemporaryDirectory() as tmpdir:
            shard_dir = Path(tmpdir)
            shard_path = shard_dir / "SHARD-01.TXT"
            shard_path.write_text("abcd", encoding="utf-8")
            with (
                mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
                mock.patch(
                    "ethernity.cli.features.api.command.run_recover_api_command",
                    side_effect=_capture_args,
                ),
            ):
                result = self.runner.invoke(
                    cli.app,
                    [
                        "--config",
                        str(DEFAULT_CONFIG_PATH),
                        "api",
                        "recover",
                        "--fallback-file",
                        str(V1_FIXTURE_ROOT / "main_fallback.txt"),
                        "--passphrase",
                        FIXTURE_PASSPHRASE,
                        "--output",
                        "/tmp/recovered.bin",
                        "--shard-dir",
                        str(shard_dir),
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["shard_fallback_file"], [str(shard_path)])

    def test_api_recover_passes_shard_scan_inputs(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args, **_kwargs) -> int:
            captured["shard_scan"] = list(args.shard_scan or [])
            return 0

        with (
            mock.patch("ethernity.cli.bootstrap.app.run_startup", return_value=False),
            mock.patch(
                "ethernity.cli.features.api.command.run_recover_api_command",
                side_effect=_capture_args,
            ),
        ):
            result = self.runner.invoke(
                cli.app,
                [
                    "--config",
                    str(DEFAULT_CONFIG_PATH),
                    "api",
                    "recover",
                    "--fallback-file",
                    str(V1_FIXTURE_ROOT / "main_fallback.txt"),
                    "--passphrase",
                    FIXTURE_PASSPHRASE,
                    "--output",
                    "/tmp/recovered.bin",
                    "--shard-scan",
                    "scan-a.pdf",
                    "--shard-scan",
                    "scan-b.pdf",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured["shard_scan"], ["scan-a.pdf", "scan-b.pdf"])

    def test_run_backup_emits_prepare_encrypt_and_render_progress(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        input_file = InputFile(
            source_path=Path("input.txt"),
            relative_path="input.txt",
            data=b"payload",
            mtime=123,
        )
        buffer = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.crypto.signing.generate_signing_keypair",
                return_value=(b"s" * 32, b"p" * 32),
            ),
            mock.patch(
                "ethernity.cli.features.backup.execution.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "stable passphrase"),
            ),
            mock.patch(
                "ethernity.cli.features.backup.execution.choose_frame_chunk_size",
                return_value=128,
            ),
            mock.patch(
                "ethernity.render.render_frames_to_pdf",
                side_effect=render_result_for_inputs,
            ),
            ndjson_session(stream=buffer),
        ):
            result = cli.run_backup(
                input_files=[input_file],
                base_dir=None,
                output_dir=str(Path(tmpdir) / "out"),
                plan=DocumentPlan(version=1, sealed=False, sharding=None),
                passphrase="stable passphrase",
                config=config,
                quiet=True,
            )

        self.assertTrue(result.qr_path.endswith("qr_document.pdf"))
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        phase_ids = [event["id"] for event in events if event["type"] == "phase"]
        self.assertIn("prepare", phase_ids)
        self.assertIn("encrypt", phase_ids)
        self.assertIn("shard", phase_ids)
        self.assertIn("render", phase_ids)
        render_progress = [
            event for event in events if event["type"] == "progress" and event["phase"] == "render"
        ]
        self.assertGreaterEqual(len(render_progress), 2)
        self.assertEqual(render_progress[-1]["current"], render_progress[-1]["total"])

    def test_run_backup_api_command_defers_artifacts_until_success(self) -> None:
        args = BackupArgs(
            input=["input.txt"],
            output_dir="/tmp/out",
            passphrase="secret words",
            quiet=True,
        )
        prepared = SimpleNamespace(
            args=args,
            input_files=(
                InputFile(
                    source_path=Path("input.txt"),
                    relative_path="input.txt",
                    data=b"payload",
                    mtime=123,
                ),
            ),
            input_origin="file",
            input_roots=(),
            plan=DocumentPlan(version=1, sealed=False, sharding=None),
        )
        buffer = io.StringIO()

        with (
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.features.backup.api_handlers.execute_prepared_backup",
                side_effect=RuntimeError("render failed"),
            ),
            ndjson_session(stream=buffer),
        ):
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                run_backup_api_command(args)

        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        artifact_kinds = [event["kind"] for event in events if event["type"] == "artifact"]
        self.assertEqual(artifact_kinds, [])

    def test_run_backup_debug_uses_stderr_during_ndjson_session(self) -> None:
        config = load_app_config(path=DEFAULT_CONFIG_PATH)
        input_file = InputFile(
            source_path=Path("input.txt"),
            relative_path="input.txt",
            data=b"payload",
            mtime=123,
        )
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch(
                "ethernity.crypto.signing.generate_signing_keypair",
                return_value=(b"s" * 32, b"p" * 32),
            ),
            mock.patch(
                "ethernity.cli.features.backup.execution.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "stable passphrase"),
            ),
            mock.patch(
                "ethernity.cli.features.backup.execution.choose_frame_chunk_size",
                return_value=128,
            ),
            mock.patch(
                "ethernity.render.render_frames_to_pdf",
                side_effect=render_result_for_inputs,
            ),
            mock.patch("ethernity.cli.features.backup.execution.print_backup_debug") as debug_mock,
            ndjson_session(stream=io.StringIO()),
        ):
            cli.run_backup(
                input_files=[input_file],
                base_dir=None,
                output_dir=str(Path(tmpdir) / "out"),
                plan=DocumentPlan(version=1, sealed=False, sharding=None),
                passphrase="stable passphrase",
                config=config,
                quiet=True,
                debug=True,
            )

        self.assertTrue(debug_mock.called)
        self.assertTrue(debug_mock.call_args.kwargs["stderr"])

    def test_execute_recover_plan_debug_uses_stderr_during_ndjson_session(self) -> None:
        plan = SimpleNamespace(
            ciphertext=b"ciphertext",
            passphrase="stable passphrase",
            auth_status="verified",
            allow_unsigned=False,
            output_path="/tmp/recovered.bin",
        )
        manifest = SimpleNamespace(input_origin="file", files=())
        extracted = []
        with (
            mock.patch(
                "ethernity.cli.features.recover.service.decrypt_manifest_extract_selection",
                return_value=SimpleNamespace(
                    manifest=manifest,
                    extracted=extracted,
                    selected_extension_index=None,
                    selected_extension_doc_hash=None,
                ),
            ),
            mock.patch(
                "ethernity.cli.features.recover.service.write_recovered_outputs",
                return_value=["/tmp/recovered.bin"],
            ),
            mock.patch("ethernity.cli.features.recover.service.print_recover_debug") as debug_mock,
            ndjson_session(stream=io.StringIO()),
        ):
            execute_recover_plan(
                cast(Any, plan),
                quiet=True,
                debug=True,
                debug_max_bytes=64,
                debug_reveal_secrets=True,
            )

        self.assertTrue(debug_mock.called)
        self.assertTrue(debug_mock.call_args.kwargs["stderr"])


if __name__ == "__main__":
    unittest.main()
