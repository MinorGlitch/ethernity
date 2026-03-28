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
from ethernity.cli.features.backup.api_handlers import run_backup_api_command
from ethernity.cli.features.config.api_handlers import (
    run_config_get_api_command,
    run_config_set_api_command,
)
from ethernity.cli.features.mint.api_handlers import (
    run_mint_api_command,
    run_mint_inspect_api_command,
)
from ethernity.cli.features.recover.service import execute_recover_plan
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.ndjson import ndjson_session
from ethernity.cli.shared.types import (
    BackupArgs,
    BackupResult,
    ConfigGetArgs,
    ConfigSetArgs,
    InputFile,
    MintArgs,
    MintResult,
)
from ethernity.config import CliDefaults, RecoverDefaults, load_app_config
from ethernity.config.install import ONBOARDING_FIELDS
from ethernity.config.paths import DEFAULT_CONFIG_PATH
from ethernity.core.models import DocumentPlan, SigningSeedMode
from ethernity.formats.envelope_types import EnvelopeManifest, ManifestFile

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


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _expected_host_path(path: str) -> str:
    return os.path.normpath(path)


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
        self.assertEqual(
            list(api_codes.STABLE_BLOCKING_ISSUE_CODES),
            contracts["stable_blocking_issue_codes"],
        )

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

    def test_api_recover_rescue_mode_with_valid_auth_emits_no_skip_warning(self) -> None:
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
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "error")
        self.assertEqual(events[0]["code"], "OUTPUT_REQUIRED")
        self.assertIn("--output is required", events[0]["message"])

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
        self.assertEqual(events[0]["code"], "OUTPUT_REQUIRED")

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
        self.assertEqual(events[-1]["unlock"]["satisfied"], False)
        self.assertTrue(events[-1]["blocking_issues"])
        self.assertEqual([event for event in events if event["type"] == "artifact"], [])

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
        self.assertEqual(events[0]["code"], "SHARD_DIR_NOT_FOUND")

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
        self.assertEqual(events[0]["code"], "INPUT_REQUIRED")

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
        self.assertEqual(events[0]["type"], "error")
        self.assertEqual(events[0]["code"], api_codes.INVALID_INPUT)
        self.assertIn("paper must be A4 or LETTER", events[0]["message"])

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
        self.assertEqual(events[0]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--signing-key-mode", events[0]["message"])

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
        self.assertEqual(events[0]["code"], api_codes.INVALID_INPUT)
        self.assertIn("--shard-threshold must be an integer", events[0]["message"])

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
            output_dir="/tmp/mint-out",
            shard_paths=("/tmp/mint-out/shard-1.pdf",),
            signing_key_shard_paths=("/tmp/mint-out/signing-key-shard-1.pdf",),
            signing_key_source="embedded signing seed",
            notes=("legacy note",),
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
        self.assertEqual(events[-1]["signing_key_source"], result.signing_key_source)
        self.assertEqual(events[-1]["notes"], list(result.notes))

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
                "ethernity.cli.features.recover.service.decrypt_manifest_and_extract",
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
                "ethernity.cli.features.recover.service.decrypt_manifest_and_extract",
                return_value=(manifest, extracted),
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
                "ethernity.cli.features.recover.service.decrypt_manifest_and_extract",
                return_value=(manifest, extracted),
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
                "ethernity.cli.features.recover.service.decrypt_manifest_and_extract",
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
            mock.patch("ethernity.render.render_frames_to_pdf"),
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
                "ethernity.cli.features.recover.service.decrypt_manifest_and_extract",
                return_value=(manifest, extracted),
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
