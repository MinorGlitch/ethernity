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

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import click
import typer

from ethernity.cli.features.backup.api_handlers import run_backup_api_command
from ethernity.cli.features.compact.api_handlers import run_compact_api_command
from ethernity.cli.features.config.api_handlers import (
    run_config_get_api_command,
    run_config_set_api_command,
)
from ethernity.cli.features.extend.api_handlers import (
    run_extend_api_command,
    run_extend_inspect_api_command,
)
from ethernity.cli.features.mint.api_handlers import (
    run_mint_api_command,
    run_mint_inspect_api_command,
)
from ethernity.cli.features.recover.api_handlers import (
    run_recover_api_command,
    run_recover_inspect_api_command,
)
from ethernity.cli.features.recover.service import RecoverShardDirError, expand_recover_shard_dir
from ethernity.cli.shared import api_codes
from ethernity.cli.shared.common import _ctx_state, _paper_callback, _resolve_config_and_paper
from ethernity.cli.shared.events import started_event_emitted
from ethernity.cli.shared.ndjson import (
    SCHEMA_VERSION,
    ApiCommandError,
    emit_error,
    emit_started,
    error_code_for_exception,
    error_details_for_exception,
    ndjson_session,
)
from ethernity.cli.shared.paths import expanduser_cli_path
from ethernity.cli.shared.types import (
    BackupArgs,
    CompactArgs,
    ConfigGetArgs,
    ConfigSetArgs,
    ExtendArgs,
    MintArgs,
    RecoverArgs,
)
from ethernity.config import BackupDefaults

_API_HELP = (
    "Machine-readable CLI for GUI clients and automation.\n\n"
    "Commands under `ethernity api` write NDJSON events to stdout."
)

_RECOVER_HELP = (
    "Recover data from QR payloads or fallback text and stream NDJSON events.\n\n"
    "For GUI clients and automation. Requires --output."
)

_BACKUP_HELP = "Create backup files and stream NDJSON events.\n\nFor GUI clients and automation."

_MINT_HELP = (
    "Mint fresh shard PDFs for an existing backup and stream NDJSON events.\n\n"
    "For GUI clients and automation."
)

_EXTEND_HELP = (
    "Create a new extension update inside a backup root folder "
    "(writable backup root) and stream NDJSON events.\n\n"
    "For GUI clients and automation."
)

_COMPACT_HELP = (
    "Compact a backup root folder (writable backup root) into a fresh standalone backup "
    "and stream NDJSON events.\n\n"
    "For GUI clients and automation."
)

_CONFIG_HELP = (
    "Read or update app configuration and onboarding metadata via NDJSON.\n\n"
    "For GUI clients and automation."
)

_INSPECT_HELP = (
    "Inspect recover, extend, and mint readiness and stream NDJSON state/events.\n\n"
    "Inspect commands do not write files or emit artifact events."
)

BackupSigningKeyMode = Literal["embedded", "sharded"]
ExtensionSigningKeyMode = Literal["not-stored", "sharded"]


class _DisplayOnlyParamType(click.ParamType):
    def __init__(self, name: str) -> None:
        self.name = name

    def convert(self, value: str, param: click.Parameter | None, ctx: click.Context | None) -> str:
        return value


_INTEGER_HELP_TYPE = _DisplayOnlyParamType("INTEGER")
_MODE_HELP_TYPE = _DisplayOnlyParamType("MODE")
_POLICY_HELP_TYPE = _DisplayOnlyParamType("POLICY")


def register(app: typer.Typer) -> None:
    context_settings = {"help_option_names": ["-h", "--help"]}
    api_app = typer.Typer(
        help=_API_HELP,
        context_settings=context_settings,
    )
    config_app = typer.Typer(
        help=_CONFIG_HELP,
        context_settings=context_settings,
    )
    inspect_app = typer.Typer(
        help=_INSPECT_HELP,
        context_settings=context_settings,
    )
    api_app.command(name="backup", help=_BACKUP_HELP)(backup)
    api_app.command(name="compact", help=_COMPACT_HELP)(compact)
    api_app.command(name="extend", help=_EXTEND_HELP)(extend)
    api_app.command(name="mint", help=_MINT_HELP)(mint)
    api_app.command(name="recover", help=_RECOVER_HELP)(recover)
    inspect_app.command(
        name="recover",
        help="Inspect recover readiness via NDJSON.",
    )(inspect_recover)
    inspect_app.command(
        name="extend",
        help=(
            "Inspect whether an extension can be unlocked and applied "
            "(extension-chain readiness) via NDJSON."
        ),
    )(inspect_extend)
    inspect_app.command(name="mint", help="Inspect mint readiness via NDJSON.")(inspect_mint)
    config_app.command(name="get", help="Read the active config as NDJSON.")(config_get)
    config_app.command(name="set", help="Apply a JSON config patch and emit NDJSON.")(config_set)
    api_app.add_typer(inspect_app, name="inspect")
    api_app.add_typer(config_app, name="config")
    app.add_typer(api_app, name="api")


def _emit_fallback_started(started: tuple[str, dict[str, Any]] | None) -> None:
    if started is None or started_event_emitted():
        return
    command, args = started
    emit_started(command=command, schema_version=SCHEMA_VERSION, args=args)


def _run_ndjson_command(
    func: Callable[[], int | None],
    *,
    started: tuple[str, dict[str, Any]] | None = None,
) -> None:
    with ndjson_session():
        try:
            result = func()
        except typer.Exit:
            raise
        except (KeyboardInterrupt, click.Abort) as exc:
            _emit_fallback_started(started)
            emit_error(
                code=error_code_for_exception(exc),
                message="Cancelled by user",
                details={"error_type": type(exc).__name__},
            )
            raise typer.Exit(code=130) from exc
        except Exception as exc:
            _emit_fallback_started(started)
            details = {"error_type": type(exc).__name__}
            details.update(error_details_for_exception(exc))
            emit_error(
                code=error_code_for_exception(exc),
                message=str(exc),
                details=details,
            )
            raise typer.Exit(code=2) from exc
        if isinstance(result, int) and result != 0:
            raise typer.Exit(code=result)


def _expand_shard_dir(shard_dir: str | None) -> list[str]:
    try:
        return expand_recover_shard_dir(shard_dir)
    except RecoverShardDirError as exc:
        if exc.reason == "not_found":
            code = api_codes.SHARD_DIR_NOT_FOUND
        elif exc.reason == "invalid_type":
            code = api_codes.SHARD_DIR_INVALID
        else:
            code = api_codes.SHARD_DIR_EMPTY
        raise ApiCommandError(code=code, message=exc.message, details={"path": exc.path}) from exc


def _expand_optional_txt_dir(
    directory: str | None,
    *,
    not_found_code: str,
    invalid_code: str,
    empty_code: str,
    label: str,
) -> list[str]:
    if not directory:
        return []
    path = Path(expanduser_cli_path(directory, preserve_stdin=False) or "")
    if not path.exists():
        raise ApiCommandError(
            code=not_found_code,
            message=f"{label} directory not found: {directory}",
            details={"path": directory},
        )
    if not path.is_dir():
        raise ApiCommandError(
            code=invalid_code,
            message=f"{label}-dir must be a directory: {directory}",
            details={"path": directory},
        )
    files = sorted(
        child for child in path.iterdir() if child.is_file() and child.suffix.lower() == ".txt"
    )
    if not files:
        raise ApiCommandError(
            code=empty_code,
            message=f"no .txt files found in {label} directory: {directory}",
            details={"path": directory},
        )
    return [str(file_path) for file_path in files]


def _resolve_api_config_and_paper(
    ctx: typer.Context,
    config: str | None,
    paper: str | None,
) -> tuple[str | None, str | None]:
    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    try:
        paper_value = _paper_callback(paper_value)
    except typer.BadParameter as exc:
        raise ApiCommandError(code=api_codes.INVALID_INPUT, message=str(exc)) from exc
    return config_value, paper_value


def _explicit_api_config_value(ctx: typer.Context, config: str | None) -> str | None:
    if config is not None:
        return config
    state = _ctx_state(ctx)
    if state is not None and state.config_explicit:
        return state.config
    return None


def _parse_api_int_option(
    name: str,
    value: str | None,
    *,
    min_value: int | None = None,
) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise ApiCommandError(
            code=api_codes.INVALID_INPUT,
            message=f"{name} must be an integer",
            details={"option": name, "value": value},
        ) from exc
    if min_value is not None and parsed < min_value:
        raise ApiCommandError(
            code=api_codes.INVALID_INPUT,
            message=f"{name} must be >= {min_value}",
            details={"option": name, "value": value, "minimum": min_value},
        )
    return parsed


def _parse_api_extension_doc_hash_option(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ApiCommandError(
            code=api_codes.INVALID_INPUT,
            message="--extension-doc-hash must be a 32-byte lowercase hex value",
            details={"option": "--extension-doc-hash", "value": value},
        )
    return normalized


def _parse_backup_signing_key_mode(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in {"embedded", "sharded"}:
        raise ApiCommandError(
            code=api_codes.INVALID_INPUT,
            message="--signing-key-mode must be 'embedded' or 'sharded'",
            details={"option": "--signing-key-mode", "value": value},
        )
    return normalized


def _parse_extension_signing_key_mode(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in {"not-stored", "sharded"}:
        raise ApiCommandError(
            code=api_codes.EXTENSION_INVALID_POLICY,
            message="--signing-key-mode must be 'not-stored' or 'sharded'",
            details={"option": "--signing-key-mode", "value": value},
        )
    return normalized


def _parse_unlock_policy(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in {"self-contained", "reuse-root"}:
        raise ApiCommandError(
            code=api_codes.EXTENSION_INVALID_POLICY,
            message="--unlock-policy must be 'self-contained' or 'reuse-root'",
            details={"option": "--unlock-policy", "value": value},
        )
    return normalized


def _stringify_paths(values: list[Path] | None) -> list[str]:
    return [str(path) for path in values or []]


def _normalized_paper_for_started(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized if normalized in {"A4", "LETTER"} else None


def _optional_int_for_started(value: str | None, *, min_value: int = 0) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value, 10)
    except ValueError:
        return None
    if parsed < min_value:
        return None
    return parsed


def _non_empty_string_for_started(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return value if normalized else None


def _normalized_signing_key_mode_for_started(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in {"embedded", "sharded"} else None


def _normalized_extension_signing_key_mode_for_started(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in {"not-stored", "sharded"} else None


def _normalized_unlock_policy_for_started(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized if normalized in {"self-contained", "reuse-root"} else None


def _normalized_extension_doc_hash_for_started(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64:
        return None
    if any(char not in "0123456789abcdef" for char in normalized):
        return None
    return normalized


def _config_started_args(
    ctx: typer.Context,
    *,
    config: str | None,
    operation: str,
    input_json: str | None = None,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "config": _explicit_api_config_value(ctx, config),
        "input_json": input_json,
    }


def _recover_started_args_for_error(
    ctx: typer.Context,
    *,
    state: object | None,
    config: str | None,
    paper: str | None,
    fallback_file: str | None,
    payloads_file: str | None,
    scan: list[str] | None,
    passphrase: str | None,
    shard_fallback_file: list[str] | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    auth_fallback_file: str | None,
    auth_payloads_file: str | None,
    extension_index: str | None,
    extension_doc_hash: str | None,
    output: str | None,
    operation: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "config": _explicit_api_config_value(ctx, config),
        "paper": _normalized_paper_for_started(paper),
        "fallback_file": fallback_file,
        "payloads_file": payloads_file,
        "scan": list(scan or []),
        "has_passphrase": passphrase is not None,
        "shard_fallback_file": list(shard_fallback_file or []),
        "shard_payloads_file": list(shard_payloads_file or []),
        "shard_scan": list(shard_scan or []),
        "auth_fallback_file": auth_fallback_file,
        "auth_payloads_file": auth_payloads_file,
        "extension_index": _optional_int_for_started(extension_index),
        "extension_doc_hash": _normalized_extension_doc_hash_for_started(extension_doc_hash),
        "quiet": True,
        "debug": _state_debug_enabled(state),
    }
    if operation is not None:
        payload["operation"] = operation
    else:
        payload["output"] = output
    return payload


def _backup_started_args_for_error(
    ctx: typer.Context,
    *,
    state: object | None,
    config: str | None,
    paper: str | None,
    design: str | None,
    input: list[Path] | None,
    input_dir: list[Path] | None,
    base_dir: str | None,
    output_dir: str | None,
    qr_chunk_size: str | None,
    passphrase: str | None,
    passphrase_generate: bool,
    passphrase_words: str | None,
    sealed: bool,
    shard_threshold: str | None,
    shard_count: str | None,
    signing_key_mode: str | None,
    signing_key_shard_threshold: str | None,
    signing_key_shard_count: str | None,
    layout_debug_dir: str | None,
) -> dict[str, Any]:
    return {
        "config": _explicit_api_config_value(ctx, config),
        "paper": _normalized_paper_for_started(paper),
        "design": design or _state_design(state),
        "input": _stringify_paths(input),
        "input_dir": _stringify_paths(input_dir),
        "base_dir": base_dir,
        "output_dir": output_dir,
        "layout_debug_dir": layout_debug_dir,
        "qr_chunk_size": _optional_int_for_started(qr_chunk_size, min_value=1),
        "has_passphrase": passphrase is not None,
        "passphrase_generate": passphrase is None,
        "passphrase_generate_requested": passphrase_generate,
        "passphrase_words": _optional_int_for_started(passphrase_words),
        "sealed": sealed,
        "shard_threshold": _optional_int_for_started(shard_threshold),
        "shard_count": _optional_int_for_started(shard_count),
        "signing_key_mode": _normalized_signing_key_mode_for_started(signing_key_mode),
        "signing_key_shard_threshold": _optional_int_for_started(signing_key_shard_threshold),
        "signing_key_shard_count": _optional_int_for_started(signing_key_shard_count),
        "quiet": True,
        "debug": _state_debug_enabled(state),
    }


def _compact_started_args_for_error(
    ctx: typer.Context,
    *,
    state: object | None,
    config: str | None,
    paper: str | None,
    design: str | None,
    root_dir: str | None,
    output_dir: str | None,
    shard_fallback_file: list[str] | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    auth_fallback_file: str | None,
    auth_payloads_file: str | None,
    layout_debug_dir: str | None,
    qr_chunk_size: str | None,
    passphrase: str | None,
) -> dict[str, Any]:
    return {
        "config": _explicit_api_config_value(ctx, config),
        "paper": _normalized_paper_for_started(paper),
        "design": design or _state_design(state),
        "root_dir": root_dir,
        "output_dir": output_dir,
        "shard_fallback_file": list(shard_fallback_file or []),
        "shard_payloads_file": list(shard_payloads_file or []),
        "shard_scan": list(shard_scan or []),
        "auth_fallback_file": auth_fallback_file,
        "auth_payloads_file": auth_payloads_file,
        "layout_debug_dir": layout_debug_dir,
        "qr_chunk_size": _optional_int_for_started(qr_chunk_size, min_value=1),
        "has_passphrase": passphrase is not None,
        "quiet": True,
        "debug": _state_debug_enabled(state),
    }


def _extend_started_args_for_error(
    ctx: typer.Context,
    *,
    state: object | None,
    config: str | None,
    paper: str | None,
    design: str | None,
    root_dir: str | None,
    input: list[Path] | None,
    input_dir: list[Path] | None,
    base_dir: str | None,
    layout_debug_dir: str | None,
    qr_chunk_size: str | None,
    passphrase: str | None,
    shard_fallback_file: list[str] | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    unlock_policy: str | None,
    shard_threshold: str | None,
    shard_count: str | None,
    signing_key_mode: str | None,
    signing_key_shard_threshold: str | None,
    signing_key_shard_count: str | None,
    operation: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "config": _explicit_api_config_value(ctx, config),
        "paper": _normalized_paper_for_started(paper),
        "design": design or _state_design(state),
        "root_dir": root_dir,
        "input": _stringify_paths(input),
        "input_dir": _stringify_paths(input_dir),
        "base_dir": base_dir,
        "layout_debug_dir": _non_empty_string_for_started(layout_debug_dir),
        "qr_chunk_size": _optional_int_for_started(qr_chunk_size, min_value=1),
        "has_passphrase": passphrase is not None,
        "shard_fallback_file": list(shard_fallback_file or []),
        "shard_payloads_file": list(shard_payloads_file or []),
        "shard_scan": list(shard_scan or []),
        "unlock_policy": _normalized_unlock_policy_for_started(unlock_policy),
        "shard_threshold": _optional_int_for_started(shard_threshold),
        "shard_count": _optional_int_for_started(shard_count),
        "signing_key_mode": _normalized_extension_signing_key_mode_for_started(signing_key_mode),
        "signing_key_shard_threshold": _optional_int_for_started(signing_key_shard_threshold),
        "signing_key_shard_count": _optional_int_for_started(signing_key_shard_count),
        "quiet": True,
        "debug": _state_debug_enabled(state),
    }
    if operation is not None:
        payload["operation"] = operation
    return payload


def _mint_started_args_for_error(
    ctx: typer.Context,
    *,
    state: object | None,
    config: str | None,
    paper: str | None,
    design: str | None,
    fallback_file: str | None,
    payloads_file: str | None,
    scan: list[str] | None,
    passphrase: str | None,
    shard_fallback_file: list[str] | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    auth_fallback_file: str | None,
    auth_payloads_file: str | None,
    extension_index: str | None,
    extension_doc_hash: str | None,
    signing_key_shard_fallback_file: list[str] | None,
    signing_key_shard_payloads_file: list[str] | None,
    signing_key_shard_scan: list[str] | None,
    output_dir: str | None,
    layout_debug_dir: str | None,
    shard_threshold: str | None,
    shard_count: str | None,
    signing_key_shard_threshold: str | None,
    signing_key_shard_count: str | None,
    passphrase_replacement_count: str | None,
    signing_key_replacement_count: str | None,
    mint_passphrase_shards: bool,
    mint_signing_key_shards: bool,
    operation: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "config": _explicit_api_config_value(ctx, config),
        "paper": _normalized_paper_for_started(paper),
        "design": design or _state_design(state),
        "fallback_file": fallback_file,
        "payloads_file": payloads_file,
        "scan": list(scan or []),
        "has_passphrase": passphrase is not None,
        "shard_fallback_file": list(shard_fallback_file or []),
        "shard_payloads_file": list(shard_payloads_file or []),
        "shard_scan": list(shard_scan or []),
        "auth_fallback_file": auth_fallback_file,
        "auth_payloads_file": auth_payloads_file,
        "extension_index": _optional_int_for_started(extension_index),
        "extension_doc_hash": _normalized_extension_doc_hash_for_started(extension_doc_hash),
        "signing_key_shard_fallback_file": list(signing_key_shard_fallback_file or []),
        "signing_key_shard_payloads_file": list(signing_key_shard_payloads_file or []),
        "signing_key_shard_scan": list(signing_key_shard_scan or []),
        "shard_threshold": _optional_int_for_started(shard_threshold),
        "shard_count": _optional_int_for_started(shard_count),
        "signing_key_shard_threshold": _optional_int_for_started(signing_key_shard_threshold),
        "signing_key_shard_count": _optional_int_for_started(signing_key_shard_count),
        "passphrase_replacement_count": _optional_int_for_started(passphrase_replacement_count),
        "signing_key_replacement_count": _optional_int_for_started(signing_key_replacement_count),
        "mint_passphrase_shards": mint_passphrase_shards,
        "mint_signing_key_shards": mint_signing_key_shards,
        "quiet": True,
        "debug": _state_debug_enabled(state),
    }
    if operation is not None:
        payload["operation"] = operation
    else:
        payload["layout_debug_dir"] = layout_debug_dir
        payload["output_dir"] = output_dir
    return payload


def _state_debug_enabled(state: object | None) -> bool:
    return bool(getattr(state, "debug", False)) if state is not None else False


def _state_debug_max_bytes(state: object | None) -> int:
    return int(getattr(state, "debug_max_bytes", 0)) if state is not None else 0


def _state_debug_reveal_secrets(state: object | None) -> bool:
    return bool(getattr(state, "debug_reveal_secrets", False)) if state is not None else False


def _state_design(state: object | None) -> str | None:
    return cast(str | None, getattr(state, "design", None)) if state is not None else None


def _state_backup_defaults(state: object | None) -> BackupDefaults:
    defaults = getattr(state, "backup_defaults", None) if state is not None else None
    if isinstance(defaults, BackupDefaults):
        return defaults
    return BackupDefaults()


def _build_recover_api_args(
    *,
    state: object | None,
    config_value: str | None,
    paper_value: str | None,
    fallback_file: str | None,
    payloads_file: str | None,
    scan: list[str] | None,
    passphrase: str | None,
    shard_fallback_file: list[str] | None,
    shard_dir: str | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    auth_fallback_file: str | None,
    auth_payloads_file: str | None,
    extension_index: int | None,
    extension_doc_hash: str | None,
    output: str | None,
    allow_unsigned: bool,
) -> RecoverArgs:
    shard_files = list(shard_fallback_file or [])
    shard_files.extend(_expand_shard_dir(shard_dir))
    debug_max_bytes = getattr(state, "debug_max_bytes", 0) if state is not None else 0
    debug_reveal_secrets = (
        getattr(state, "debug_reveal_secrets", False) if state is not None else False
    )
    return RecoverArgs(
        config=config_value,
        paper=paper_value,
        fallback_file=fallback_file,
        payloads_file=payloads_file,
        scan=list(scan or []),
        passphrase=passphrase,
        shard_fallback_file=shard_files,
        shard_payloads_file=list(shard_payloads_file or []),
        shard_scan=list(shard_scan or []),
        auth_fallback_file=auth_fallback_file,
        auth_payloads_file=auth_payloads_file,
        extension_index=extension_index,
        extension_doc_hash=extension_doc_hash,
        output=output,
        allow_unsigned=allow_unsigned,
        assume_yes=True,
        debug_max_bytes=debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        quiet=True,
    )


def _run_recover_operation(
    *,
    ctx: typer.Context,
    state: object | None,
    config: str | None,
    paper: str | None,
    fallback_file: str | None,
    payloads_file: str | None,
    scan: list[str] | None,
    passphrase: str | None,
    shard_fallback_file: list[str] | None,
    shard_dir: str | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    auth_fallback_file: str | None,
    auth_payloads_file: str | None,
    extension_index: int | None,
    extension_doc_hash: str | None,
    output: str | None,
    allow_unsigned: bool,
    handler: Callable[..., int],
) -> int:
    config_value, paper_value = _resolve_api_config_and_paper(ctx, config, paper)
    extension_doc_hash_value = _parse_api_extension_doc_hash_option(extension_doc_hash)
    args = _build_recover_api_args(
        state=state,
        config_value=config_value,
        paper_value=paper_value,
        fallback_file=fallback_file,
        payloads_file=payloads_file,
        scan=list(scan or []),
        passphrase=passphrase,
        shard_fallback_file=list(shard_fallback_file or []),
        shard_dir=shard_dir,
        shard_payloads_file=list(shard_payloads_file or []),
        shard_scan=list(shard_scan or []),
        auth_fallback_file=auth_fallback_file,
        auth_payloads_file=auth_payloads_file,
        extension_index=extension_index,
        extension_doc_hash=extension_doc_hash_value,
        output=output,
        allow_unsigned=allow_unsigned,
    )
    return handler(args, debug=_state_debug_enabled(state))


def _build_mint_api_args(
    *,
    state: object | None,
    config_value: str | None,
    paper_value: str | None,
    design: str | None,
    fallback_file: str | None,
    payloads_file: str | None,
    scan: list[str] | None,
    passphrase: str | None,
    shard_fallback_file: list[str] | None,
    shard_dir: str | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    auth_fallback_file: str | None,
    auth_payloads_file: str | None,
    extension_index: int | None,
    extension_doc_hash: str | None,
    signing_key_shard_fallback_file: list[str] | None,
    signing_key_shard_dir: str | None,
    signing_key_shard_payloads_file: list[str] | None,
    signing_key_shard_scan: list[str] | None,
    output_dir: str | None,
    layout_debug_dir: str | None,
    shard_threshold: str | None,
    shard_count: str | None,
    signing_key_shard_threshold: str | None,
    signing_key_shard_count: str | None,
    passphrase_replacement_count: str | None,
    signing_key_replacement_count: str | None,
    mint_passphrase_shards: bool,
    mint_signing_key_shards: bool,
) -> MintArgs:
    passphrase_shard_files = list(shard_fallback_file or [])
    passphrase_shard_files.extend(
        _expand_optional_txt_dir(
            shard_dir,
            not_found_code=api_codes.SHARD_DIR_NOT_FOUND,
            invalid_code=api_codes.SHARD_DIR_INVALID,
            empty_code=api_codes.SHARD_DIR_EMPTY,
            label="shard",
        )
    )
    signing_key_shard_files = list(signing_key_shard_fallback_file or [])
    signing_key_shard_files.extend(
        _expand_optional_txt_dir(
            signing_key_shard_dir,
            not_found_code=api_codes.SIGNING_KEY_SHARD_DIR_NOT_FOUND,
            invalid_code=api_codes.SIGNING_KEY_SHARD_DIR_INVALID,
            empty_code=api_codes.SIGNING_KEY_SHARD_DIR_EMPTY,
            label="signing-key shard",
        )
    )
    extension_doc_hash_value = _parse_api_extension_doc_hash_option(extension_doc_hash)
    return MintArgs(
        config=config_value,
        paper=paper_value,
        design=design or (getattr(state, "design", None) if state is not None else None),
        fallback_file=fallback_file,
        payloads_file=payloads_file,
        scan=list(scan or []),
        passphrase=passphrase,
        shard_fallback_file=passphrase_shard_files,
        shard_payloads_file=list(shard_payloads_file or []),
        shard_scan=list(shard_scan or []),
        auth_fallback_file=auth_fallback_file,
        auth_payloads_file=auth_payloads_file,
        extension_index=extension_index,
        extension_doc_hash=extension_doc_hash_value,
        signing_key_shard_fallback_file=signing_key_shard_files,
        signing_key_shard_payloads_file=list(signing_key_shard_payloads_file or []),
        signing_key_shard_scan=list(signing_key_shard_scan or []),
        output_dir=output_dir,
        output_dir_existing_parent=True,
        layout_debug_dir=layout_debug_dir,
        shard_threshold=_parse_api_int_option("--shard-threshold", shard_threshold, min_value=1),
        shard_count=_parse_api_int_option("--shard-count", shard_count, min_value=1),
        signing_key_shard_threshold=_parse_api_int_option(
            "--signing-key-shard-threshold",
            signing_key_shard_threshold,
            min_value=1,
        ),
        signing_key_shard_count=_parse_api_int_option(
            "--signing-key-shard-count",
            signing_key_shard_count,
            min_value=1,
        ),
        passphrase_replacement_count=_parse_api_int_option(
            "--passphrase-replacement-count",
            passphrase_replacement_count,
            min_value=1,
        ),
        signing_key_replacement_count=_parse_api_int_option(
            "--signing-key-replacement-count",
            signing_key_replacement_count,
            min_value=1,
        ),
        mint_passphrase_shards=mint_passphrase_shards,
        mint_signing_key_shards=mint_signing_key_shards,
        quiet=True,
    )


def _run_mint_operation(
    *,
    ctx: typer.Context,
    state: object | None,
    config: str | None,
    paper: str | None,
    design: str | None,
    fallback_file: str | None,
    payloads_file: str | None,
    scan: list[str] | None,
    passphrase: str | None,
    shard_fallback_file: list[str] | None,
    shard_dir: str | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    auth_fallback_file: str | None,
    auth_payloads_file: str | None,
    extension_index: int | None,
    extension_doc_hash: str | None,
    signing_key_shard_fallback_file: list[str] | None,
    signing_key_shard_dir: str | None,
    signing_key_shard_payloads_file: list[str] | None,
    signing_key_shard_scan: list[str] | None,
    output_dir: str | None,
    layout_debug_dir: str | None,
    shard_threshold: str | None,
    shard_count: str | None,
    signing_key_shard_threshold: str | None,
    signing_key_shard_count: str | None,
    passphrase_replacement_count: str | None,
    signing_key_replacement_count: str | None,
    mint_passphrase_shards: bool,
    mint_signing_key_shards: bool,
    handler: Callable[..., int],
) -> int:
    config_value, paper_value = _resolve_api_config_and_paper(ctx, config, paper)
    args = _build_mint_api_args(
        state=state,
        config_value=config_value,
        paper_value=paper_value,
        design=design,
        fallback_file=fallback_file,
        payloads_file=payloads_file,
        scan=list(scan or []),
        passphrase=passphrase,
        shard_fallback_file=list(shard_fallback_file or []),
        shard_dir=shard_dir,
        shard_payloads_file=list(shard_payloads_file or []),
        shard_scan=list(shard_scan or []),
        auth_fallback_file=auth_fallback_file,
        auth_payloads_file=auth_payloads_file,
        extension_index=extension_index,
        extension_doc_hash=extension_doc_hash,
        signing_key_shard_fallback_file=list(signing_key_shard_fallback_file or []),
        signing_key_shard_dir=signing_key_shard_dir,
        signing_key_shard_payloads_file=list(signing_key_shard_payloads_file or []),
        signing_key_shard_scan=list(signing_key_shard_scan or []),
        output_dir=output_dir,
        layout_debug_dir=layout_debug_dir,
        shard_threshold=shard_threshold,
        shard_count=shard_count,
        signing_key_shard_threshold=signing_key_shard_threshold,
        signing_key_shard_count=signing_key_shard_count,
        passphrase_replacement_count=passphrase_replacement_count,
        signing_key_replacement_count=signing_key_replacement_count,
        mint_passphrase_shards=mint_passphrase_shards,
        mint_signing_key_shards=mint_signing_key_shards,
    )
    return handler(args, debug=_state_debug_enabled(state))


def _build_backup_api_args(
    *,
    state: object | None,
    config_value: str | None,
    paper_value: str | None,
    design: str | None,
    input: list[Path] | None,
    input_dir: list[Path] | None,
    base_dir: str | None,
    output_dir: str | None,
    qr_chunk_size: str | None,
    passphrase: str | None,
    passphrase_generate: bool,
    passphrase_words: str | None,
    sealed: bool,
    shard_threshold: str | None,
    shard_count: str | None,
    signing_key_mode: str | None,
    signing_key_shard_threshold: str | None,
    signing_key_shard_count: str | None,
    layout_debug_dir: str | None,
) -> BackupArgs:
    defaults = _state_backup_defaults(state)
    qr_chunk_size_value = _parse_api_int_option("--qr-chunk-size", qr_chunk_size)
    passphrase_words_value = _parse_api_int_option("--passphrase-words", passphrase_words)
    shard_threshold_cli = _parse_api_int_option("--shard-threshold", shard_threshold)
    shard_count_cli = _parse_api_int_option("--shard-count", shard_count)
    signing_key_mode_cli = _parse_backup_signing_key_mode(signing_key_mode)
    signing_key_shard_threshold_cli = _parse_api_int_option(
        "--signing-key-shard-threshold",
        signing_key_shard_threshold,
    )
    signing_key_shard_count_cli = _parse_api_int_option(
        "--signing-key-shard-count",
        signing_key_shard_count,
    )

    return BackupArgs(
        config=config_value,
        paper=paper_value,
        design=design or _state_design(state),
        input=[str(path) for path in (input or [])],
        input_dir=[str(path) for path in (input_dir or [])],
        base_dir=base_dir if base_dir is not None else defaults.base_dir,
        output_dir=output_dir if output_dir is not None else defaults.output_dir,
        output_dir_existing_parent=True,
        layout_debug_dir=layout_debug_dir,
        qr_chunk_size=qr_chunk_size_value,
        passphrase=passphrase,
        passphrase_generate=passphrase_generate,
        passphrase_words=passphrase_words_value,
        sealed=sealed,
        shard_threshold=(
            shard_threshold_cli if shard_threshold_cli is not None else defaults.shard_threshold
        ),
        shard_count=shard_count_cli if shard_count_cli is not None else defaults.shard_count,
        signing_key_mode=cast(
            BackupSigningKeyMode | None,
            signing_key_mode_cli if signing_key_mode_cli is not None else defaults.signing_key_mode,
        ),
        signing_key_shard_threshold=(
            signing_key_shard_threshold_cli
            if signing_key_shard_threshold_cli is not None
            else defaults.signing_key_shard_threshold
        ),
        signing_key_shard_count=(
            signing_key_shard_count_cli
            if signing_key_shard_count_cli is not None
            else defaults.signing_key_shard_count
        ),
        debug=_state_debug_enabled(state),
        debug_max_bytes=_state_debug_max_bytes(state),
        debug_reveal_secrets=_state_debug_reveal_secrets(state),
        assume_yes=True,
        quiet=True,
    )


def _build_extend_api_args(
    *,
    state: object | None,
    config_value: str | None,
    paper_value: str | None,
    design: str | None,
    root_dir: str | None,
    input: list[Path] | None,
    input_dir: list[Path] | None,
    base_dir: str | None,
    layout_debug_dir: str | None,
    qr_chunk_size: str | None,
    passphrase: str | None,
    shard_fallback_file: list[str] | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    unlock_policy: str | None,
    shard_threshold: str | None,
    shard_count: str | None,
    signing_key_mode: str | None,
    signing_key_shard_threshold: str | None,
    signing_key_shard_count: str | None,
) -> ExtendArgs:
    defaults = _state_backup_defaults(state)
    qr_chunk_size_cli = _parse_api_int_option(
        "--qr-chunk-size",
        qr_chunk_size,
        min_value=1,
    )
    unlock_policy_cli = _parse_unlock_policy(unlock_policy)
    shard_threshold_cli = _parse_api_int_option(
        "--shard-threshold",
        shard_threshold,
        min_value=0,
    )
    shard_count_cli = _parse_api_int_option("--shard-count", shard_count, min_value=0)
    signing_key_mode_cli = _parse_extension_signing_key_mode(signing_key_mode)
    signing_key_shard_threshold_cli = _parse_api_int_option(
        "--signing-key-shard-threshold",
        signing_key_shard_threshold,
        min_value=0,
    )
    signing_key_shard_count_cli = _parse_api_int_option(
        "--signing-key-shard-count",
        signing_key_shard_count,
        min_value=0,
    )
    return ExtendArgs(
        config=config_value,
        paper=paper_value,
        design=design or _state_design(state),
        root_dir=root_dir,
        input=[str(path) for path in (input or [])],
        input_dir=[str(path) for path in (input_dir or [])],
        base_dir=base_dir if base_dir is not None else defaults.base_dir,
        layout_debug_dir=layout_debug_dir,
        qr_chunk_size=qr_chunk_size_cli,
        passphrase=passphrase,
        shard_fallback_file=list(shard_fallback_file or []),
        shard_payloads_file=list(shard_payloads_file or []),
        shard_scan=list(shard_scan or []),
        unlock_policy=cast(
            Literal["self-contained", "reuse-root"] | None,
            unlock_policy_cli,
        ),
        shard_threshold=shard_threshold_cli,
        shard_count=shard_count_cli,
        signing_key_mode=cast(
            ExtensionSigningKeyMode | None,
            signing_key_mode_cli,
        ),
        signing_key_shard_threshold=signing_key_shard_threshold_cli,
        signing_key_shard_count=signing_key_shard_count_cli,
        quiet=True,
    )


def _build_compact_api_args(
    *,
    state: object | None,
    config_value: str | None,
    paper_value: str | None,
    design: str | None,
    root_dir: str | None,
    output_dir: str | None,
    shard_fallback_file: list[str] | None,
    shard_payloads_file: list[str] | None,
    shard_scan: list[str] | None,
    auth_fallback_file: str | None,
    auth_payloads_file: str | None,
    layout_debug_dir: str | None,
    qr_chunk_size: str | None,
    passphrase: str | None,
) -> CompactArgs:
    qr_chunk_size_cli = _parse_api_int_option("--qr-chunk-size", qr_chunk_size, min_value=1)
    return CompactArgs(
        config=config_value,
        paper=paper_value,
        design=design or _state_design(state),
        root_dir=root_dir,
        output_dir=output_dir,
        shard_fallback_file=shard_fallback_file,
        shard_payloads_file=shard_payloads_file,
        shard_scan=shard_scan,
        auth_fallback_file=auth_fallback_file,
        auth_payloads_file=auth_payloads_file,
        layout_debug_dir=layout_debug_dir,
        qr_chunk_size=qr_chunk_size_cli,
        passphrase=passphrase,
        quiet=True,
    )


def compact(
    ctx: typer.Context,
    root_dir: Annotated[
        str | None,
        typer.Option(
            "--root-dir",
            help="Backup root folder (writable backup root) to compact. Required in API mode.",
        ),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option("--output-dir", "-o", help="Where to write the compacted standalone backup."),
    ] = None,
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option("--shard-fallback-file", help="Fallback text file with shard lines."),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option("--shard-payloads-file", help="Text file with shard payload lines."),
    ] = None,
    shard_scan: Annotated[
        list[str] | None,
        typer.Option("--shard-scan", help="Passphrase shard document image/PDF to scan."),
    ] = None,
    auth_fallback_file: Annotated[
        str | None,
        typer.Option("--auth-fallback-file", help="Fallback text file for the AUTH payload."),
    ] = None,
    auth_payloads_file: Annotated[
        str | None,
        typer.Option("--auth-payloads-file", help="Text file with the AUTH payload line."),
    ] = None,
    layout_debug_dir: Annotated[
        str | None,
        typer.Option(
            "--layout-debug-dir", help="Write per-document layout diagnostics JSON files."
        ),
    ] = None,
    qr_chunk_size: Annotated[
        str | None,
        typer.Option(
            "--qr-chunk-size",
            help="Preferred ciphertext bytes per QR frame.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option("--passphrase", help="Passphrase to decrypt and compact with."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option("--paper", help="Paper size override (A4/Letter)."),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option("--design", help="Template design override for the compacted backup."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        config_value, paper_value = _resolve_api_config_and_paper(ctx, config, paper)
        args = _build_compact_api_args(
            state=state,
            config_value=config_value,
            paper_value=paper_value,
            design=design,
            root_dir=root_dir,
            output_dir=output_dir,
            shard_fallback_file=shard_fallback_file,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            auth_fallback_file=auth_fallback_file,
            auth_payloads_file=auth_payloads_file,
            layout_debug_dir=layout_debug_dir,
            qr_chunk_size=qr_chunk_size,
            passphrase=passphrase,
        )
        return run_compact_api_command(args, debug=_state_debug_enabled(state))

    _run_ndjson_command(
        _run,
        started=(
            "compact",
            _compact_started_args_for_error(
                ctx,
                state=state,
                config=config,
                paper=paper,
                design=design,
                root_dir=root_dir,
                output_dir=output_dir,
                shard_fallback_file=shard_fallback_file,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                auth_fallback_file=auth_fallback_file,
                auth_payloads_file=auth_payloads_file,
                layout_debug_dir=layout_debug_dir,
                qr_chunk_size=qr_chunk_size,
                passphrase=passphrase,
            ),
        ),
    )


def extend(
    ctx: typer.Context,
    root_dir: Annotated[
        str | None,
        typer.Option(
            "--root-dir",
            help="Backup root folder (writable backup root) to extend. Required in API mode.",
        ),
    ] = None,
    input: Annotated[
        list[Path] | None,
        typer.Option(
            "--input",
            "-i",
            help="File to include in selected scope (repeatable, use - for stdin).",
        ),
    ] = None,
    input_dir: Annotated[
        list[Path] | None,
        typer.Option("--input-dir", help="Directory to include in selected scope (repeatable)."),
    ] = None,
    base_dir: Annotated[
        str | None,
        typer.Option("--base-dir", help="Base path for stored relative names."),
    ] = None,
    qr_chunk_size: Annotated[
        str | None,
        typer.Option(
            "--qr-chunk-size",
            help="Preferred ciphertext bytes per QR frame.",
            metavar="INTEGER",
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option(
            "--passphrase",
            help="Passphrase to decrypt the root and encrypt the extension.",
        ),
    ] = None,
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-fallback-file",
            help="Passphrase shard recovery text file for unlocking the existing backup.",
        ),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-payloads-file",
            help="Passphrase shard QR payload file for unlocking the existing backup.",
        ),
    ] = None,
    shard_scan: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-scan",
            help="Passphrase shard image/PDF to scan for unlocking the existing backup.",
        ),
    ] = None,
    unlock_policy: Annotated[
        str | None,
        typer.Option(
            "--unlock-policy",
            help=(
                "Extension unlock artifact policy. Accepted values: self-contained, "
                "reuse-root. reuse-root uses the published or supplied root passphrase "
                "shard policy."
            ),
            click_type=_POLICY_HELP_TYPE,
        ),
    ] = None,
    shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--shard-threshold",
            help="Minimum passphrase shards needed to recover.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    shard_count: Annotated[
        str | None,
        typer.Option(
            "--shard-count",
            help="Total passphrase shard documents to create.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_mode: Annotated[
        str | None,
        typer.Option(
            "--signing-key-mode",
            help=(
                "Signing key handling for the new extension. Accepted values: not-stored, sharded."
            ),
            click_type=_MODE_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Signing-key shard threshold.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Signing-key shard count.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    layout_debug_dir: Annotated[
        str | None,
        typer.Option(
            "--layout-debug-dir", help="Write per-document layout diagnostics JSON files."
        ),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option("--paper", help="Paper size override (A4/Letter)."),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option("--design", help="Template design override for the new extension output."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        config_value, paper_value = _resolve_api_config_and_paper(ctx, config, paper)
        args = _build_extend_api_args(
            state=state,
            config_value=config_value,
            paper_value=paper_value,
            design=design,
            root_dir=root_dir,
            input=input,
            input_dir=input_dir,
            base_dir=base_dir,
            layout_debug_dir=layout_debug_dir,
            qr_chunk_size=qr_chunk_size,
            passphrase=passphrase,
            shard_fallback_file=shard_fallback_file,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            unlock_policy=unlock_policy,
            shard_threshold=shard_threshold,
            shard_count=shard_count,
            signing_key_mode=signing_key_mode,
            signing_key_shard_threshold=signing_key_shard_threshold,
            signing_key_shard_count=signing_key_shard_count,
        )
        return run_extend_api_command(args, debug=_state_debug_enabled(state))

    _run_ndjson_command(
        _run,
        started=(
            "extend",
            _extend_started_args_for_error(
                ctx,
                state=state,
                config=config,
                paper=paper,
                design=design,
                root_dir=root_dir,
                input=input,
                input_dir=input_dir,
                base_dir=base_dir,
                layout_debug_dir=layout_debug_dir,
                qr_chunk_size=qr_chunk_size,
                passphrase=passphrase,
                shard_fallback_file=shard_fallback_file,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                unlock_policy=unlock_policy,
                shard_threshold=shard_threshold,
                shard_count=shard_count,
                signing_key_mode=signing_key_mode,
                signing_key_shard_threshold=signing_key_shard_threshold,
                signing_key_shard_count=signing_key_shard_count,
            ),
        ),
    )


def config_get(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Read this config file instead of the user config."),
    ] = None,
) -> None:
    def _run() -> int:
        args = ConfigGetArgs(config=_explicit_api_config_value(ctx, config))
        return run_config_get_api_command(args)

    _run_ndjson_command(
        _run,
        started=("config", _config_started_args(ctx, config=config, operation="get")),
    )


def config_set(
    ctx: typer.Context,
    input_json: Annotated[
        str | None,
        typer.Option(
            "--input-json",
            help="JSON patch file path or - for stdin.",
        ),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Write this config file instead of the user config."),
    ] = None,
) -> None:
    def _run() -> int:
        args = ConfigSetArgs(
            config=_explicit_api_config_value(ctx, config),
            input_json=input_json,
        )
        return run_config_set_api_command(args)

    _run_ndjson_command(
        _run,
        started=(
            "config",
            _config_started_args(
                ctx,
                config=config,
                operation="set",
                input_json=input_json,
            ),
        ),
    )


def recover(
    ctx: typer.Context,
    fallback_file: Annotated[
        str | None,
        typer.Option("--fallback-file", "-f", help="Main recovery text (fallback, z-base-32)."),
    ] = None,
    payloads_file: Annotated[
        str | None,
        typer.Option("--payloads-file", help="Main QR payloads (one per line)."),
    ] = None,
    scan: Annotated[
        list[str] | None,
        typer.Option("--scan", help="Scan path (image/PDF/dir, repeatable)."),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option("--passphrase", help="Passphrase to decrypt with."),
    ] = None,
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option("--shard-fallback-file", help="Shard recovery text file (repeatable)."),
    ] = None,
    shard_dir: Annotated[
        str | None,
        typer.Option("--shard-dir", help="Directory containing shard text files."),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option("--shard-payloads-file", help="Shard QR payload file (repeatable)."),
    ] = None,
    shard_scan: Annotated[
        list[str] | None,
        typer.Option("--shard-scan", help="Shard scan path (image/PDF/dir, repeatable)."),
    ] = None,
    auth_fallback_file: Annotated[
        str | None,
        typer.Option("--auth-fallback-file", help="Auth recovery text (fallback, z-base-32)."),
    ] = None,
    auth_payloads_file: Annotated[
        str | None,
        typer.Option("--auth-payloads-file", help="Auth QR payloads (one per line)."),
    ] = None,
    extension_index: Annotated[
        str | None,
        typer.Option(
            "--extension-index",
            help="Recover through a specific extension index (0 = root only).",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    extension_doc_hash: Annotated[
        str | None,
        typer.Option(
            "--extension-doc-hash",
            help="Recover through the extension with this authenticated doc hash.",
        ),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Output file or directory path. Required in API mode."),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option("--paper", help="Paper size override (A4/Letter)."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        return _run_recover_operation(
            ctx=ctx,
            state=state,
            config=config,
            paper=paper,
            fallback_file=fallback_file,
            payloads_file=payloads_file,
            scan=scan,
            passphrase=passphrase,
            shard_fallback_file=shard_fallback_file,
            shard_dir=shard_dir,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            auth_fallback_file=auth_fallback_file,
            auth_payloads_file=auth_payloads_file,
            extension_index=_parse_api_int_option(
                "--extension-index",
                extension_index,
                min_value=0,
            ),
            extension_doc_hash=extension_doc_hash,
            output=output,
            allow_unsigned=False,
            handler=run_recover_api_command,
        )

    _run_ndjson_command(
        _run,
        started=(
            "recover",
            _recover_started_args_for_error(
                ctx,
                state=state,
                config=config,
                paper=paper,
                fallback_file=fallback_file,
                payloads_file=payloads_file,
                scan=scan,
                passphrase=passphrase,
                shard_fallback_file=shard_fallback_file,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                auth_fallback_file=auth_fallback_file,
                auth_payloads_file=auth_payloads_file,
                extension_index=extension_index,
                extension_doc_hash=extension_doc_hash,
                output=output,
            ),
        ),
    )


def inspect_recover(
    ctx: typer.Context,
    fallback_file: Annotated[
        str | None,
        typer.Option("--fallback-file", "-f", help="Main recovery text (fallback, z-base-32)."),
    ] = None,
    payloads_file: Annotated[
        str | None,
        typer.Option("--payloads-file", help="Main QR payloads (one per line)."),
    ] = None,
    scan: Annotated[
        list[str] | None,
        typer.Option("--scan", help="Scan path (image/PDF/dir, repeatable)."),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option("--passphrase", help="Passphrase to decrypt with."),
    ] = None,
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option("--shard-fallback-file", help="Shard recovery text file (repeatable)."),
    ] = None,
    shard_dir: Annotated[
        str | None,
        typer.Option("--shard-dir", help="Directory containing shard text files."),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option("--shard-payloads-file", help="Shard QR payload file (repeatable)."),
    ] = None,
    shard_scan: Annotated[
        list[str] | None,
        typer.Option("--shard-scan", help="Shard scan path (image/PDF/dir, repeatable)."),
    ] = None,
    auth_fallback_file: Annotated[
        str | None,
        typer.Option("--auth-fallback-file", help="Auth recovery text (fallback, z-base-32)."),
    ] = None,
    auth_payloads_file: Annotated[
        str | None,
        typer.Option("--auth-payloads-file", help="Auth QR payloads (one per line)."),
    ] = None,
    extension_index: Annotated[
        str | None,
        typer.Option(
            "--extension-index",
            help="Inspect through a specific extension index.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    extension_doc_hash: Annotated[
        str | None,
        typer.Option(
            "--extension-doc-hash",
            help="Inspect through the extension with this authenticated doc hash.",
        ),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option("--paper", help="Paper size override (A4/Letter)."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        return _run_recover_operation(
            ctx=ctx,
            state=state,
            config=config,
            paper=paper,
            fallback_file=fallback_file,
            payloads_file=payloads_file,
            scan=scan,
            passphrase=passphrase,
            shard_fallback_file=shard_fallback_file,
            shard_dir=shard_dir,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            auth_fallback_file=auth_fallback_file,
            auth_payloads_file=auth_payloads_file,
            extension_index=_parse_api_int_option(
                "--extension-index",
                extension_index,
                min_value=0,
            ),
            extension_doc_hash=extension_doc_hash,
            output=None,
            allow_unsigned=False,
            handler=run_recover_inspect_api_command,
        )

    _run_ndjson_command(
        _run,
        started=(
            "recover",
            _recover_started_args_for_error(
                ctx,
                state=state,
                config=config,
                paper=paper,
                fallback_file=fallback_file,
                payloads_file=payloads_file,
                scan=scan,
                passphrase=passphrase,
                shard_fallback_file=shard_fallback_file,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                auth_fallback_file=auth_fallback_file,
                auth_payloads_file=auth_payloads_file,
                extension_index=extension_index,
                extension_doc_hash=extension_doc_hash,
                output=None,
                operation="inspect",
            ),
        ),
    )


def backup(
    ctx: typer.Context,
    input: Annotated[
        list[Path] | None,
        typer.Option("--input", "-i", help="File to include (repeatable, use - for stdin)."),
    ] = None,
    input_dir: Annotated[
        list[Path] | None,
        typer.Option("--input-dir", help="Folder to include (recursive, repeatable)."),
    ] = None,
    base_dir: Annotated[
        str | None,
        typer.Option("--base-dir", help="Base path for stored relative names."),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option(
            "--output-dir",
            "-o",
            help=(
                "Where to write PDFs. Existing directories are treated as parent folders; "
                "new paths are created exactly."
            ),
        ),
    ] = None,
    qr_chunk_size: Annotated[
        str | None,
        typer.Option(
            "--qr-chunk-size",
            help="Preferred ciphertext bytes per QR frame.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option("--passphrase", help="Passphrase to encrypt with."),
    ] = None,
    passphrase_generate: Annotated[
        bool,
        typer.Option(
            "--generate-passphrase", "--passphrase-generate", help="Generate a mnemonic passphrase."
        ),
    ] = False,
    passphrase_words: Annotated[
        str | None,
        typer.Option(
            "--passphrase-words",
            help="Mnemonic word count for generated passphrases.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    sealed: Annotated[
        bool,
        typer.Option("--sealed", help="Seal backup (no new shards later)."),
    ] = False,
    shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--shard-threshold",
            help="Minimum shards needed to recover.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    shard_count: Annotated[
        str | None,
        typer.Option(
            "--shard-count",
            help="Total shard documents to create.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_mode: Annotated[
        str | None,
        typer.Option(
            "--signing-key-mode",
            help="Signing key handling for sharded backups.",
            click_type=_MODE_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Signing-key shard threshold.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Signing-key shard count.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    layout_debug_dir: Annotated[
        str | None,
        typer.Option(
            "--layout-debug-dir", help="Write per-document layout diagnostics JSON files."
        ),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option("--paper", help="Paper size override (A4/Letter)."),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option("--design", help="Template design folder."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        config_value, paper_value = _resolve_api_config_and_paper(ctx, config, paper)
        args = _build_backup_api_args(
            state=state,
            config_value=config_value,
            paper_value=paper_value,
            design=design,
            input=input,
            input_dir=input_dir,
            base_dir=base_dir,
            output_dir=output_dir,
            qr_chunk_size=qr_chunk_size,
            passphrase=passphrase,
            passphrase_generate=passphrase_generate,
            passphrase_words=passphrase_words,
            sealed=sealed,
            shard_threshold=shard_threshold,
            shard_count=shard_count,
            signing_key_mode=signing_key_mode,
            signing_key_shard_threshold=signing_key_shard_threshold,
            signing_key_shard_count=signing_key_shard_count,
            layout_debug_dir=layout_debug_dir,
        )
        return run_backup_api_command(args)

    _run_ndjson_command(
        _run,
        started=(
            "backup",
            _backup_started_args_for_error(
                ctx,
                state=state,
                config=config,
                paper=paper,
                design=design,
                input=input,
                input_dir=input_dir,
                base_dir=base_dir,
                output_dir=output_dir,
                qr_chunk_size=qr_chunk_size,
                passphrase=passphrase,
                passphrase_generate=passphrase_generate,
                passphrase_words=passphrase_words,
                sealed=sealed,
                shard_threshold=shard_threshold,
                shard_count=shard_count,
                signing_key_mode=signing_key_mode,
                signing_key_shard_threshold=signing_key_shard_threshold,
                signing_key_shard_count=signing_key_shard_count,
                layout_debug_dir=layout_debug_dir,
            ),
        ),
    )


def inspect_extend(
    ctx: typer.Context,
    root_dir: Annotated[
        str | None,
        typer.Option(
            "--root-dir",
            help="Backup root folder (writable backup root) to inspect. Required in API mode.",
        ),
    ] = None,
    input: Annotated[
        list[Path] | None,
        typer.Option("--input", "-i", help="File to include in selected scope (repeatable)."),
    ] = None,
    input_dir: Annotated[
        list[Path] | None,
        typer.Option("--input-dir", help="Directory to include in selected scope (repeatable)."),
    ] = None,
    base_dir: Annotated[
        str | None,
        typer.Option("--base-dir", help="Base path for stored relative names."),
    ] = None,
    qr_chunk_size: Annotated[
        str | None,
        typer.Option(
            "--qr-chunk-size",
            help="Preferred ciphertext bytes per QR frame.",
            metavar="INTEGER",
        ),
    ] = None,
    layout_debug_dir: Annotated[
        str | None,
        typer.Option(
            "--layout-debug-dir",
            help="Validate per-document layout diagnostics output policy.",
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option(
            "--passphrase",
            help=(
                "Passphrase to validate whether the extension can be unlocked "
                "(extension unlock readiness)."
            ),
        ),
    ] = None,
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-fallback-file",
            help="Passphrase shard recovery text file for unlocking the existing backup.",
        ),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-payloads-file",
            help="Passphrase shard QR payload file for unlocking the existing backup.",
        ),
    ] = None,
    shard_scan: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-scan",
            help="Passphrase shard image/PDF to scan for unlocking the existing backup.",
        ),
    ] = None,
    unlock_policy: Annotated[
        str | None,
        typer.Option(
            "--unlock-policy",
            help=(
                "Extension unlock artifact policy. Accepted values: self-contained, "
                "reuse-root. reuse-root uses the published or supplied root passphrase "
                "shard policy."
            ),
            click_type=_POLICY_HELP_TYPE,
        ),
    ] = None,
    shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--shard-threshold",
            help="Minimum passphrase shards needed to recover.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    shard_count: Annotated[
        str | None,
        typer.Option(
            "--shard-count",
            help="Total passphrase shard documents to create.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_mode: Annotated[
        str | None,
        typer.Option(
            "--signing-key-mode",
            help=(
                "Signing key handling for the new extension. Accepted values: not-stored, sharded."
            ),
            click_type=_MODE_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Signing-key shard threshold.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Signing-key shard count.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option("--paper", help="Paper size override (A4/Letter)."),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option("--design", help="Template design override for the new extension output."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        config_value, paper_value = _resolve_api_config_and_paper(ctx, config, paper)
        args = _build_extend_api_args(
            state=state,
            config_value=config_value,
            paper_value=paper_value,
            design=design,
            root_dir=root_dir,
            input=input,
            input_dir=input_dir,
            base_dir=base_dir,
            layout_debug_dir=layout_debug_dir,
            qr_chunk_size=qr_chunk_size,
            passphrase=passphrase,
            shard_fallback_file=shard_fallback_file,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            unlock_policy=unlock_policy,
            shard_threshold=shard_threshold,
            shard_count=shard_count,
            signing_key_mode=signing_key_mode,
            signing_key_shard_threshold=signing_key_shard_threshold,
            signing_key_shard_count=signing_key_shard_count,
        )
        return run_extend_inspect_api_command(args, debug=_state_debug_enabled(state))

    _run_ndjson_command(
        _run,
        started=(
            "extend",
            _extend_started_args_for_error(
                ctx,
                state=state,
                config=config,
                paper=paper,
                design=design,
                root_dir=root_dir,
                input=input,
                input_dir=input_dir,
                base_dir=base_dir,
                layout_debug_dir=layout_debug_dir,
                qr_chunk_size=qr_chunk_size,
                passphrase=passphrase,
                shard_fallback_file=shard_fallback_file,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                unlock_policy=unlock_policy,
                shard_threshold=shard_threshold,
                shard_count=shard_count,
                signing_key_mode=signing_key_mode,
                signing_key_shard_threshold=signing_key_shard_threshold,
                signing_key_shard_count=signing_key_shard_count,
                operation="inspect",
            ),
        ),
    )


def mint(
    ctx: typer.Context,
    fallback_file: Annotated[
        str | None,
        typer.Option("--fallback-file", "-f", help="Main recovery text (fallback, z-base-32)."),
    ] = None,
    payloads_file: Annotated[
        str | None,
        typer.Option("--payloads-file", help="Main QR payloads (one per line)."),
    ] = None,
    scan: Annotated[
        list[str] | None,
        typer.Option("--scan", help="Scan path (image/PDF/dir, repeatable)."),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option("--passphrase", help="Passphrase to decrypt with."),
    ] = None,
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option("--shard-fallback-file", help="Existing passphrase shard recovery text file."),
    ] = None,
    shard_dir: Annotated[
        str | None,
        typer.Option(
            "--shard-dir", help="Directory containing existing passphrase shard text files."
        ),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option("--shard-payloads-file", help="Existing passphrase shard QR payload file."),
    ] = None,
    shard_scan: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-scan", help="Existing passphrase shard scan path (image/PDF/dir, repeatable)."
        ),
    ] = None,
    auth_fallback_file: Annotated[
        str | None,
        typer.Option("--auth-fallback-file", help="Auth recovery text (fallback, z-base-32)."),
    ] = None,
    auth_payloads_file: Annotated[
        str | None,
        typer.Option("--auth-payloads-file", help="Auth QR payloads (one per line)."),
    ] = None,
    extension_index: Annotated[
        str | None,
        typer.Option(
            "--extension-index",
            help="Mint against a specific extension index (0 = root only).",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    extension_doc_hash: Annotated[
        str | None,
        typer.Option(
            "--extension-doc-hash",
            help="Mint against the extension with this authenticated doc hash.",
        ),
    ] = None,
    signing_key_shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option(
            "--signing-key-shard-fallback-file",
            help="Signing-key shard recovery text file.",
        ),
    ] = None,
    signing_key_shard_dir: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-dir",
            help="Directory containing signing-key shard text files.",
        ),
    ] = None,
    signing_key_shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--signing-key-shard-payloads-file",
            help="Signing-key shard QR payload file.",
        ),
    ] = None,
    signing_key_shard_scan: Annotated[
        list[str] | None,
        typer.Option(
            "--signing-key-shard-scan",
            help="Signing-key shard scan path (image/PDF/dir, repeatable).",
        ),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option("--output-dir", "-o", help="Where to write minted shard PDFs."),
    ] = None,
    layout_debug_dir: Annotated[
        str | None,
        typer.Option("--layout-debug-dir", help="Write layout diagnostics JSON files."),
    ] = None,
    shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--shard-threshold",
            help="Minimum fresh passphrase shards needed to recover.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    shard_count: Annotated[
        str | None,
        typer.Option(
            "--shard-count",
            help="Total fresh passphrase shard documents to create.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Minimum fresh signing-key shards needed to recover.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Total fresh signing-key shard documents to create.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    passphrase_replacement_count: Annotated[
        str | None,
        typer.Option(
            "--passphrase-replacement-count",
            help="Mint this many compatible replacement passphrase shards.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_replacement_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-replacement-count",
            help="Mint this many compatible replacement signing-key shards.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    mint_passphrase_shards: Annotated[
        bool,
        typer.Option(
            "--passphrase-shards/--no-passphrase-shards",
            help="Mint fresh passphrase shard documents.",
        ),
    ] = True,
    mint_signing_key_shards: Annotated[
        bool,
        typer.Option(
            "--signing-key-shards/--no-signing-key-shards",
            help="Mint fresh signing-key shard documents.",
        ),
    ] = True,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option("--paper", help="Paper size override (A4/Letter)."),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option("--design", help="Template design folder."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        return _run_mint_operation(
            ctx=ctx,
            state=state,
            config=config,
            paper=paper,
            design=design,
            fallback_file=fallback_file,
            payloads_file=payloads_file,
            scan=scan,
            passphrase=passphrase,
            shard_fallback_file=shard_fallback_file,
            shard_dir=shard_dir,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            auth_fallback_file=auth_fallback_file,
            auth_payloads_file=auth_payloads_file,
            extension_index=_parse_api_int_option(
                "--extension-index",
                extension_index,
                min_value=0,
            ),
            extension_doc_hash=extension_doc_hash,
            signing_key_shard_fallback_file=signing_key_shard_fallback_file,
            signing_key_shard_dir=signing_key_shard_dir,
            signing_key_shard_payloads_file=signing_key_shard_payloads_file,
            signing_key_shard_scan=signing_key_shard_scan,
            output_dir=output_dir,
            layout_debug_dir=layout_debug_dir,
            shard_threshold=shard_threshold,
            shard_count=shard_count,
            signing_key_shard_threshold=signing_key_shard_threshold,
            signing_key_shard_count=signing_key_shard_count,
            passphrase_replacement_count=passphrase_replacement_count,
            signing_key_replacement_count=signing_key_replacement_count,
            mint_passphrase_shards=mint_passphrase_shards,
            mint_signing_key_shards=mint_signing_key_shards,
            handler=run_mint_api_command,
        )

    _run_ndjson_command(
        _run,
        started=(
            "mint",
            _mint_started_args_for_error(
                ctx,
                state=state,
                config=config,
                paper=paper,
                design=design,
                fallback_file=fallback_file,
                payloads_file=payloads_file,
                scan=scan,
                passphrase=passphrase,
                shard_fallback_file=shard_fallback_file,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                auth_fallback_file=auth_fallback_file,
                auth_payloads_file=auth_payloads_file,
                extension_index=extension_index,
                extension_doc_hash=extension_doc_hash,
                signing_key_shard_fallback_file=signing_key_shard_fallback_file,
                signing_key_shard_payloads_file=signing_key_shard_payloads_file,
                signing_key_shard_scan=signing_key_shard_scan,
                output_dir=output_dir,
                layout_debug_dir=layout_debug_dir,
                shard_threshold=shard_threshold,
                shard_count=shard_count,
                signing_key_shard_threshold=signing_key_shard_threshold,
                signing_key_shard_count=signing_key_shard_count,
                passphrase_replacement_count=passphrase_replacement_count,
                signing_key_replacement_count=signing_key_replacement_count,
                mint_passphrase_shards=mint_passphrase_shards,
                mint_signing_key_shards=mint_signing_key_shards,
            ),
        ),
    )


def inspect_mint(
    ctx: typer.Context,
    fallback_file: Annotated[
        str | None,
        typer.Option("--fallback-file", "-f", help="Main recovery text (fallback, z-base-32)."),
    ] = None,
    payloads_file: Annotated[
        str | None,
        typer.Option("--payloads-file", help="Main QR payloads (one per line)."),
    ] = None,
    scan: Annotated[
        list[str] | None,
        typer.Option("--scan", help="Scan path (image/PDF/dir, repeatable)."),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option("--passphrase", help="Passphrase to decrypt with."),
    ] = None,
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option("--shard-fallback-file", help="Existing passphrase shard recovery text file."),
    ] = None,
    shard_dir: Annotated[
        str | None,
        typer.Option(
            "--shard-dir", help="Directory containing existing passphrase shard text files."
        ),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option("--shard-payloads-file", help="Existing passphrase shard QR payload file."),
    ] = None,
    shard_scan: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-scan", help="Existing passphrase shard scan path (image/PDF/dir, repeatable)."
        ),
    ] = None,
    auth_fallback_file: Annotated[
        str | None,
        typer.Option("--auth-fallback-file", help="Auth recovery text (fallback, z-base-32)."),
    ] = None,
    auth_payloads_file: Annotated[
        str | None,
        typer.Option("--auth-payloads-file", help="Auth QR payloads (one per line)."),
    ] = None,
    extension_index: Annotated[
        str | None,
        typer.Option(
            "--extension-index",
            help="Inspect minting against a specific extension index (0 = root only).",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    extension_doc_hash: Annotated[
        str | None,
        typer.Option(
            "--extension-doc-hash",
            help="Inspect minting against the extension with this authenticated doc hash.",
        ),
    ] = None,
    signing_key_shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option(
            "--signing-key-shard-fallback-file",
            help="Signing-key shard recovery text file.",
        ),
    ] = None,
    signing_key_shard_dir: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-dir",
            help="Directory containing signing-key shard text files.",
        ),
    ] = None,
    signing_key_shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--signing-key-shard-payloads-file",
            help="Signing-key shard QR payload file.",
        ),
    ] = None,
    signing_key_shard_scan: Annotated[
        list[str] | None,
        typer.Option(
            "--signing-key-shard-scan",
            help="Signing-key shard scan path (image/PDF/dir, repeatable).",
        ),
    ] = None,
    shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--shard-threshold",
            help="Minimum fresh passphrase shards needed to recover.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    shard_count: Annotated[
        str | None,
        typer.Option(
            "--shard-count",
            help="Total fresh passphrase shard documents to create.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Minimum fresh signing-key shards needed to recover.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Total fresh signing-key shard documents to create.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    passphrase_replacement_count: Annotated[
        str | None,
        typer.Option(
            "--passphrase-replacement-count",
            help="Mint this many compatible replacement passphrase shards.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    signing_key_replacement_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-replacement-count",
            help="Mint this many compatible replacement signing-key shards.",
            click_type=_INTEGER_HELP_TYPE,
        ),
    ] = None,
    mint_passphrase_shards: Annotated[
        bool,
        typer.Option(
            "--passphrase-shards/--no-passphrase-shards",
            help="Mint fresh passphrase shard documents.",
        ),
    ] = True,
    mint_signing_key_shards: Annotated[
        bool,
        typer.Option(
            "--signing-key-shards/--no-signing-key-shards",
            help="Mint fresh signing-key shard documents.",
        ),
    ] = True,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option("--paper", help="Paper size override (A4/Letter)."),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option("--design", help="Template design folder."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        return _run_mint_operation(
            ctx=ctx,
            state=state,
            config=config,
            paper=paper,
            design=design,
            fallback_file=fallback_file,
            payloads_file=payloads_file,
            scan=scan,
            passphrase=passphrase,
            shard_fallback_file=shard_fallback_file,
            shard_dir=shard_dir,
            shard_payloads_file=shard_payloads_file,
            shard_scan=shard_scan,
            auth_fallback_file=auth_fallback_file,
            auth_payloads_file=auth_payloads_file,
            extension_index=_parse_api_int_option(
                "--extension-index",
                extension_index,
                min_value=0,
            ),
            extension_doc_hash=extension_doc_hash,
            signing_key_shard_fallback_file=signing_key_shard_fallback_file,
            signing_key_shard_dir=signing_key_shard_dir,
            signing_key_shard_payloads_file=signing_key_shard_payloads_file,
            signing_key_shard_scan=signing_key_shard_scan,
            output_dir=None,
            layout_debug_dir=None,
            shard_threshold=shard_threshold,
            shard_count=shard_count,
            signing_key_shard_threshold=signing_key_shard_threshold,
            signing_key_shard_count=signing_key_shard_count,
            passphrase_replacement_count=passphrase_replacement_count,
            signing_key_replacement_count=signing_key_replacement_count,
            mint_passphrase_shards=mint_passphrase_shards,
            mint_signing_key_shards=mint_signing_key_shards,
            handler=run_mint_inspect_api_command,
        )

    _run_ndjson_command(
        _run,
        started=(
            "mint",
            _mint_started_args_for_error(
                ctx,
                state=state,
                config=config,
                paper=paper,
                design=design,
                fallback_file=fallback_file,
                payloads_file=payloads_file,
                scan=scan,
                passphrase=passphrase,
                shard_fallback_file=shard_fallback_file,
                shard_payloads_file=shard_payloads_file,
                shard_scan=shard_scan,
                auth_fallback_file=auth_fallback_file,
                auth_payloads_file=auth_payloads_file,
                extension_index=extension_index,
                extension_doc_hash=extension_doc_hash,
                signing_key_shard_fallback_file=signing_key_shard_fallback_file,
                signing_key_shard_payloads_file=signing_key_shard_payloads_file,
                signing_key_shard_scan=signing_key_shard_scan,
                output_dir=None,
                layout_debug_dir=None,
                shard_threshold=shard_threshold,
                shard_count=shard_count,
                signing_key_shard_threshold=signing_key_shard_threshold,
                signing_key_shard_count=signing_key_shard_count,
                passphrase_replacement_count=passphrase_replacement_count,
                signing_key_replacement_count=signing_key_replacement_count,
                mint_passphrase_shards=mint_passphrase_shards,
                mint_signing_key_shards=mint_signing_key_shards,
                operation="inspect",
            ),
        ),
    )


__all__ = ["register"]
