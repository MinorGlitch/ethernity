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

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

import typer

from ...config import BackupDefaults
from .. import api_codes
from ..core.common import _ctx_state, _paper_callback, _resolve_config_and_paper
from ..core.types import BackupArgs, RecoverArgs
from ..flows.backup_api import run_backup_api_command
from ..flows.kit_api import run_kit_api_command
from ..flows.recover_api import run_recover_api_command
from ..flows.recover_service import (
    RecoverShardDirError,
    apply_recover_stdin_default,
    expand_recover_shard_dir,
)
from ..flows.settings_api import run_settings_get_api_command, run_settings_set_api_command
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

_KIT_HELP = (
    "Generate a recovery kit QR document and emit NDJSON progress/events.\n\n"
    "This command is intended for GUI or automation use."
)

_SETTINGS_HELP = "Machine-readable settings surface for GUI integrations."


def register(app: typer.Typer) -> None:
    api_app = typer.Typer(help=_API_HELP, add_completion=False)
    api_app.command(name="backup", help=_BACKUP_HELP)(backup)
    api_app.command(name="kit", help=_KIT_HELP)(kit)
    api_app.command(name="recover", help=_RECOVER_HELP)(recover)
    settings_app = typer.Typer(help=_SETTINGS_HELP, add_completion=False)
    settings_app.command(name="get", help="Load GUI-managed settings.")(settings_get)
    settings_app.command(name="set", help="Persist GUI-managed settings.")(settings_set)
    api_app.add_typer(settings_app, name="settings")
    app.add_typer(api_app, name="api")


def _run_ndjson_command(func: Callable[[], int | None]) -> None:
    with ndjson_session():
        try:
            result = func()
        except KeyboardInterrupt as exc:
            emit_error(
                code=error_code_for_exception(exc),
                message="Cancelled by user",
                details={"error_type": type(exc).__name__},
            )
            raise typer.Exit(code=130) from exc
        except (OSError, RuntimeError, ValueError, TypeError, LookupError) as exc:
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
        typer.Option(
            "--shard-fallback-file",
            help="Shard recovery text, QR payload, image, or PDF file (repeatable).",
        ),
    ] = None,
    shard_dir: Annotated[
        str | None,
        typer.Option("--shard-dir", help="Directory containing shard text files."),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-payloads-file",
            help="Shard QR payload, image, or PDF file (repeatable).",
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
        typer.Option("--paper", help="Paper size override (A4/Letter).", callback=_paper_callback),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
        fallback_value = apply_recover_stdin_default(
            fallback_file,
            payloads_file,
            list(scan or []),
            stdin_is_tty=sys.stdin.isatty(),
        )

        shard_files = list(shard_fallback_file or [])
        shard_files.extend(_expand_shard_dir(shard_dir))

        args = RecoverArgs(
            config=config_value,
            paper=paper_value,
            fallback_file=fallback_value,
            payloads_file=payloads_file,
            scan=list(scan or []),
            passphrase=passphrase,
            shard_fallback_file=shard_files,
            shard_payloads_file=list(shard_payloads_file or []),
            auth_fallback_file=auth_fallback_file,
            auth_payloads_file=auth_payloads_file,
            output=output,
            allow_unsigned=allow_unsigned,
            assume_yes=True,
            debug_max_bytes=state.debug_max_bytes if state is not None else 0,
            debug_reveal_secrets=state.debug_reveal_secrets if state is not None else False,
            quiet=True,
        )
        debug_value = state.debug if state is not None else False
        return run_recover_api_command(args, debug=debug_value)

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
        typer.Option("--output-dir", "-o", help="Where to write PDFs (default: backup-<doc_id>)."),
    ] = None,
    qr_chunk_size: Annotated[
        int | None,
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
        int | None,
        typer.Option("--passphrase-words", help="Mnemonic word count for generated passphrases."),
    ] = None,
    sealed: Annotated[
        bool,
        typer.Option("--sealed", help="Seal backup (no new shards later)."),
    ] = False,
    shard_threshold: Annotated[
        int | None,
        typer.Option("--shard-threshold", help="Minimum shards needed to recover."),
    ] = None,
    shard_count: Annotated[
        int | None,
        typer.Option("--shard-count", help="Total shard documents to create."),
    ] = None,
    signing_key_mode: Annotated[
        Literal["embedded", "sharded"] | None,
        typer.Option("--signing-key-mode", help="Signing key handling for sharded backups."),
    ] = None,
    signing_key_shard_threshold: Annotated[
        int | None,
        typer.Option("--signing-key-shard-threshold", help="Signing-key shard threshold."),
    ] = None,
    signing_key_shard_count: Annotated[
        int | None,
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
        typer.Option("--paper", help="Paper size override (A4/Letter).", callback=_paper_callback),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option("--design", help="Template design folder."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
        design_value = design or (state.design if state is not None else None)
        defaults = state.backup_defaults if state is not None else None
        if not isinstance(defaults, BackupDefaults):
            defaults = BackupDefaults()

        output_dir_value = output_dir if output_dir is not None else defaults.output_dir
        base_dir_value = base_dir if base_dir is not None else defaults.base_dir
        shard_threshold_value = (
            shard_threshold if shard_threshold is not None else defaults.shard_threshold
        )
        shard_count_value = shard_count if shard_count is not None else defaults.shard_count
        signing_key_mode_value = (
            signing_key_mode if signing_key_mode is not None else defaults.signing_key_mode
        )
        signing_key_shard_threshold_value = (
            signing_key_shard_threshold
            if signing_key_shard_threshold is not None
            else defaults.signing_key_shard_threshold
        )
        signing_key_shard_count_value = (
            signing_key_shard_count
            if signing_key_shard_count is not None
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
            layout_debug_dir=layout_debug_dir,
            qr_chunk_size=qr_chunk_size,
            passphrase=passphrase,
            passphrase_generate=passphrase_generate,
            passphrase_words=passphrase_words,
            sealed=sealed,
            shard_threshold=shard_threshold_value,
            shard_count=shard_count_value,
            signing_key_mode=signing_key_mode_value,
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


def kit(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output PDF path."),
    ] = None,
    bundle: Annotated[
        Path | None,
        typer.Option("--bundle", "-b", help="Custom recovery kit HTML bundle."),
    ] = None,
    qr_chunk_size: Annotated[
        int | None,
        typer.Option("--qr-chunk-size", help="Payload bytes per QR chunk."),
    ] = None,
    variant: Annotated[
        str,
        typer.Option("--variant", help="Recovery kit variant: lean or scanner."),
    ] = "lean",
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use a custom TOML configuration file."),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option("--paper", help="Paper size override (A4/Letter).", callback=_paper_callback),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option("--design", help="Template design folder."),
    ] = None,
) -> None:
    state = _ctx_state(ctx)

    def _run() -> int:
        config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
        design_value = design or (state.design if state is not None else None)
        return run_kit_api_command(
            bundle=bundle,
            output=output,
            config_value=config_value,
            paper_value=paper_value,
            design_value=design_value,
            variant_value=variant.strip().lower(),
            qr_chunk_size=qr_chunk_size,
        )

    _run_ndjson_command(_run)


def settings_get(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
) -> None:
    _ = ctx

    def _run() -> int:
        return run_settings_get_api_command(config_path=config)

    _run_ndjson_command(_run)


def settings_set(
    ctx: typer.Context,
    config: Annotated[
        str | None,
        typer.Option("--config", help="Use this config file."),
    ] = None,
    template_design: Annotated[
        str,
        typer.Option("--template-design", help="Template design folder."),
    ] = "sentinel",
    page_size: Annotated[
        str,
        typer.Option("--page-size", help="Page size override (A4/LETTER)."),
    ] = "A4",
    backup_output_dir: Annotated[
        str,
        typer.Option("--backup-output-dir", help="Default backup output directory."),
    ] = "",
    qr_chunk_size: Annotated[
        int,
        typer.Option("--qr-chunk-size", help="Default preferred QR chunk size."),
    ] = 512,
    backup_shard_threshold: Annotated[
        int,
        typer.Option("--backup-shard-threshold", help="Default backup shard threshold (0 clears)."),
    ] = 0,
    backup_shard_count: Annotated[
        int,
        typer.Option("--backup-shard-count", help="Default backup shard count (0 clears)."),
    ] = 0,
    signing_key_mode: Annotated[
        str,
        typer.Option(
            "--signing-key-mode",
            help="Default signing key mode: embedded, sharded, or empty to clear.",
        ),
    ] = "",
    signing_key_shard_threshold: Annotated[
        int,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Default signing-key shard threshold (0 clears).",
        ),
    ] = 0,
    signing_key_shard_count: Annotated[
        int,
        typer.Option(
            "--signing-key-shard-count",
            help="Default signing-key shard count (0 clears).",
        ),
    ] = 0,
    recover_output_dir: Annotated[
        str,
        typer.Option("--recover-output-dir", help="Default recover output directory."),
    ] = "",
) -> None:
    _ = ctx

    def _run() -> int:
        return run_settings_set_api_command(
            config_path=config,
            design=template_design,
            page_size=page_size,
            backup_output_dir=backup_output_dir,
            qr_chunk_size=qr_chunk_size,
            backup_shard_threshold=backup_shard_threshold,
            backup_shard_count=backup_shard_count,
            signing_key_mode=signing_key_mode,
            signing_key_shard_threshold=signing_key_shard_threshold,
            signing_key_shard_count=signing_key_shard_count,
            recover_output_dir=recover_output_dir,
        )

    _run_ndjson_command(_run)


__all__ = ["register"]
