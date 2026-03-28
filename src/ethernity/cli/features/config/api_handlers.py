#!/usr/bin/env python3
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

import json
import sys
from pathlib import Path

from ethernity.cli.shared import api_codes
from ethernity.cli.shared.events import emit_phase, emit_result
from ethernity.cli.shared.ndjson import SCHEMA_VERSION, ApiCommandError, emit_started
from ethernity.cli.shared.paths import expanduser_cli_path
from ethernity.cli.shared.types import ConfigGetArgs, ConfigSetArgs
from ethernity.config import ConfigPatchError, apply_api_config_patch, get_api_config_snapshot


def run_config_get_api_command(args: ConfigGetArgs) -> int:
    emit_started(
        command="config",
        schema_version=SCHEMA_VERSION,
        args={
            "operation": "get",
            "config": args.config,
            "input_json": None,
        },
    )
    emit_phase(phase="load", label="Loading config")
    try:
        snapshot = get_api_config_snapshot(args.config)
    except ConfigPatchError as exc:
        raise ApiCommandError(code=exc.code, message=exc.message, details=exc.details) from exc
    _emit_config_result(operation="get", snapshot=snapshot)
    return 0


def run_config_set_api_command(args: ConfigSetArgs) -> int:
    if not args.input_json:
        raise ApiCommandError(
            code=api_codes.CONFIG_INPUT_REQUIRED,
            message="--input-json is required for `ethernity api config set`",
        )
    emit_started(
        command="config",
        schema_version=SCHEMA_VERSION,
        args={
            "operation": "set",
            "config": args.config,
            "input_json": args.input_json,
        },
    )
    emit_phase(phase="validate", label="Validating config patch")
    patch = _read_config_patch(args.input_json)
    try:
        snapshot = apply_api_config_patch(args.config, patch)
    except ConfigPatchError as exc:
        raise ApiCommandError(code=exc.code, message=exc.message, details=exc.details) from exc
    emit_phase(phase="write", label="Writing config")
    _emit_config_result(operation="set", snapshot=snapshot)
    return 0


def _read_config_patch(input_json: str) -> dict[str, object]:
    normalized = expanduser_cli_path(input_json, preserve_stdin=True)
    try:
        if normalized == "-":
            text = sys.stdin.read()
        else:
            path = Path(normalized or "")
            text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ApiCommandError(
            code=api_codes.CONFIG_JSON_INVALID,
            message="config patch is not valid UTF-8",
            details={"path": normalized} if normalized not in {None, "-"} else {},
        ) from exc
    except OSError as exc:
        raise ApiCommandError(
            code=api_codes.IO_ERROR,
            message=str(exc),
            details={"path": normalized} if normalized not in {None, "-"} else {},
        ) from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiCommandError(
            code=api_codes.CONFIG_JSON_INVALID,
            message=f"invalid JSON patch: {exc.msg}",
            details={"line": exc.lineno, "column": exc.colno},
        ) from exc

    if not isinstance(payload, dict):
        raise ApiCommandError(
            code=api_codes.CONFIG_JSON_INVALID,
            message="config patch must be a JSON object",
        )
    return payload


def _emit_config_result(*, operation: str, snapshot) -> None:
    emit_result(
        command="config",
        operation=operation,
        path=snapshot.path,
        source=snapshot.source,
        status=snapshot.status,
        errors=list(snapshot.errors),
        values=snapshot.values,
        options=snapshot.options,
        onboarding=snapshot.onboarding,
    )


__all__ = ["run_config_get_api_command", "run_config_set_api_command"]
