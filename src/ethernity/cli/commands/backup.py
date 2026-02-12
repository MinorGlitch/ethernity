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
from typing import Literal

import typer

from ..api import DEBUG_MAX_BYTES_DEFAULT, console_err
from ..core.common import _ctx_value, _paper_callback, _resolve_config_and_paper, _run_cli
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
    input: list[Path] | None = typer.Option(
        None,
        "--input",
        "-i",
        help="File to include (repeatable, use - for stdin).",
        rich_help_panel="Inputs",
    ),
    input_dir: list[Path] | None = typer.Option(
        None,
        "--input-dir",
        help="Folder to include (recursive, repeatable).",
        rich_help_panel="Inputs",
    ),
    base_dir: str | None = typer.Option(
        None,
        "--base-dir",
        help="Base path for stored relative names.",
        rich_help_panel="Advanced",
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Where to write PDFs (default: backup-<doc_id>).",
        rich_help_panel="Outputs",
    ),
    qr_chunk_size: int | None = typer.Option(
        None,
        "--qr-chunk-size",
        help=(
            "Preferred ciphertext bytes per QR frame. Lower values create more codes "
            "but easier scanning; renderer may reduce to fit."
        ),
        rich_help_panel="Config",
    ),
    passphrase: str | None = typer.Option(
        None,
        "--passphrase",
        help="Passphrase to encrypt with.",
        rich_help_panel="Encryption",
    ),
    passphrase_generate: bool = typer.Option(
        False,
        "--generate-passphrase",
        "--passphrase-generate",
        help="Generate a mnemonic passphrase (default if none).",
        rich_help_panel="Encryption",
    ),
    passphrase_words: int | None = typer.Option(
        None,
        "--passphrase-words",
        help="Mnemonic word count for generated passphrases (12/15/18/21/24).",
        rich_help_panel="Encryption",
    ),
    sealed: bool = typer.Option(
        False,
        "--sealed",
        help="Seal backup (no new shards later).",
        rich_help_panel="Sharding",
    ),
    shard_threshold: int | None = typer.Option(
        None,
        "--shard-threshold",
        help="Minimum shards needed to recover (e.g., 2 for '2 of 3').",
        rich_help_panel="Sharding",
    ),
    shard_count: int | None = typer.Option(
        None,
        "--shard-count",
        help="Total shard documents to create (e.g., 3 for '2 of 3').",
        rich_help_panel="Sharding",
    ),
    signing_key_mode: Literal["embedded", "sharded"] | None = typer.Option(
        None,
        "--signing-key-mode",
        help=(
            "Signing key handling for sharded passphrase backups: embedded (inside main doc) or "
            "sharded (separate signing-key PDFs)."
        ),
        rich_help_panel="Sharding",
    ),
    signing_key_shard_threshold: int | None = typer.Option(
        None,
        "--signing-key-shard-threshold",
        help="Signing-key shard threshold (n). Requires --signing-key-mode sharded.",
        rich_help_panel="Sharding",
    ),
    signing_key_shard_count: int | None = typer.Option(
        None,
        "--signing-key-shard-count",
        help="Signing-key shard count (k). Requires --signing-key-mode sharded.",
        rich_help_panel="Sharding",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        help="Use this config file.",
        rich_help_panel="Config",
    ),
    paper: str | None = typer.Option(
        None,
        "--paper",
        help="Paper size override (A4/Letter).",
        callback=_paper_callback,
        rich_help_panel="Config",
    ),
    design: str | None = typer.Option(
        None,
        "--design",
        help="Template design folder (auto-discovered under templates/).",
        rich_help_panel="Config",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Show plaintext debug details.",
        rich_help_panel="Debug",
    ),
    debug_max_bytes: int | None = typer.Option(
        None,
        "--debug-max-bytes",
        help=f"Limit debug dump size (default: {DEBUG_MAX_BYTES_DEFAULT}, 0 = no limit).",
        rich_help_panel="Debug",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Hide non-error output.",
        rich_help_panel="Behavior",
    ),
) -> None:
    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    design_value = design or _ctx_value(ctx, "design")
    debug_value = debug or bool(_ctx_value(ctx, "debug"))
    debug_max_value = (
        int(_ctx_value(ctx, "debug_max_bytes") or 0) if debug_max_bytes is None else debug_max_bytes
    )
    quiet_value = quiet or bool(_ctx_value(ctx, "quiet"))
    args = BackupArgs(
        config=config_value,
        paper=paper_value,
        design=design_value,
        input=[str(path) for path in (input or [])],
        input_dir=[str(path) for path in (input_dir or [])],
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
        debug=debug_value,
        debug_max_bytes=debug_max_value,
        quiet=quiet_value,
    )
    if _should_use_wizard_for_backup(args):
        _run_cli(
            functools.partial(
                run_wizard,
                debug_override=debug_value if debug_value else None,
                debug_max_bytes=debug_max_value,
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
