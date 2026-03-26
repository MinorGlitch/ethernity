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
from typing import Annotated

import typer

from ethernity.cli.features.mint.workflow import (
    _should_use_wizard_for_mint,
    run_mint_command,
    run_mint_wizard,
)
from ethernity.cli.shared.common import (
    _ctx_state,
    _paper_callback,
    _resolve_config_and_paper,
    _run_cli,
)
from ethernity.cli.shared.paths import expanduser_cli_path
from ethernity.cli.shared.types import MintArgs

_MINT_HELP = (
    "Mint fresh shard PDFs for an existing backup.\n\n"
    "Examples:\n"
    "  ethernity mint --payloads-file qr.txt --passphrase '...' "
    "--shard-threshold 2 --shard-count 3\n"
    "  ethernity mint --scan scans --shard-payloads-file old_shards.txt "
    "--signing-key-shard-payloads-file signing_shards.txt --shard-threshold 2 --shard-count 5\n"
    "  ethernity mint --payloads-file qr.txt --passphrase '...' --shard-payloads-file old.txt "
    "--passphrase-replacement-count 1 --no-signing-key-shards\n"
)


def register(app: typer.Typer) -> None:
    app.command(help=_MINT_HELP)(mint)


def _expand_shard_dir(shard_dir: str | None, *, label: str) -> list[str]:
    """Expand a shard directory to a sorted list of `.txt` files."""

    if not shard_dir:
        return []
    path = Path(expanduser_cli_path(shard_dir, preserve_stdin=False) or "")
    if not path.exists():
        raise typer.BadParameter(f"{label} directory not found: {shard_dir}")
    if not path.is_dir():
        raise typer.BadParameter(f"{label}-dir must be a directory: {shard_dir}")
    files = sorted(path.glob("*.txt"))
    if not files:
        raise typer.BadParameter(f"no .txt files found in {label} directory: {shard_dir}")
    return [str(file_path) for file_path in files]


def mint(
    ctx: typer.Context,
    fallback_file: Annotated[
        str | None,
        typer.Option(
            "--fallback-file",
            "-f",
            help="Main recovery text (fallback, z-base-32, use - for stdin).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    payloads_file: Annotated[
        str | None,
        typer.Option(
            "--payloads-file",
            help="Main QR payloads (one per line).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    scan: Annotated[
        list[str] | None,
        typer.Option(
            "--scan",
            help="Scan path (image/PDF/dir, repeatable).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option(
            "--passphrase",
            help="Passphrase to decrypt with.",
            rich_help_panel="Keys",
        ),
    ] = None,
    shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-fallback-file",
            help="Existing passphrase shard recovery text file (repeatable).",
            rich_help_panel="Keys",
        ),
    ] = None,
    shard_dir: Annotated[
        str | None,
        typer.Option(
            "--shard-dir",
            help="Directory containing existing passphrase shard text files.",
            rich_help_panel="Keys",
        ),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-payloads-file",
            help="Existing passphrase shard QR payload file (repeatable).",
            rich_help_panel="Keys",
        ),
    ] = None,
    auth_fallback_file: Annotated[
        str | None,
        typer.Option(
            "--auth-fallback-file",
            help="Auth recovery text (fallback, z-base-32, use - for stdin).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    auth_payloads_file: Annotated[
        str | None,
        typer.Option(
            "--auth-payloads-file",
            help="Auth QR payloads (one per line).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    signing_key_shard_fallback_file: Annotated[
        list[str] | None,
        typer.Option(
            "--signing-key-shard-fallback-file",
            help="Signing-key shard recovery text file (repeatable).",
            rich_help_panel="Keys",
        ),
    ] = None,
    signing_key_shard_dir: Annotated[
        str | None,
        typer.Option(
            "--signing-key-shard-dir",
            help="Directory containing signing-key shard text files.",
            rich_help_panel="Keys",
        ),
    ] = None,
    signing_key_shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--signing-key-shard-payloads-file",
            help="Signing-key shard QR payload file (repeatable).",
            rich_help_panel="Keys",
        ),
    ] = None,
    signing_key_shard_scan: Annotated[
        list[str] | None,
        typer.Option(
            "--signing-key-shard-scan",
            help="Signing-key shard scan path (image/PDF/dir, repeatable).",
            rich_help_panel="Keys",
        ),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Where to write minted shard PDFs (default: mint-<doc_id>).",
            rich_help_panel="Outputs",
        ),
    ] = None,
    layout_debug_dir: Annotated[
        str | None,
        typer.Option(
            "--layout-debug-dir",
            help="Write layout diagnostics JSON files to this directory.",
            rich_help_panel="Advanced",
        ),
    ] = None,
    shard_threshold: Annotated[
        int | None,
        typer.Option(
            "--shard-threshold",
            help="Minimum fresh passphrase shards needed to recover.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    shard_count: Annotated[
        int | None,
        typer.Option(
            "--shard-count",
            help="Total fresh passphrase shard documents to create.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    signing_key_shard_threshold: Annotated[
        int | None,
        typer.Option(
            "--signing-key-shard-threshold",
            help="Minimum fresh signing-key shards needed to recover.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    signing_key_shard_count: Annotated[
        int | None,
        typer.Option(
            "--signing-key-shard-count",
            help="Total fresh signing-key shard documents to create.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    passphrase_replacement_count: Annotated[
        int | None,
        typer.Option(
            "--passphrase-replacement-count",
            help="Mint this many compatible replacement passphrase shards.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    signing_key_replacement_count: Annotated[
        int | None,
        typer.Option(
            "--signing-key-replacement-count",
            help="Mint this many compatible replacement signing-key shards.",
            rich_help_panel="Outputs",
        ),
    ] = None,
    mint_passphrase_shards: Annotated[
        bool,
        typer.Option(
            "--passphrase-shards/--no-passphrase-shards",
            help="Mint fresh passphrase shard documents.",
            rich_help_panel="Outputs",
        ),
    ] = True,
    mint_signing_key_shards: Annotated[
        bool,
        typer.Option(
            "--signing-key-shards/--no-signing-key-shards",
            help="Mint fresh signing-key shard documents.",
            rich_help_panel="Outputs",
        ),
    ] = True,
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
    quiet_value = quiet or (state.quiet if state is not None else False)
    debug_value = state.debug if state is not None else False
    design_value = design or (state.design if state is not None else None)

    passphrase_shard_files = list(shard_fallback_file or [])
    passphrase_shard_files.extend(_expand_shard_dir(shard_dir, label="shard"))
    signing_key_shard_files = list(signing_key_shard_fallback_file or [])
    signing_key_shard_files.extend(
        _expand_shard_dir(signing_key_shard_dir, label="signing-key shard")
    )

    args = MintArgs(
        config=config_value,
        paper=paper_value,
        design=design_value,
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
        quiet=quiet_value,
    )
    if _should_use_wizard_for_mint(args):
        _run_cli(functools.partial(run_mint_wizard, args, debug=debug_value), debug=debug_value)
        return
    _run_cli(functools.partial(run_mint_command, args, debug=debug_value), debug=debug_value)
