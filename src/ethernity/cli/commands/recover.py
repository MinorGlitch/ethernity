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
import sys
from pathlib import Path
from typing import Annotated

import typer

from ...config import RecoverDefaults
from ..core.common import _ctx_state, _paper_callback, _resolve_config_and_paper, _run_cli
from ..core.paths import expanduser_cli_path
from ..core.types import RecoverArgs
from ..flows.recover import _should_use_wizard_for_recover, run_recover_command, run_recover_wizard


def _expand_shard_dir(shard_dir: str | None) -> list[str]:
    """Expand shard directory to list of .txt files."""
    if not shard_dir:
        return []
    path = Path(expanduser_cli_path(shard_dir, preserve_stdin=False) or "")
    if not path.exists():
        raise typer.BadParameter(f"shard directory not found: {shard_dir}")
    if not path.is_dir():
        raise typer.BadParameter(f"shard-dir must be a directory: {shard_dir}")
    files = sorted(path.glob("*.txt"))
    if not files:
        raise typer.BadParameter(f"no .txt files found in shard directory: {shard_dir}")
    return [str(f) for f in files]


def register(app: typer.Typer) -> None:
    app.command(
        help=(
            "Recover data from QR payloads or recovery text (fallback).\n\n"
            "Examples:\n"
            "  ethernity recover --scan ./scans\n"
            "  ethernity recover --fallback-file recovery.txt --output recovered.bin\n"
            "  ethernity recover --payloads-file qr_payloads.txt\n"
        )
    )(recover)


def recover(
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
            help="Shard recovery text file (repeatable).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    shard_dir: Annotated[
        str | None,
        typer.Option(
            "--shard-dir",
            help="Directory containing shard text files (auto-discovers *.txt files).",
            rich_help_panel="Inputs",
        ),
    ] = None,
    shard_payloads_file: Annotated[
        list[str] | None,
        typer.Option(
            "--shard-payloads-file",
            help="Shard QR payload file (repeatable).",
            rich_help_panel="Inputs",
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
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Output file/dir (default: stdout for single-file recovery; "
                "multi-file recovery requires --output directory)."
            ),
            rich_help_panel="Output",
        ),
    ] = None,
    allow_unsigned: Annotated[
        bool,
        typer.Option(
            "--rescue-mode",
            "--skip-auth-check",
            help=(
                "Enable rescue mode and continue without authentication verification "
                "(legacy alias: --skip-auth-check)."
            ),
            rich_help_panel="Verification",
        ),
    ] = False,
    assume_yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompts and proceed.",
            rich_help_panel="Behavior",
        ),
    ] = False,
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
    defaults = state.recover_defaults if state is not None else None
    if not isinstance(defaults, RecoverDefaults):
        defaults = RecoverDefaults()
    output_value = output if output is not None else defaults.output
    debug_max_value = state.debug_max_bytes if state is not None else 0
    debug_reveal_value = state.debug_reveal_secrets if state is not None else False

    if not fallback_file and not payloads_file and not (scan or []) and not sys.stdin.isatty():
        fallback_file = "-"

    # Expand shard_dir to individual files and combine with explicit files
    shard_files = list(shard_fallback_file or [])
    shard_files.extend(_expand_shard_dir(shard_dir))

    args = RecoverArgs(
        config=config_value,
        paper=paper_value,
        fallback_file=fallback_file,
        payloads_file=payloads_file,
        scan=list(scan or []),
        passphrase=passphrase,
        shard_fallback_file=shard_files,
        shard_payloads_file=list(shard_payloads_file or []),
        auth_fallback_file=auth_fallback_file,
        auth_payloads_file=auth_payloads_file,
        output=output_value,
        allow_unsigned=allow_unsigned,
        assume_yes=assume_yes,
        debug_max_bytes=debug_max_value,
        debug_reveal_secrets=debug_reveal_value,
        quiet=quiet_value,
    )
    if _should_use_wizard_for_recover(args):
        _run_cli(functools.partial(run_recover_wizard, args, debug=debug_value), debug=debug_value)
        return
    _run_cli(functools.partial(run_recover_command, args, debug=debug_value), debug=debug_value)
