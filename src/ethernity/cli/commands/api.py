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
from typing import Annotated, Literal, cast

import typer

from ...config import BackupDefaults
from .. import api_codes
from ..core.common import _ctx_state, _paper_callback, _resolve_config_and_paper
from ..core.paths import expanduser_cli_path
from ..core.types import BackupArgs, ConfigGetArgs, ConfigSetArgs, MintArgs, RecoverArgs
from ..flows.backup_api import run_backup_api_command
from ..flows.config_api import run_config_get_api_command, run_config_set_api_command
from ..flows.mint_api import run_mint_api_command, run_mint_inspect_api_command
from ..flows.recover_api import run_recover_api_command, run_recover_inspect_api_command
from ..flows.recover_service import (
    RecoverShardDirError,
    expand_recover_shard_dir,
)
from ..ndjson import (
    ApiCommandError,
    emit_error,
    error_code_for_exception,
    error_details_for_exception,
    ndjson_session,
)

_API_HELP = (
    "Machine-readable CLI surface for GUI and automation integrations.\n\n"
    "Commands under `ethernity api` write NDJSON events to stdout."
)

_RECOVER_HELP = (
    "Recover data from QR payloads or fallback text and emit NDJSON progress/events.\n\n"
    "This command is intended for GUI or automation use and requires --output."
)

_BACKUP_HELP = (
    "Create backup documents and emit NDJSON progress/events.\n\n"
    "This command is intended for GUI or automation use."
)

_MINT_HELP = (
    "Mint fresh shard PDFs for an existing backup and emit NDJSON progress/events.\n\n"
    "This command is intended for GUI or automation use."
)

_CONFIG_HELP = (
    "Read or update app configuration and onboarding metadata via NDJSON.\n\n"
    "This command is intended for GUI and automation use."
)

_INSPECT_HELP = (
    "Inspect recover and mint readiness and emit NDJSON state/events.\n\n"
    "Inspect commands do not write files or emit artifact events."
)

SigningKeyMode = Literal["embedded", "sharded"]


def register(app: typer.Typer) -> None:
    api_app = typer.Typer(help=_API_HELP, add_completion=False)
    config_app = typer.Typer(help=_CONFIG_HELP, add_completion=False)
    inspect_app = typer.Typer(help=_INSPECT_HELP, add_completion=False)
    api_app.command(name="backup", help=_BACKUP_HELP)(backup)
    api_app.command(name="mint", help=_MINT_HELP)(mint)
    api_app.command(name="recover", help=_RECOVER_HELP)(recover)
    inspect_app.command(
        name="recover",
        help="Inspect recover readiness via NDJSON.",
    )(inspect_recover)
    inspect_app.command(name="mint", help="Inspect mint readiness via NDJSON.")(inspect_mint)
    config_app.command(name="get", help="Read the active config as NDJSON.")(config_get)
    config_app.command(name="set", help="Apply a JSON config patch and emit NDJSON.")(config_set)
    api_app.add_typer(inspect_app, name="inspect")
    api_app.add_typer(config_app, name="config")
    app.add_typer(api_app, name="api")


def _run_ndjson_command(func: Callable[[], int | None]) -> None:
    with ndjson_session():
        try:
            result = func()
        except typer.Exit:
            raise
        except KeyboardInterrupt as exc:
            emit_error(
                code=error_code_for_exception(exc),
                message="Cancelled by user",
                details={"error_type": type(exc).__name__},
            )
            raise typer.Exit(code=130) from exc
        except Exception as exc:
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


def _parse_api_int_option(name: str, value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value, 10)
    except ValueError as exc:
        raise ApiCommandError(
            code=api_codes.INVALID_INPUT,
            message=f"{name} must be an integer",
            details={"option": name, "value": value},
        ) from exc


def _parse_signing_key_mode(value: str | None) -> str | None:
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


def _build_recover_api_args(
    *,
    state: object,
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
    output: str | None,
    allow_unsigned: bool,
) -> RecoverArgs:
    shard_files = list(shard_fallback_file or [])
    shard_files.extend(_expand_shard_dir(shard_dir))
    ctx_state = cast(object | None, state)
    debug_max_bytes = getattr(ctx_state, "debug_max_bytes", 0) if ctx_state is not None else 0
    debug_reveal_secrets = (
        getattr(ctx_state, "debug_reveal_secrets", False) if ctx_state is not None else False
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
        output=output,
        allow_unsigned=allow_unsigned,
        assume_yes=True,
        debug_max_bytes=debug_max_bytes,
        debug_reveal_secrets=debug_reveal_secrets,
        quiet=True,
    )


def _build_mint_api_args(
    *,
    state: object,
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
    auth_fallback_file: str | None,
    auth_payloads_file: str | None,
    signing_key_shard_fallback_file: list[str] | None,
    signing_key_shard_dir: str | None,
    signing_key_shard_payloads_file: list[str] | None,
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
    ctx_state = cast(object | None, state)
    return MintArgs(
        config=config_value,
        paper=paper_value,
        design=design or (getattr(ctx_state, "design", None) if ctx_state is not None else None),
        fallback_file=fallback_file,
        payloads_file=payloads_file,
        scan=list(scan or []),
        passphrase=passphrase,
        shard_fallback_file=passphrase_shard_files,
        shard_payloads_file=list(shard_payloads_file or []),
        auth_fallback_file=auth_fallback_file,
        auth_payloads_file=auth_payloads_file,
        signing_key_shard_fallback_file=signing_key_shard_files,
        signing_key_shard_payloads_file=list(signing_key_shard_payloads_file or []),
        output_dir=output_dir,
        output_dir_existing_parent=True,
        layout_debug_dir=layout_debug_dir,
        shard_threshold=_parse_api_int_option("--shard-threshold", shard_threshold),
        shard_count=_parse_api_int_option("--shard-count", shard_count),
        signing_key_shard_threshold=_parse_api_int_option(
            "--signing-key-shard-threshold",
            signing_key_shard_threshold,
        ),
        signing_key_shard_count=_parse_api_int_option(
            "--signing-key-shard-count",
            signing_key_shard_count,
        ),
        passphrase_replacement_count=_parse_api_int_option(
            "--passphrase-replacement-count",
            passphrase_replacement_count,
        ),
        signing_key_replacement_count=_parse_api_int_option(
            "--signing-key-replacement-count",
            signing_key_replacement_count,
        ),
        mint_passphrase_shards=mint_passphrase_shards,
        mint_signing_key_shards=mint_signing_key_shards,
        quiet=True,
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

    _run_ndjson_command(_run)


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

    _run_ndjson_command(_run)


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
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Output file or directory path. Required in API mode."),
    ] = None,
    allow_unsigned: Annotated[
        bool,
        typer.Option(
            "--rescue-mode",
            "--skip-auth-check",
            help="Enable rescue mode and continue without authentication verification.",
        ),
    ] = False,
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
        config_value, paper_value = _resolve_api_config_and_paper(ctx, config, paper)
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
            output=output,
            allow_unsigned=allow_unsigned,
        )
        debug_value = state.debug if state is not None else False
        return run_recover_api_command(args, debug=debug_value)

    _run_ndjson_command(_run)


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
    allow_unsigned: Annotated[
        bool,
        typer.Option(
            "--rescue-mode",
            "--skip-auth-check",
            help="Enable rescue mode and continue without authentication verification.",
        ),
    ] = False,
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
        config_value, paper_value = _resolve_api_config_and_paper(ctx, config, paper)
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
            output=None,
            allow_unsigned=allow_unsigned,
        )
        debug_value = state.debug if state is not None else False
        return run_recover_inspect_api_command(args, debug=debug_value)

    _run_ndjson_command(_run)


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
        typer.Option("--qr-chunk-size", help="Preferred ciphertext bytes per QR frame."),
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
        typer.Option("--passphrase-words", help="Mnemonic word count for generated passphrases."),
    ] = None,
    sealed: Annotated[
        bool,
        typer.Option("--sealed", help="Seal backup (no new shards later)."),
    ] = False,
    shard_threshold: Annotated[
        str | None,
        typer.Option("--shard-threshold", help="Minimum shards needed to recover."),
    ] = None,
    shard_count: Annotated[
        str | None,
        typer.Option("--shard-count", help="Total shard documents to create."),
    ] = None,
    signing_key_mode: Annotated[
        str | None,
        typer.Option("--signing-key-mode", help="Signing key handling for sharded backups."),
    ] = None,
    signing_key_shard_threshold: Annotated[
        str | None,
        typer.Option("--signing-key-shard-threshold", help="Signing-key shard threshold."),
    ] = None,
    signing_key_shard_count: Annotated[
        str | None,
        typer.Option("--signing-key-shard-count", help="Signing-key shard count."),
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
        design_value = design or (state.design if state is not None else None)
        defaults = state.backup_defaults if state is not None else None
        if not isinstance(defaults, BackupDefaults):
            defaults = BackupDefaults()

        qr_chunk_size_value = _parse_api_int_option("--qr-chunk-size", qr_chunk_size)
        passphrase_words_value = _parse_api_int_option("--passphrase-words", passphrase_words)
        shard_threshold_cli = _parse_api_int_option("--shard-threshold", shard_threshold)
        shard_count_cli = _parse_api_int_option("--shard-count", shard_count)
        signing_key_mode_cli = _parse_signing_key_mode(signing_key_mode)
        signing_key_shard_threshold_cli = _parse_api_int_option(
            "--signing-key-shard-threshold",
            signing_key_shard_threshold,
        )
        signing_key_shard_count_cli = _parse_api_int_option(
            "--signing-key-shard-count",
            signing_key_shard_count,
        )

        output_dir_value = output_dir if output_dir is not None else defaults.output_dir
        base_dir_value = base_dir if base_dir is not None else defaults.base_dir
        shard_threshold_value = (
            shard_threshold_cli if shard_threshold_cli is not None else defaults.shard_threshold
        )
        shard_count_value = shard_count_cli if shard_count_cli is not None else defaults.shard_count
        signing_key_mode_value = (
            signing_key_mode_cli if signing_key_mode_cli is not None else defaults.signing_key_mode
        )
        signing_key_shard_threshold_value = (
            signing_key_shard_threshold_cli
            if signing_key_shard_threshold_cli is not None
            else defaults.signing_key_shard_threshold
        )
        signing_key_shard_count_value = (
            signing_key_shard_count_cli
            if signing_key_shard_count_cli is not None
            else defaults.signing_key_shard_count
        )

        args = BackupArgs(
            config=config_value,
            paper=paper_value,
            design=design_value,
            input=[str(path) for path in (input or [])],
            input_dir=[str(path) for path in (input_dir or [])],
            base_dir=base_dir_value,
            output_dir=output_dir_value,
            output_dir_existing_parent=True,
            layout_debug_dir=layout_debug_dir,
            qr_chunk_size=qr_chunk_size_value,
            passphrase=passphrase,
            passphrase_generate=passphrase_generate,
            passphrase_words=passphrase_words_value,
            sealed=sealed,
            shard_threshold=shard_threshold_value,
            shard_count=shard_count_value,
            signing_key_mode=cast(SigningKeyMode | None, signing_key_mode_value),
            signing_key_shard_threshold=signing_key_shard_threshold_value,
            signing_key_shard_count=signing_key_shard_count_value,
            debug=state.debug if state is not None else False,
            debug_max_bytes=state.debug_max_bytes if state is not None else 0,
            debug_reveal_secrets=state.debug_reveal_secrets if state is not None else False,
            assume_yes=True,
            quiet=True,
        )
        return run_backup_api_command(args)

    _run_ndjson_command(_run)


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
    auth_fallback_file: Annotated[
        str | None,
        typer.Option("--auth-fallback-file", help="Auth recovery text (fallback, z-base-32)."),
    ] = None,
    auth_payloads_file: Annotated[
        str | None,
        typer.Option("--auth-payloads-file", help="Auth QR payloads (one per line)."),
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
            "--shard-threshold", help="Minimum fresh passphrase shards needed to recover."
        ),
    ] = None,
    shard_count: Annotated[
        str | None,
        typer.Option("--shard-count", help="Total fresh passphrase shard documents to create."),
    ] = None,
    signing_key_shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Minimum fresh signing-key shards needed to recover.",
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Total fresh signing-key shard documents to create.",
        ),
    ] = None,
    passphrase_replacement_count: Annotated[
        str | None,
        typer.Option(
            "--passphrase-replacement-count",
            help="Mint this many compatible replacement passphrase shards.",
        ),
    ] = None,
    signing_key_replacement_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-replacement-count",
            help="Mint this many compatible replacement signing-key shards.",
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
            auth_fallback_file=auth_fallback_file,
            auth_payloads_file=auth_payloads_file,
            signing_key_shard_fallback_file=list(signing_key_shard_fallback_file or []),
            signing_key_shard_dir=signing_key_shard_dir,
            signing_key_shard_payloads_file=list(signing_key_shard_payloads_file or []),
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
        debug_value = state.debug if state is not None else False
        return run_mint_api_command(args, debug=debug_value)

    _run_ndjson_command(_run)


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
    auth_fallback_file: Annotated[
        str | None,
        typer.Option("--auth-fallback-file", help="Auth recovery text (fallback, z-base-32)."),
    ] = None,
    auth_payloads_file: Annotated[
        str | None,
        typer.Option("--auth-payloads-file", help="Auth QR payloads (one per line)."),
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
    layout_debug_dir: Annotated[
        str | None,
        typer.Option("--layout-debug-dir", help="Write layout diagnostics JSON files."),
    ] = None,
    shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--shard-threshold", help="Minimum fresh passphrase shards needed to recover."
        ),
    ] = None,
    shard_count: Annotated[
        str | None,
        typer.Option("--shard-count", help="Total fresh passphrase shard documents to create."),
    ] = None,
    signing_key_shard_threshold: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Minimum fresh signing-key shards needed to recover.",
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Total fresh signing-key shard documents to create.",
        ),
    ] = None,
    passphrase_replacement_count: Annotated[
        str | None,
        typer.Option(
            "--passphrase-replacement-count",
            help="Mint this many compatible replacement passphrase shards.",
        ),
    ] = None,
    signing_key_replacement_count: Annotated[
        str | None,
        typer.Option(
            "--signing-key-replacement-count",
            help="Mint this many compatible replacement signing-key shards.",
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
            auth_fallback_file=auth_fallback_file,
            auth_payloads_file=auth_payloads_file,
            signing_key_shard_fallback_file=list(signing_key_shard_fallback_file or []),
            signing_key_shard_dir=signing_key_shard_dir,
            signing_key_shard_payloads_file=list(signing_key_shard_payloads_file or []),
            output_dir=None,
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
        debug_value = state.debug if state is not None else False
        return run_mint_inspect_api_command(args, debug=debug_value)

    _run_ndjson_command(_run)


__all__ = ["register"]
