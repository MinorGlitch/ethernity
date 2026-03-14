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
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from jsonschema import validators
from jsonschema.exceptions import ValidationError
from typer.testing import CliRunner

from ethernity import cli
from ethernity.cli import api_codes
from ethernity.cli.core.types import (
    BackupArgs,
    BackupResult,
    ConfigGetArgs,
    ConfigSetArgs,
    InputFile,
    MintArgs,
    MintResult,
)
from ethernity.cli.flows.backup_api import run_backup_api_command
from ethernity.cli.flows.config_api import run_config_get_api_command, run_config_set_api_command
from ethernity.cli.flows.mint_api import run_mint_api_command
from ethernity.cli.flows.recover_service import execute_recover_plan
from ethernity.cli.ndjson import ndjson_session
from ethernity.config import CliDefaults, RecoverDefaults, load_app_config
from ethernity.core.models import DocumentPlan, SigningSeedMode
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "v1_0" / "golden" / "base64" / "file_no_shard"
DEFAULT_CONFIG_PATH = REPO_ROOT / "src" / "ethernity" / "config" / "config.toml"
CLI_API_SCHEMA_PATH = REPO_ROOT / "docs" / "cli_api.schema.json"
CLI_API_CONTRACTS_PATH = REPO_ROOT / "tests" / "fixtures" / "cli_api" / "contracts.json"
FIXTURE_PASSPHRASE = "stable-v1-baseline-passphrase"


@lru_cache(maxsize=1)
def _schema_validator():
    schema = json.loads(CLI_API_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator_cls = validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls(schema)


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

    def test_api_help_lists_recover(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False) as run_startup:
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "--help"],
            )
        self.assertEqual(result.exit_code, 0)
        run_startup.assert_not_called()
        self.assertIn("backup", result.output)
        self.assertIn("config", result.output)
        self.assertIn("mint", result.output)
        self.assertIn("recover", result.output)

    def test_api_config_get_ignores_bootstrap_default_config_when_no_explicit_config(self) -> None:
        captured: dict[str, object] = {}

        def _capture(args) -> int:
            captured["config"] = args.config
            return 0

        with mock.patch(
            "ethernity.cli.commands.api.run_config_get_api_command", side_effect=_capture
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
            "qr": {"error": "Q", "chunk_size": 768},
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
            "debug": {"max_bytes": None},
            "runtime": {"render_jobs": None},
        }
        options = {
            "template_designs": ["sentinel"],
            "page_sizes": ["A4", "LETTER"],
            "qr_error_correction": ["L", "M", "Q", "H"],
            "payload_codecs": ["auto", "raw", "gzip"],
            "qr_payload_codecs": ["raw", "base64"],
            "signing_key_modes": ["embedded", "sharded"],
            "onboarding_fields": ["page_size"],
        }
        snapshot = SimpleNamespace(
            path="/tmp/config.toml",
            source="user",
            values=values,
            options=options,
            onboarding={
                "needed": True,
                "configured_fields": [],
                "available_fields": ["page_size"],
            },
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.flows.config_api.get_api_config_snapshot", return_value=snapshot
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
            "debug": {"max_bytes": None},
            "runtime": {"render_jobs": None},
        }
        options = {
            "template_designs": ["sentinel"],
            "page_sizes": ["A4", "LETTER"],
            "qr_error_correction": ["L", "M", "Q", "H"],
            "payload_codecs": ["auto", "raw", "gzip"],
            "qr_payload_codecs": ["raw", "base64"],
            "signing_key_modes": ["embedded", "sharded"],
            "onboarding_fields": ["page_size"],
        }
        snapshot = SimpleNamespace(
            path="/tmp/config.toml",
            source="user",
            values=values,
            options=options,
            onboarding={
                "needed": False,
                "configured_fields": ["page_size"],
                "available_fields": ["page_size"],
            },
        )
        buffer = io.StringIO()
        with (
            mock.patch(
                "ethernity.cli.flows.config_api.apply_api_config_patch", return_value=snapshot
            ) as apply_patch,
            ndjson_session(stream=buffer),
            mock.patch(
                "ethernity.cli.flows.config_api.sys.stdin",
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
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["api", "config", "set", "--input-json", "-"],
                input="{not-json}",
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[-1]["code"], api_codes.CONFIG_JSON_INVALID)

    def test_api_command_does_not_run_startup(self) -> None:
        with (
            mock.patch(
                "ethernity.cli.app.run_startup", side_effect=AssertionError("startup-called")
            ) as run_startup,
            mock.patch("ethernity.cli.commands.api.run_backup_api_command", return_value=0),
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
                "ethernity.cli.app.load_cli_defaults", side_effect=ValueError("defaults-failed")
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
                "ethernity.cli.app.run_startup",
                side_effect=AssertionError("startup-called"),
            ) as run_startup,
            mock.patch(
                "ethernity.cli.commands.api.run_backup_api_command",
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

    def test_api_backup_flag_values_reach_command(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args: BackupArgs) -> int:
            captured["input"] = list(args.input or [])
            captured["output_dir"] = args.output_dir
            captured["output_dir_existing_parent"] = args.output_dir_existing_parent
            captured["shard_threshold"] = args.shard_threshold
            return 0

        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            with mock.patch(
                "ethernity.cli.commands.api.run_backup_api_command",
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

    def test_api_recover_emits_ndjson_and_writes_output(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "recovered.bin"
            with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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
            with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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

    def test_api_recover_rescue_mode_with_valid_auth_emits_no_skip_warning(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "recovered.bin"
            with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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
                        "--rescue-mode",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        warning_events = [event for event in events if event["type"] == "warning"]
        self.assertEqual(warning_events, [])

    def test_api_recover_without_output_emits_structured_error(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "error")
        self.assertEqual(events[0]["code"], "OUTPUT_REQUIRED")
        self.assertIn("--output is required", events[0]["message"])

    def test_api_recover_without_output_ignores_config_default(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        defaults = CliDefaults(recover=RecoverDefaults(output="/tmp/stale-output.bin"))
        with (
            mock.patch("ethernity.cli.app.run_startup", return_value=False),
            mock.patch("ethernity.cli.app.load_cli_defaults", return_value=defaults),
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
        self.assertEqual(events[0]["code"], "OUTPUT_REQUIRED")

    def test_api_recover_does_not_implicitly_read_stdin(self) -> None:
        captured: dict[str, object] = {}

        def _capture_args(args, **_kwargs) -> int:
            captured["fallback_file"] = args.fallback_file
            captured["payloads_file"] = args.payloads_file
            captured["scan"] = list(args.scan or [])
            return 0

        with (
            mock.patch("ethernity.cli.app.run_startup", return_value=False),
            mock.patch(
                "ethernity.cli.commands.api.run_recover_api_command",
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

    def test_api_recover_missing_shard_dir_emits_structured_error_code(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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
        self.assertEqual(events[0]["code"], "SHARD_DIR_NOT_FOUND")

    def test_api_recover_missing_payload_file_emits_not_found(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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

    def test_api_recover_invalid_paper_emits_ndjson_error(self) -> None:
        payloads_file = V1_FIXTURE_ROOT / "main_payloads.txt"
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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
        self.assertEqual(events[0]["type"], "error")
        self.assertEqual(events[0]["code"], api_codes.INVALID_INPUT)
        self.assertIn("paper must be A4 or LETTER", events[0]["message"])

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
            )

        with (
            mock.patch("ethernity.cli.app.run_startup", return_value=False),
            mock.patch(
                "ethernity.cli.flows.recover_api.prepare_recover_plan",
                return_value=SimpleNamespace(allow_unsigned=False),
            ),
            mock.patch(
                "ethernity.cli.flows.recover_api.execute_recover_plan",
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
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
            result = self.runner.invoke(
                cli.app,
                ["--config", str(DEFAULT_CONFIG_PATH), "api", "backup"],
            )

        self.assertEqual(result.exit_code, 2)
        events = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(events[0]["code"], "INPUT_REQUIRED")

    def test_api_backup_missing_input_file_emits_not_found(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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

    def test_api_backup_invalid_paper_emits_ndjson_error(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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
        self.assertEqual(events[0]["type"], "error")
        self.assertEqual(events[0]["code"], api_codes.INVALID_INPUT)
        self.assertIn("paper must be A4 or LETTER", events[0]["message"])

    def test_api_backup_invalid_signing_key_mode_emits_ndjson_error(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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
        self.assertEqual(events[0]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--signing-key-mode", events[0]["message"])

    def test_api_backup_invalid_integer_option_emits_ndjson_error(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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
        self.assertEqual(events[0]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--shard-threshold must be an integer", events[0]["message"])

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
                "ethernity.cli.flows.backup_api.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.flows.backup_api.execute_prepared_backup",
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
                "ethernity.cli.flows.backup_api.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.flows.backup_api.execute_prepared_backup",
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
                "ethernity.cli.flows.backup_api.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.flows.backup_api.execute_prepared_backup",
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
                "ethernity.cli.flows.backup_api.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.flows.backup_api.execute_prepared_backup",
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
            output_dir="/tmp/mint-out",
            shard_threshold=2,
            shard_count=3,
            quiet=True,
        )
        result = MintResult(
            doc_id=b"\x02" * 8,
            output_dir="/tmp/mint-out",
            shard_paths=("/tmp/mint-out/shard-1.pdf",),
            signing_key_shard_paths=("/tmp/mint-out/signing-key-shard-1.pdf",),
            signing_key_source="embedded signing seed",
            notes=("legacy note",),
        )
        buffer = io.StringIO()
        with (
            mock.patch("ethernity.cli.flows.mint_api.execute_mint", return_value=result),
            mock.patch("pathlib.Path.exists", return_value=False),
            ndjson_session(stream=buffer),
        ):
            exit_code = run_mint_api_command(args)

        self.assertEqual(exit_code, 0)
        events = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
        self._assert_valid_events(events)
        self.assertEqual(
            [event["type"] for event in events], ["started", "artifact", "artifact", "result"]
        )
        self.assertEqual(events[0]["command"], "mint")
        self.assertEqual(events[1]["kind"], "shard_document")
        self.assertEqual(events[2]["kind"], "signing_key_shard_document")
        self.assertEqual(events[-1]["artifacts"]["shard_documents"], list(result.shard_paths))
        self.assertEqual(events[-1]["signing_key_source"], result.signing_key_source)
        self.assertEqual(events[-1]["notes"], list(result.notes))

    def test_api_mint_signing_key_shard_dir_error_is_structured(self) -> None:
        with mock.patch("ethernity.cli.app.run_startup", return_value=False):
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
                    "ethernity.cli.flows.backup_api.prepare_backup_run",
                    return_value=prepared,
                ),
                mock.patch(
                    "ethernity.cli.flows.backup_api.execute_prepared_backup",
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
                "ethernity.cli.flows.recover_service.decrypt_manifest_and_extract",
                return_value=(manifest, extracted),
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
                "ethernity.cli.flows.recover_service.decrypt_manifest_and_extract",
                return_value=(manifest, extracted),
            ):
                plan.output_path = tmpdir
                execution = execute_recover_plan(
                    cast(Any, plan), quiet=True, emit_file_artifacts=False
                )

        self.assertEqual(execution.output_path_kind, "directory")
        self.assertEqual(execution.output_path, tmpdir)

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
                "ethernity.cli.flows.recover_service.decrypt_manifest_and_extract",
                return_value=(manifest, extracted),
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
                mock.patch("ethernity.cli.app.run_startup", return_value=False),
                mock.patch(
                    "ethernity.cli.commands.api.run_recover_api_command",
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
            mock.patch("ethernity.cli.app.run_startup", return_value=False),
            mock.patch(
                "ethernity.cli.commands.api.run_recover_api_command",
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
                "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "stable passphrase"),
            ),
            mock.patch(
                "ethernity.cli.flows.backup_flow.choose_frame_chunk_size",
                return_value=128,
            ),
            mock.patch("ethernity.render.render_frames_to_pdf"),
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
                "ethernity.cli.flows.backup_api.prepare_backup_run",
                return_value=prepared,
            ),
            mock.patch(
                "ethernity.cli.flows.backup_api.execute_prepared_backup",
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
                "ethernity.cli.flows.backup_flow.encrypt_bytes_with_passphrase",
                return_value=(b"ciphertext", "stable passphrase"),
            ),
            mock.patch(
                "ethernity.cli.flows.backup_flow.choose_frame_chunk_size",
                return_value=128,
            ),
            mock.patch("ethernity.render.render_frames_to_pdf"),
            mock.patch("ethernity.cli.flows.backup_flow.print_backup_debug") as debug_mock,
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
                "ethernity.cli.flows.recover_service.decrypt_manifest_and_extract",
                return_value=(manifest, extracted),
            ),
            mock.patch(
                "ethernity.cli.flows.recover_service.write_recovered_outputs",
                return_value=["/tmp/recovered.bin"],
            ),
            mock.patch("ethernity.cli.flows.recover_service.print_recover_debug") as debug_mock,
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
