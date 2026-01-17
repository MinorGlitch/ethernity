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

import typer

from ..core.common import _ctx_value, _paper_callback, _resolve_config_and_paper, _run_cli
from ..core.types import RecoverArgs
from ..flows.recover import _should_use_wizard_for_recover, run_recover_command, run_recover_wizard


def _expand_shard_dir(shard_dir: str | None) -> list[str]:
    """Expand shard directory to list of .txt files."""
    if not shard_dir:
        return []
    path = Path(shard_dir).expanduser()
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
    fallback_file: str | None = typer.Option(
        None,
        "--fallback-file",
        "-f",
        help="Main recovery text (fallback, z-base-32, use - for stdin).",
        rich_help_panel="Inputs",
    ),
    payloads_file: str | None = typer.Option(
        None,
        "--payloads-file",
        help="Main QR payloads (one per line).",
        rich_help_panel="Inputs",
    ),
    scan: list[str] | None = typer.Option(
        None,
        "--scan",
        help="Scan path (image/PDF/dir, repeatable).",
        rich_help_panel="Inputs",
    ),
    passphrase: str | None = typer.Option(
        None,
        "--passphrase",
        help="Passphrase to decrypt with.",
        rich_help_panel="Keys",
    ),
    shard_fallback_file: list[str] | None = typer.Option(
        None,
        "--shard-fallback-file",
        help="Shard recovery text file (repeatable).",
        rich_help_panel="Inputs",
    ),
    shard_dir: str | None = typer.Option(
        None,
        "--shard-dir",
        help="Directory containing shard text files (auto-discovers *.txt files).",
        rich_help_panel="Inputs",
    ),
    shard_payloads_file: list[str] | None = typer.Option(
        None,
        "--shard-payloads-file",
        help="Shard QR payload file (repeatable).",
        rich_help_panel="Inputs",
    ),
    auth_fallback_file: str | None = typer.Option(
        None,
        "--auth-fallback-file",
        help="Auth recovery text (fallback, z-base-32, use - for stdin).",
        rich_help_panel="Inputs",
    ),
    auth_payloads_file: str | None = typer.Option(
        None,
        "--auth-payloads-file",
        help="Auth QR payloads (one per line).",
        rich_help_panel="Inputs",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file/dir (default: stdout).",
        rich_help_panel="Output",
    ),
    allow_unsigned: bool = typer.Option(
        False,
        "--skip-auth-check",
        help="Skip authentication verification (use only if you trust the source).",
        rich_help_panel="Verification",
    ),
    assume_yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompts and proceed.",
        rich_help_panel="Behavior",
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
        help="Paper preset (A4/LETTER).",
        callback=_paper_callback,
        rich_help_panel="Config",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Hide non-error output.",
        rich_help_panel="Behavior",
    ),
) -> None:
    config_value, paper_value = _resolve_config_and_paper(ctx, config, paper)
    quiet_value = quiet or bool(_ctx_value(ctx, "quiet"))
    debug_value = bool(_ctx_value(ctx, "debug"))

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
        shard_dir=shard_dir,
        shard_payloads_file=list(shard_payloads_file or []),
        auth_fallback_file=auth_fallback_file,
        auth_payloads_file=auth_payloads_file,
        output=output,
        allow_unsigned=allow_unsigned,
        assume_yes=assume_yes,
        quiet=quiet_value,
    )
    if _should_use_wizard_for_recover(args):
        _run_cli(functools.partial(run_recover_wizard, args, debug=debug_value), debug=debug_value)
        return
    _run_cli(functools.partial(run_recover_command, args, debug=debug_value), debug=debug_value)
