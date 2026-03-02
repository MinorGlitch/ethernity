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

import functools
from pathlib import Path
from typing import Annotated, Literal

import typer

from ...config import BackupDefaults
from ..api import DEBUG_MAX_BYTES_DEFAULT, console_err
from ..core.common import _ctx_state, _paper_callback, _resolve_config_and_paper, _run_cli
from ..core.types import BackupArgs
from ..flows.backup import _should_use_wizard_for_backup, run_backup_command, run_wizard

_BACKUP_HELP = (
    "Create a backup PDF.\n\n"
    "Examples:\n"
    "  ethernity backup -i secrets.txt\n"
    "  ethernity backup --input-dir docs --output-dir backups\n"
)


def register(app: typer.Typer) -> None:
    app.command(help=_BACKUP_HELP)(backup)


def backup(
    ctx: typer.Context,
    input: Annotated[
        list[Path] | None,
        typer.Option(
            "--input",
            "-i",
            help="File to include (repeatable, use - for stdin).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    input_dir: Annotated[
        list[Path] | None,
        typer.Option(
            "--input-dir",
            help="Folder to include (recursive, repeatable).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    base_dir: Annotated[
        str | None,
        typer.Option(
            "--base-dir",
            help="Base path for stored relative names.",
            rich_help_panel="Advanced",
        ),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Where to write PDFs (default: backup-<doc_id>).",
            rich_help_panel="Outputs",
        ),
    ] = None,
    layout_debug_dir: Annotated[
        str | None,
        typer.Option(
            "--layout-debug-dir",
            help=(
                "Write per-document layout diagnostics JSON files to this directory "
                "(for pagination/capacity debugging)."
            ),
            rich_help_panel="Advanced",
        ),
    ] = None,
    qr_chunk_size: Annotated[
        int | None,
        typer.Option(
            "--qr-chunk-size",
            help=(
                "Preferred ciphertext bytes per QR frame. Lower values create more codes "
                "but easier scanning; renderer may reduce to fit."
            ),
            rich_help_panel="Config",
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option(
            "--passphrase",
            help="Passphrase to encrypt with.",
            rich_help_panel="Encryption",
        ),
    ] = None,
    passphrase_generate: Annotated[
        bool,
        typer.Option(
            "--generate-passphrase",
            "--passphrase-generate",
            help="Generate a mnemonic passphrase (default if none).",
            rich_help_panel="Encryption",
        ),
    ] = False,
    passphrase_words: Annotated[
        int | None,
        typer.Option(
            "--passphrase-words",
            help="Mnemonic word count for generated passphrases (12/15/18/21/24).",
            rich_help_panel="Encryption",
        ),
    ] = None,
    sealed: Annotated[
        bool,
        typer.Option(
            "--sealed",
            help="Seal backup (no new shards later).",
            rich_help_panel="Sharding",
        ),
    ] = False,
    shard_threshold: Annotated[
        int | None,
        typer.Option(
            "--shard-threshold",
            help="Minimum shards needed to recover (e.g., 2 for '2 of 3').",
            rich_help_panel="Sharding",
        ),
    ] = None,
    shard_count: Annotated[
        int | None,
        typer.Option(
            "--shard-count",
            help="Total shard documents to create (e.g., 3 for '2 of 3').",
            rich_help_panel="Sharding",
        ),
    ] = None,
    signing_key_mode: Annotated[
        Literal["embedded", "sharded"] | None,
        typer.Option(
            "--signing-key-mode",
            help=(
                "Signing key handling for sharded passphrase backups: "
                "embedded (inside main doc) or sharded (separate signing-key PDFs)."
            ),
            rich_help_panel="Sharding",
        ),
    ] = None,
    signing_key_shard_threshold: Annotated[
        int | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Signing-key shard threshold (n). Requires --signing-key-mode sharded.",
            rich_help_panel="Sharding",
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        int | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Signing-key shard count (k). Requires --signing-key-mode sharded.",
            rich_help_panel="Sharding",
        ),
    ] = None,
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            help="Use this config file.",
            rich_help_panel="Config",
        ),
    ] = None,
    paper: Annotated[
        str | None,
        typer.Option(
            "--paper",
            help="Paper size override (A4/Letter).",
            callback=_paper_callback,
            rich_help_panel="Config",
        ),
    ] = None,
    design: Annotated[
        str | None,
        typer.Option(
            "--design",
            help="Template design folder (auto-discovered under templates/).",
            rich_help_panel="Config",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Show plaintext debug details.",
            rich_help_panel="Debug",
        ),
    ] = False,
    debug_max_bytes: Annotated[
        int | None,
        typer.Option(
            "--debug-max-bytes",
            help=f"Limit debug dump size (default: {DEBUG_MAX_BYTES_DEFAULT}, 0 = no limit).",
            rich_help_panel="Debug",
        ),
    ] = None,
    assume_yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompts and proceed.",
            rich_help_panel="Behavior",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            help="Hide non-error output.",
            rich_help_panel="Behavior",
        ),
    ] = False,
) -> None:
    state = _ctx_state(ctx)
    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    design_value = design or (state.design if state is not None else None)
    defaults = state.backup_defaults if state is not None else None
    if not isinstance(defaults, BackupDefaults):
        defaults = BackupDefaults()

    debug_value = debug or (state.debug if state is not None else False)
    debug_max_value = (
        (state.debug_max_bytes if state is not None else 0)
        if debug_max_bytes is None
        else debug_max_bytes
    )
    debug_reveal_value = state.debug_reveal_secrets if state is not None else False
    quiet_value = quiet or (state.quiet if state is not None else False)
    base_dir_value = base_dir if base_dir is not None else defaults.base_dir
    output_dir_value = output_dir if output_dir is not None else defaults.output_dir
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
        debug=debug_value,
        debug_max_bytes=debug_max_value,
        debug_reveal_secrets=debug_reveal_value,
        assume_yes=assume_yes,
        quiet=quiet_value,
    )
    if _should_use_wizard_for_backup(args):
        _run_cli(
            functools.partial(
                run_wizard,
                debug_override=debug_value if debug_value else None,
                debug_max_bytes=debug_max_value,
                debug_reveal_secrets=debug_reveal_value,
                config_path=config_value,
                paper_size=paper_value,
                quiet=quiet_value,
                args=args,
            ),
            debug=debug_value,
        )
        return
    if not args.input and not args.input_dir:
        console_err.print(
            "Input is required for non-interactive backup. "
            "Use --input PATH, --input-dir DIR, or --input - for stdin."
        )
        raise typer.Exit(code=2)
    _run_cli(functools.partial(run_backup_command, args), debug=debug_value)
